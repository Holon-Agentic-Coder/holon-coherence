"""Host-local LLM endpoint routing between the host and the containerized proxy.

The optimization proxy normally runs inside a Docker container, so a request the agent
addresses at the machine itself cannot be resolved from the container's network
namespace: ``localhost`` / ``127.0.0.1`` belong to the container, and the host's own LAN
address is not routable from the Docker Desktop VM. Every one of those spellings denotes
the same thing from the host's point of view, and from inside the container they must all
resolve to the same place: ``host.docker.internal``.

Two halves live here:

* **Host side** (used by ``cli.py``): expand a declared ``--local-llm-base`` authority into
  its *equivalence class* (every literal that denotes "this machine"), work out which
  ``NO_PROXY`` entries would silently bypass it, and hand the allow list to the container.
* **Container side** (used by ``mitm_addon.py``): decide, per outbound connection, whether
  the requested authority must be dialled via the Docker host gateway.

Safety invariant: rewriting is opt-in and address-specific. Loopback plus explicitly
declared or host-detected addresses are rewritten; arbitrary RFC1918 peers are never
rewritten, so a genuinely remote inference box on the same LAN cannot be hijacked onto
the host.
"""

from __future__ import annotations

import contextlib
import ipaddress
import logging
import os
import re
import socket
from typing import NamedTuple

GATEWAY_HOSTNAME = "host.docker.internal"
"""Docker's name for the host as seen from inside a container."""

HOST_LOCAL_ENV_VAR = "HOLON_HOST_LOCAL_HOSTS"
"""Container environment variable carrying the allow list of host-local authorities."""

NO_PROXY_WILDCARD = "*"

_LOOPBACK_NAMES = frozenset({"localhost", "ip6-localhost", "ip6-loopback"})

_CANONICAL_LOOPBACK_HOSTS = ("localhost", "127.0.0.1", "::1")
"""Loopback spellings treated as the same endpoint as a declared loopback base."""

_HOST_CHARS_RE = re.compile(r"^[A-Za-z0-9._:\-\[\]]+$")
_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*$")
_SPLIT_SPEC_RE = re.compile(r"[,;\s]+")
_SPLIT_AUTHORITY_RE = re.compile(r"[/?#]")
_ROUTING_PROBE_ENDPOINTS = (
    (socket.AF_INET, ("8.8.8.8", 1)),
    (socket.AF_INET6, ("2001:4860:4860::8888", 1)),
)
_EXCLUDED_HOST_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
    ipaddress.ip_network("172.17.0.0/16"),  # Default Docker bridge (docker0 / 172.17.0.1)
    ipaddress.ip_network("100.64.0.0/10"),  # RFC 6598 Carrier-Grade NAT / Tailscale / virtual tunnel
)


class LocalTarget(NamedTuple):
    """A host-local endpoint: a normalized host literal and an optional port."""

    host: str
    port: int | None = None

    @property
    def canonical(self) -> str:
        """Render as a ``host:port`` (or bare ``host``) token for the allow list."""
        if self.port is None:
            return self.host
        return f"[{self.host}]:{self.port}" if ":" in self.host else f"{self.host}:{self.port}"


class RewriteDecision(NamedTuple):
    """Outcome of a container-side rewrite check."""

    address: tuple[str, int] | None
    reason: str

    @property
    def should_rewrite(self) -> bool:
        """True when the connection must be dialled via the gateway address."""
        return self.address is not None


class PruningPlan(NamedTuple):
    """Result of reconciling a ``NO_PROXY`` value against a declared local endpoint."""

    keep: tuple[str, ...]
    remove: tuple[str, ...]
    blocked_by_wildcard: bool

    @property
    def intercepted(self) -> bool:
        """True when traffic to the target reaches the proxy once ``remove`` is dropped."""
        return bool(self.remove) and not self.blocked_by_wildcard


class PruningResult(NamedTuple):
    """A rewritten ``NO_PROXY`` value plus what was taken out of it."""

    value: str
    plan: PruningPlan


def normalize_host(raw: str) -> str:
    """Normalize a host literal: strip brackets, trailing dot, whitespace; lowercase."""
    return raw.strip().strip("[]").split("%", 1)[0].rstrip(".").lower()


def is_loopback_host(host: str) -> bool:
    """True for ``localhost``, ``.localhost`` subdomains (RFC 6761), and loopback ranges (127.0.0.0/8, ::1)."""
    normalized = normalize_host(host)
    if normalized in _LOOPBACK_NAMES or normalized.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def _split_authority(value: str) -> tuple[str | None, int | None]:
    """Split ``host``, ``host:port`` or ``[ipv6]:port`` into a normalized host and optional port."""
    value = value.strip()
    if not value:
        return None, None

    if value.startswith("["):
        match = re.match(r"^\[([^\]]+)\](?::(\d+))?$", value)
        if not match:
            return None, None
        host, port = match.group(1), match.group(2)
    else:
        if value.count(":") > 1:
            # Unbracketed IPv6 literal (``fe80::1``): its last group is an address part, not a port.
            # Must be a valid IPv6 literal; reject malformed strings like `:::11434`.
            try:
                ipaddress.IPv6Address(value)
            except ValueError:
                return None, None
            host, port = value, None
        else:
            head, sep, tail = value.rpartition(":")
            if tail.isdigit():
                host, port = head, tail
            elif sep:
                # ``host:notaport`` or ``host:`` is a mistake, not a portless host or an unbracketed IPv6.
                return None, None
            else:
                host, port = value, None

    host = normalize_host(host)
    if not host or not _HOST_CHARS_RE.match(host):
        return None, None
    if _is_unspecified_address(host):
        # 0.0.0.0 / :: are bind addresses, not endpoints anyone can dial.
        return None, None
    if port is None:
        return host, None

    port_num = int(port)
    if not (1 <= port_num <= 65535):
        return None, None
    return host, port_num


def _is_unspecified_address(host: str) -> bool:
    """True for the unspecified addresses ``0.0.0.0`` and ``::``."""
    try:
        return ipaddress.ip_address(host).is_unspecified
    except ValueError:
        return False


def parse_local_target(raw: str | None) -> LocalTarget | None:
    """Parse a declared local endpoint.

    Accepts the spellings users actually paste: ``localhost:8081``, ``127.0.0.1:8081``,
    ``192.168.2.13:8081``, ``[::1]:8081`` and whole base URLs such as
    ``http://localhost:8081/v1``. Returns ``None`` when no usable host can be read.
    """
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    scheme = None
    if "://" in value:
        scheme_part, _, remainder = value.partition("://")
        if not _SCHEME_RE.match(scheme_part):
            return None
        scheme = scheme_part.lower()
        value = remainder
    value = _SPLIT_AUTHORITY_RE.split(value, 1)[0]
    host, port = _split_authority(value)
    if host is None:
        return None
    if port is None and scheme:
        if scheme == "http":
            port = 80
        elif scheme == "https":
            port = 443
    return LocalTarget(host, port)


_parse_url = parse_local_target


def detect_host_addresses() -> tuple[str, ...]:
    """Return the host's own non-loopback unicast addresses.

    Safe to rewrite onto the gateway *because these addresses are the host*: the probe
    runs on the host itself, before the container is started. Loopback, link-local,
    multicast, unspecified, Docker bridge (172.17.0.0/16), and virtual/CGNAT (100.64.0.0/10)
    addresses are excluded. The UDP routing probe is prioritized; hostname resolution
    serves as a best-effort fallback if probes return no addresses.
    """
    probe_addresses: set[str] = set()

    for family, endpoint in _ROUTING_PROBE_ENDPOINTS:
        try:
            with socket.socket(family, socket.SOCK_DGRAM) as sock:
                sock.connect(endpoint)
                probe_addresses.add(sock.getsockname()[0])
        except OSError:
            continue

    addresses: set[str] = set(probe_addresses)
    if not addresses:
        try:
            # Fallback to hostname resolution only if UDP routing probes failed (e.g. offline host)
            infos = socket.getaddrinfo(socket.gethostname(), None)
            for info in infos:
                addresses.add(str(info[4][0]))
        except OSError:
            pass

    logging.debug("detect_host_addresses: raw candidates before filtering: %s", addresses)

    cleaned: set[str] = set()
    for raw in addresses:
        host = normalize_host(raw)
        if not host:
            continue
        try:
            parsed = ipaddress.ip_address(host)
        except ValueError:
            continue
        if parsed.is_loopback or parsed.is_link_local or parsed.is_multicast or parsed.is_unspecified:
            continue
        if any(parsed.version == net.version and parsed in net for net in _EXCLUDED_HOST_NETWORKS):
            continue
        cleaned.add(host)
    return tuple(sorted(cleaned))


def resolve_gateway_address() -> str | None:
    """Resolve ``host.docker.internal`` to a usable gateway IP, preferring IPv4.

    Returns ``None`` when the name does not resolve (Linux without
    ``--add-host=host.docker.internal:host-gateway``) or only yields loopback.
    """
    try:
        infos = socket.getaddrinfo(GATEWAY_HOSTNAME, None, type=socket.SOCK_STREAM)
    except OSError:
        return None

    fallback: str | None = None
    for info in infos:
        host = normalize_host(str(info[4][0]))
        try:
            parsed = ipaddress.ip_address(host)
        except ValueError:
            continue
        if parsed.is_loopback or parsed.is_unspecified:
            continue
        if parsed.version == 4:
            return host
        fallback = fallback or host
    return fallback


def in_container() -> bool:
    """True when executing inside a Docker container."""
    return os.path.exists("/.dockerenv") or os.environ.get("HOLON_IN_CONTAINER") == "1"


def expand_equivalence_class(target: LocalTarget, host_addresses: tuple[str, ...] = ()) -> tuple[LocalTarget, ...]:
    """Expand one declared endpoint into every literal that denotes the same machine.

    ``localhost:8081``, ``127.0.0.1:8081``, ``[::1]:8081`` and the host's own LAN address
    all reach the same server as far as the host is concerned, so from the container they
    must all be rewritten onto the gateway. The declared port is carried through.

    A non-loopback, non-host address is returned unchanged: it may be a real remote peer.
    """
    hosts = {target.host}
    if is_loopback_host(target.host):
        hosts.update(_CANONICAL_LOOPBACK_HOSTS)
        hosts.update(host_addresses)
    elif target.host in host_addresses:
        hosts.update(host_addresses)
    if target.host != GATEWAY_HOSTNAME:
        hosts.discard(GATEWAY_HOSTNAME)
    return tuple(LocalTarget(host, target.port) for host in sorted(hosts))


def encode_targets(targets: tuple[LocalTarget, ...]) -> str:
    """Serialize an allow list for the container environment."""
    return ",".join(dict.fromkeys(target.canonical for target in targets))


def decode_targets(spec: str | None) -> tuple[LocalTarget, ...]:
    """Parse a container allow list back into targets, dropping malformed entries."""
    if not spec:
        return ()
    targets: list[LocalTarget] = []
    seen: set[str] = set()
    for token in _SPLIT_SPEC_RE.split(spec.strip()):
        if not token:
            continue
        parsed = parse_local_target(token)
        if parsed is None or parsed.canonical in seen:
            continue
        seen.add(parsed.canonical)
        targets.append(parsed)
    return tuple(targets)


def targets_from_env(environ: dict[str, str] | None = None) -> tuple[LocalTarget, ...]:
    """Read the allow list from the environment (container side)."""
    env = os.environ if environ is None else environ
    return decode_targets(env.get(HOST_LOCAL_ENV_VAR))


def decide_rewrite(
    host: str | None,
    port: int | None,
    targets: tuple[LocalTarget, ...],
    gateway_ip: str | None,
    proxy_ports: tuple[int, ...] = (),
) -> RewriteDecision:
    """Decide whether an outbound connection must be dialled via the host gateway.

    ``proxy_ports`` lists ports the proxy itself listens on; rewriting one of those would
    dial straight back into the proxy through its own published mapping.
    """
    if not host or port is None:
        return RewriteDecision(None, "no-authority")
    if not targets:
        return RewriteDecision(None, "not-configured")

    normalized = normalize_host(host)
    if normalized == GATEWAY_HOSTNAME:
        return RewriteDecision(None, "already-gateway")
    if port in proxy_ports:
        return RewriteDecision(None, "proxy-own-port")

    loopback = is_loopback_host(normalized)
    if loopback:
        if not any(is_loopback_host(t.host) for t in targets):
            return RewriteDecision(None, "not-allow-listed")
    else:
        matched = False
        for target in targets:
            if target.host != normalized:
                continue
            if target.port is None or target.port == port:
                matched = True
                break
        if not matched:
            return RewriteDecision(None, "not-allow-listed")

    if not gateway_ip:
        return RewriteDecision(None, "gateway-unresolved")
    return RewriteDecision((gateway_ip, port), "loopback" if loopback else "allow-listed")


def parse_no_proxy(value: str | None) -> tuple[str, ...]:
    """Split a ``NO_PROXY`` value into ordered, de-duplicated entries."""
    if not value:
        return ()
    entries: list[str] = []
    for token in value.split(","):
        stripped = token.strip()
        if stripped and stripped not in entries:
            entries.append(stripped)
    return tuple(entries)


def _entry_matches(entry: str, equivalence_hosts: frozenset[str], port: int | None) -> bool:
    stripped = entry.strip()
    if stripped == NO_PROXY_WILDCARD:
        return False
    if stripped.startswith("*."):
        stripped = stripped[2:]
    stripped = stripped.lstrip(".")
    host, entry_port = _split_authority(stripped)
    if host is None or host not in equivalence_hosts:
        return False
    return entry_port is None or port is None or entry_port == port


def plan_no_proxy_pruning(
    no_proxy_value: str | None,
    target: LocalTarget,
    host_addresses: tuple[str, ...] = (),
) -> PruningPlan:
    """Reconcile ``NO_PROXY`` against a declared local endpoint.

    An entry is removed when its host denotes the declared machine and it either omits a
    port or names the declared port. A wildcard ``*`` is never removed: it bypasses the
    proxy globally, so the caller must report that interception is impossible rather than
    silently discarding a deliberate global bypass.
    """
    entries = parse_no_proxy(no_proxy_value)
    if not entries:
        return PruningPlan((), (), False)

    equivalence_hosts = frozenset(entry.host for entry in expand_equivalence_class(target, host_addresses))
    remove = tuple(entry for entry in entries if _entry_matches(entry, equivalence_hosts, target.port))
    keep = tuple(entry for entry in entries if entry not in remove)
    return PruningPlan(keep=keep, remove=remove, blocked_by_wildcard=NO_PROXY_WILDCARD in entries)


def apply_no_proxy_pruning(no_proxy_value: str | None, plan: PruningPlan) -> PruningResult:
    """Materialize the pruned ``NO_PROXY`` value for a plan."""
    if plan.blocked_by_wildcard:
        return PruningResult(no_proxy_value or "", plan)
    return PruningResult(",".join(plan.keep), plan)


def rewrite_connection(
    data: object,
    targets: tuple[LocalTarget, ...],
    gateway_ip: str | None,
    proxy_ports: tuple[int, ...] = (),
) -> RewriteDecision:
    """Apply the rewrite decision to a mitmproxy ``server_connect`` payload.

    Kept separate from the hook so the decision table is unit-testable without mitmproxy.
    """
    server = getattr(data, "server", None)
    address = getattr(server, "address", None) if server is not None else None
    if not address:
        return RewriteDecision(None, "no-authority")

    decision = decide_rewrite(address[0], address[1], targets, gateway_ip, proxy_ports)
    if decision.should_rewrite and server is not None:
        with contextlib.suppress(Exception):
            server.address = decision.address
    return decision
