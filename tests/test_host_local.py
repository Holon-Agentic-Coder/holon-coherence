"""Tests for host-local LLM endpoint routing: parsing, equivalence classes, NO_PROXY pruning
and the container-side rewrite decision table."""

from __future__ import annotations

from typing import Any

import pytest

from holon_coherence.host_local import (
    GATEWAY_HOSTNAME,
    HOST_LOCAL_ENV_VAR,
    LocalTarget,
    _parse_url,
    decide_rewrite,
    decode_targets,
    detect_host_addresses,
    encode_targets,
    expand_equivalence_class,
    is_loopback_host,
    normalize_host,
    parse_local_target,
    parse_no_proxy,
    plan_no_proxy_pruning,
    rewrite_connection,
    targets_from_env,
)

GATEWAY = "192.168.65.254"
HOST_IPS = ("192.168.2.13", "10.0.0.7")
DEFAULT_NO_PROXY = "localhost,127.0.0.1,::1,169.254.169.254,api.github.com,github.com"


class TestParseLocalTarget:
    """The flag must accept every spelling a user can paste out of a model server's docs."""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("localhost:8081", LocalTarget("localhost", 8081)),
            ("127.0.0.1:8081", LocalTarget("127.0.0.1", 8081)),
            ("192.168.2.13:8081", LocalTarget("192.168.2.13", 8081)),
            ("[::1]:8081", LocalTarget("::1", 8081)),
            ("LOCALHOST:8081", LocalTarget("localhost", 8081)),
            ("  localhost:8081  ", LocalTarget("localhost", 8081)),
            ("localhost", LocalTarget("localhost", None)),
            ("ollama.local", LocalTarget("ollama.local", None)),
            ("fe80::1", LocalTarget("fe80::1", None)),
        ],
    )
    def test_authority_forms(self, raw: str, expected: LocalTarget) -> None:
        assert parse_local_target(raw) == expected

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("http://localhost:8081/v1", LocalTarget("localhost", 8081)),
            ("http://localhost:8081", LocalTarget("localhost", 8081)),
            ("http://localhost:8081/v1/chat/completions", LocalTarget("localhost", 8081)),
            ("http://localhost:8081/v1?key=abc", LocalTarget("localhost", 8081)),
            ("http://127.0.0.1:11434/v1/", LocalTarget("127.0.0.1", 11434)),
            ("https://lmstudio.local:1234/v1", LocalTarget("lmstudio.local", 1234)),
            ("http://localhost/v1", LocalTarget("localhost", 80)),
            ("https://localhost/v1", LocalTarget("localhost", 443)),
            ("http://localhost", LocalTarget("localhost", 80)),
            ("https://localhost", LocalTarget("localhost", 443)),
        ],
    )
    def test_base_url_forms(self, raw: str, expected: LocalTarget) -> None:
        assert parse_local_target(raw) == expected

    @pytest.mark.parametrize(
        "raw",
        [
            None,
            "",
            "   ",
            "localhost:abc",
            "localhost:",
            "127.0.0.1:",
            "[::1]:",
            "localhost:0",
            "localhost:99999",
            "://x",
            "0.0.0.0:8081",
            "::",
            "[::]:80",
            ":::11434",
        ],
    )
    def test_invalid_forms(self, raw: str | None) -> None:
        """Bind addresses and malformed values must be rejected, not silently accepted."""
        assert parse_local_target(raw) is None

    def test_normalize_host_strips_brackets_zone_and_dot(self) -> None:
        assert normalize_host("[fe80::1%en0]") == "fe80::1"
        assert normalize_host("Localhost.") == "localhost"

    def test_is_loopback_host_covers_ranges_and_names(self) -> None:
        assert is_loopback_host("localhost")
        assert is_loopback_host("model.localhost")
        assert is_loopback_host("api.localhost")
        assert is_loopback_host("sub.domain.localhost")
        assert is_loopback_host("127.0.0.1")
        assert is_loopback_host("127.0.0.53")
        assert is_loopback_host("::1")
        assert not is_loopback_host("192.168.2.13")
        assert not is_loopback_host("169.254.169.254")
        assert not is_loopback_host("api.anthropic.com")
        assert not is_loopback_host("notlocalhost")
        assert not is_loopback_host("localhost.example.com")

    def test_parse_url_alias(self) -> None:
        assert _parse_url("http://localhost/v1") == LocalTarget("localhost", 80)
        assert _parse_url("https://localhost/v1") == LocalTarget("localhost", 443)


class TestEquivalenceClass:
    """localhost / 127.0.0.1 / ::1 / the host's own LAN IP are one endpoint from the host's view."""

    def test_loopback_declaration_expands_to_every_host_literal(self) -> None:
        targets = expand_equivalence_class(LocalTarget("localhost", 8081), HOST_IPS)
        hosts = {target.host for target in targets}
        assert hosts == {"localhost", "127.0.0.1", "::1", *HOST_IPS}
        assert {target.port for target in targets} == {8081}

    def test_host_ip_declaration_does_not_grab_loopback(self) -> None:
        targets = expand_equivalence_class(LocalTarget("192.168.2.13", 8081), HOST_IPS)
        hosts = {target.host for target in targets}
        assert "192.168.2.13" in hosts
        assert "localhost" not in hosts
        assert "127.0.0.1" not in hosts

    def test_remote_peer_is_left_alone(self) -> None:
        assert expand_equivalence_class(LocalTarget("10.20.30.40", 8000), HOST_IPS) == (
            LocalTarget("10.20.30.40", 8000),
        )

    def test_gateway_name_never_needs_rewriting(self) -> None:
        targets = expand_equivalence_class(LocalTarget("localhost", 11434), (GATEWAY_HOSTNAME,))
        assert GATEWAY_HOSTNAME not in {target.host for target in targets}

    def test_gateway_name_preserved_when_explicitly_declared(self) -> None:
        targets = expand_equivalence_class(LocalTarget(GATEWAY_HOSTNAME, 8081))
        assert targets == (LocalTarget(GATEWAY_HOSTNAME, 8081),)

    def test_encode_decode_round_trip(self) -> None:
        targets = expand_equivalence_class(LocalTarget("localhost", 8081), HOST_IPS)
        encoded = encode_targets(targets)
        assert decode_targets(encoded) == targets
        assert "8081" in encoded

    def test_decode_drops_junk_and_dedupes(self) -> None:
        assert decode_targets("localhost:8081, localhost:8081, ::,  bad:port ") == (LocalTarget("localhost", 8081),)
        assert decode_targets(None) == ()
        assert decode_targets("") == ()

    def test_targets_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(HOST_LOCAL_ENV_VAR, "localhost:11434,127.0.0.1:11434")
        assert targets_from_env() == (LocalTarget("localhost", 11434), LocalTarget("127.0.0.1", 11434))
        assert targets_from_env({}) == ()


class TestRewriteDecision:
    """The container-side decision table (Bean 0027)."""

    TARGETS = decode_targets("localhost:8081,127.0.0.1:8081,[::1]:8081,192.168.2.13:8081")

    def test_loopback_is_rewritten_even_on_undeclared_ports(self) -> None:
        # Inside the container, loopback is never where the agent's model server lives, so
        # any loopback authority that arrives must go to the host.
        for host in ("localhost", "127.0.0.1", "::1"):
            decision = decide_rewrite(host, 8081, self.TARGETS, GATEWAY)
            assert decision.should_rewrite
            assert decision.address == (GATEWAY, 8081)
            assert decision.reason == "loopback"
        assert decide_rewrite("127.0.0.1", 3000, self.TARGETS, GATEWAY).should_rewrite

    def test_port_is_preserved(self) -> None:
        assert decide_rewrite("localhost", 11434, self.TARGETS, GATEWAY).address == (GATEWAY, 11434)

    def test_allow_listed_host_ip_is_rewritten(self) -> None:
        decision = decide_rewrite("192.168.2.13", 8081, self.TARGETS, GATEWAY)
        assert decision.should_rewrite
        assert decision.reason == "allow-listed"

    def test_allow_listed_host_on_other_port_is_not_rewritten(self) -> None:
        assert decide_rewrite("192.168.2.13", 9999, self.TARGETS, GATEWAY).address is None

    def test_genuine_lan_peer_is_never_rewritten(self) -> None:
        """Safety invariant: an undeclared LAN host may be a real remote inference box."""
        decision = decide_rewrite("192.168.2.99", 8081, self.TARGETS, GATEWAY)
        assert decision.address is None
        assert decision.reason == "not-allow-listed"

    def test_public_host_is_never_rewritten(self) -> None:
        for host in ("api.anthropic.com", "api.openai.com", "generativelanguage.googleapis.com"):
            assert decide_rewrite(host, 443, self.TARGETS, GATEWAY).address is None

    def test_link_local_metadata_is_not_rewritten(self) -> None:
        assert decide_rewrite("169.254.169.254", 80, self.TARGETS, GATEWAY).address is None

    def test_without_declaration_the_addon_is_inert(self) -> None:
        decision = decide_rewrite("localhost", 8081, (), GATEWAY)
        assert decision.address is None
        assert decision.reason == "not-configured"

    def test_gateway_already_correct(self) -> None:
        assert decide_rewrite(GATEWAY_HOSTNAME, 8081, self.TARGETS, GATEWAY).reason == "already-gateway"

    def test_proxy_own_port_never_loops(self) -> None:
        """Rewriting the proxy's own published port would dial back into itself."""
        decision = decide_rewrite("localhost", 8080, self.TARGETS, GATEWAY, proxy_ports=(8080,))
        assert decision.address is None
        assert decision.reason == "proxy-own-port"

    def test_gateway_unresolved_reports_actionable_reason(self) -> None:
        decision = decide_rewrite("localhost", 8081, self.TARGETS, None)
        assert decision.address is None
        assert decision.reason == "gateway-unresolved"

    def test_missing_authority(self) -> None:
        assert decide_rewrite(None, 8081, self.TARGETS, GATEWAY).reason == "no-authority"
        assert decide_rewrite("localhost", None, self.TARGETS, GATEWAY).reason == "no-authority"

    def test_portless_target_matches_any_port(self) -> None:
        targets = decode_targets("192.168.2.13")
        assert decide_rewrite("192.168.2.13", 1234, targets, GATEWAY).should_rewrite

    def test_loopback_not_rewritten_when_only_lan_targets_configured(self) -> None:
        targets = decode_targets("192.168.2.13:8081")
        decision = decide_rewrite("localhost", 8081, targets, GATEWAY)
        assert decision.address is None
        assert decision.reason == "not-allow-listed"


class _FakeServer:
    def __init__(self, address: tuple[str, int] | None) -> None:
        self.address = address


class _FakeHookData:
    def __init__(self, address: tuple[str, int] | None) -> None:
        self.server = _FakeServer(address)


class TestRewriteConnection:
    """rewrite_connection mutates the mitmproxy server address in place."""

    TARGETS = decode_targets("localhost:8081,127.0.0.1:8081,192.168.2.13:8081")

    def test_mutates_address(self) -> None:
        data: Any = _FakeHookData(("localhost", 8081))
        decision = rewrite_connection(data, self.TARGETS, GATEWAY)
        assert decision.should_rewrite
        assert data.server.address == (GATEWAY, 8081)

    def test_leaves_untouched_when_not_applicable(self) -> None:
        data: Any = _FakeHookData(("api.openai.com", 443))
        assert not rewrite_connection(data, self.TARGETS, GATEWAY).should_rewrite
        assert data.server.address == ("api.openai.com", 443)

    def test_survives_missing_server(self) -> None:
        class _NoServer:
            pass

        assert rewrite_connection(_NoServer(), self.TARGETS, GATEWAY).reason == "no-authority"


class TestNoProxyPruning:
    """A loopback entry in NO_PROXY means the agent never asks the proxy at all."""

    def test_loopback_declaration_removes_the_whole_loopback_class(self) -> None:
        plan = plan_no_proxy_pruning(DEFAULT_NO_PROXY, LocalTarget("localhost", 8081))
        assert set(plan.remove) == {"localhost", "127.0.0.1", "::1"}
        assert set(plan.keep) == {"169.254.169.254", "api.github.com", "github.com"}
        assert plan.intercepted

    def test_host_ip_declaration_leaves_loopback_bypass_intact(self) -> None:
        """Declaring the LAN address must not silently route other localhost traffic."""
        plan = plan_no_proxy_pruning(DEFAULT_NO_PROXY, LocalTarget("192.168.2.13", 8081), HOST_IPS)
        assert plan.remove == ()
        assert "localhost" in plan.keep

    def test_port_scoped_entry_removes_only_that_port(self) -> None:
        value = "localhost:8081,localhost:3000,github.com"
        plan = plan_no_proxy_pruning(value, LocalTarget("localhost", 8081))
        assert plan.remove == ("localhost:8081",)
        assert "localhost:3000" in plan.keep

    def test_wildcard_is_reported_not_removed(self) -> None:
        plan = plan_no_proxy_pruning("*,github.com", LocalTarget("localhost", 8081))
        assert plan.blocked_by_wildcard
        assert "*" in plan.keep
        assert not plan.intercepted

    def test_suffix_entry_is_matched(self) -> None:
        plan = plan_no_proxy_pruning(".localhost,github.com", LocalTarget("localhost", 8081))
        assert plan.remove == (".localhost",)

    def test_wildcard_subdomain_entry_is_matched(self) -> None:
        plan = plan_no_proxy_pruning("*.localhost,github.com", LocalTarget("localhost", 8081))
        assert plan.remove == ("*.localhost",)

    def test_no_target_in_value_is_a_no_op(self) -> None:
        plan = plan_no_proxy_pruning("api.github.com,github.com", LocalTarget("localhost", 8081))
        assert plan.remove == ()
        assert not plan.intercepted

    def test_empty_value(self) -> None:
        assert plan_no_proxy_pruning(None, LocalTarget("localhost", 8081)).keep == ()

    def test_parse_no_proxy_dedupes_and_strips(self) -> None:
        assert parse_no_proxy(" localhost , 127.0.0.1 ,, localhost ") == ("localhost", "127.0.0.1")
        assert parse_no_proxy(None) == ()


class _FakeServerConn:
    def __init__(self, address: tuple[str, int] | None) -> None:
        self.address = address
        self.error: str | None = None


class _FakeConnectData:
    def __init__(self, address: tuple[str, int] | None) -> None:
        self.server = _FakeServerConn(address)
        self.hook = None


class TestMitmproxyServerConnectHook:
    """The mitmproxy hook is what actually redirects the dial onto the host gateway."""

    ALLOW_LIST = "127.0.0.1:8081,192.168.2.13:8081,localhost:8081"

    def _addon(self) -> Any:
        from holon_coherence.mitm_addon import MitmproxyAddon

        return MitmproxyAddon(cache_dir="/tmp/holon-test-cache")

    def test_host_mode_is_left_untouched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """On the host, localhost genuinely is the target -- rewriting there would be wrong."""
        monkeypatch.setenv(HOST_LOCAL_ENV_VAR, self.ALLOW_LIST)
        monkeypatch.setattr("holon_coherence.mitm_addon.in_container", lambda: False)
        data: Any = _FakeConnectData(("localhost", 8081))
        self._addon().server_connect(data)
        assert data.server.address == ("localhost", 8081)

    def test_without_allow_list_the_hook_is_inert(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(HOST_LOCAL_ENV_VAR, raising=False)
        monkeypatch.setattr("holon_coherence.mitm_addon.in_container", lambda: True)
        data: Any = _FakeConnectData(("localhost", 8081))
        self._addon().server_connect(data)
        assert data.server.address == ("localhost", 8081)

    def test_container_rewrites_and_logs_original_authority(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(HOST_LOCAL_ENV_VAR, self.ALLOW_LIST)
        monkeypatch.setattr("holon_coherence.mitm_addon.in_container", lambda: True)
        monkeypatch.setattr("holon_coherence.mitm_addon.resolve_gateway_address", lambda: GATEWAY)
        logged: list[str] = []
        monkeypatch.setattr("holon_coherence.mitm_addon.log_telemetry", logged.append)

        data: Any = _FakeConnectData(("localhost", 8081))
        self._addon().server_connect(data)

        assert data.server.address == (GATEWAY, 8081)
        assert logged and "localhost:8081" in logged[0] and GATEWAY in logged[0]

    def test_only_the_listen_port_counts_as_self(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """8081 is a common model-server port; assuming the proxy owns it would block it."""
        monkeypatch.setenv(HOST_LOCAL_ENV_VAR, self.ALLOW_LIST)
        monkeypatch.setattr("holon_coherence.mitm_addon.in_container", lambda: True)
        monkeypatch.setattr("holon_coherence.mitm_addon.resolve_gateway_address", lambda: GATEWAY)
        addon = self._addon()
        assert addon._proxy_own_ports() == (8080,)
        data: Any = _FakeConnectData(("localhost", 8081))
        addon.server_connect(data)
        assert data.server.address == (GATEWAY, 8081)

    def test_public_hosts_are_never_rewritten(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(HOST_LOCAL_ENV_VAR, self.ALLOW_LIST)
        monkeypatch.setattr("holon_coherence.mitm_addon.in_container", lambda: True)
        monkeypatch.setattr("holon_coherence.mitm_addon.resolve_gateway_address", lambda: GATEWAY)
        for host, port in (("api.anthropic.com", 443), ("192.168.2.99", 8081), ("169.254.169.254", 80)):
            data: Any = _FakeConnectData((host, port))
            self._addon().server_connect(data)
            assert data.server.address == (host, port)

    def test_gateway_failure_warns_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(HOST_LOCAL_ENV_VAR, self.ALLOW_LIST)
        monkeypatch.setattr("holon_coherence.mitm_addon.in_container", lambda: True)
        monkeypatch.setattr("holon_coherence.mitm_addon.resolve_gateway_address", lambda: None)
        logged: list[str] = []
        monkeypatch.setattr("holon_coherence.mitm_addon.log_telemetry", logged.append)

        addon = self._addon()
        for _ in range(3):
            data: Any = _FakeConnectData(("localhost", 8081))
            addon.server_connect(data)
            assert data.server.address == ("localhost", 8081)

        warnings = [entry for entry in logged if "WARNING" in entry]
        assert len(warnings) == 1
        assert "host-gateway" in warnings[0]

    def test_gateway_resolution_retries_on_failure_and_caches_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(HOST_LOCAL_ENV_VAR, self.ALLOW_LIST)
        monkeypatch.setattr("holon_coherence.mitm_addon.in_container", lambda: True)
        calls: list[str | None] = [None, None, GATEWAY]

        def _mock_resolve() -> str | None:
            if calls:
                return calls.pop(0)
            return GATEWAY

        monkeypatch.setattr("holon_coherence.mitm_addon.resolve_gateway_address", _mock_resolve)
        addon = self._addon()
        assert addon._resolve_gateway() is None
        assert addon._resolve_gateway() is None
        assert addon._resolve_gateway() == GATEWAY
        # Subsequent call uses cache
        assert addon._resolve_gateway() == GATEWAY
        assert len(calls) == 0

    def test_proxy_own_port_connection_blocked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(HOST_LOCAL_ENV_VAR, self.ALLOW_LIST)
        monkeypatch.setattr("holon_coherence.mitm_addon.in_container", lambda: True)
        monkeypatch.setattr("holon_coherence.mitm_addon.resolve_gateway_address", lambda: GATEWAY)
        addon = self._addon()
        data: Any = _FakeConnectData(("localhost", 8080))
        addon.server_connect(data)
        assert data.server.address == ("localhost", 8080)
        assert data.server.error == "Connection to proxy's own port blocked"

    def test_proxy_own_port_from_env_avoids_loop(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HOLON_PROXY_PORT", "9090")
        addon = self._addon()
        ports = addon._proxy_own_ports()
        assert 9090 in ports

    def test_proxy_own_port_in_container_does_not_treat_listen_port_as_published(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """In container mode, only HOLON_PROXY_PORT counts as a host self-loop hazard."""
        monkeypatch.setattr("holon_coherence.mitm_addon.in_container", lambda: True)
        monkeypatch.setenv("HOLON_PROXY_PORT", "9090")
        addon = self._addon()
        assert addon._proxy_own_ports() == (9090,)

    def test_proxy_own_port_in_container_defaults_to_8080(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("holon_coherence.mitm_addon.in_container", lambda: True)
        monkeypatch.delenv("HOLON_PROXY_PORT", raising=False)
        addon = self._addon()
        assert addon._proxy_own_ports() == (8080,)


class TestDetectHostAddresses:
    """Tests for host-side address discovery and exclusion of bridge/tunnel subnets."""

    def test_udp_probe_address_prioritized(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _FakeSocket:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            def connect(self, endpoint: Any) -> None:
                pass

            def getsockname(self) -> tuple[str, int]:
                return ("192.168.1.50", 54321)

            def __enter__(self) -> _FakeSocket:
                return self

            def __exit__(self, *args: Any) -> None:
                pass

        monkeypatch.setattr("socket.socket", _FakeSocket)

        def _mock_getaddrinfo(*args: Any, **kwargs: Any) -> list[Any]:
            pytest.fail("getaddrinfo should not be called when UDP probe succeeds")

        monkeypatch.setattr("socket.getaddrinfo", _mock_getaddrinfo)
        assert detect_host_addresses() == ("192.168.1.50",)

    def test_docker_bridge_and_cgnat_filtered_out(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _FailingSocket:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            def connect(self, endpoint: Any) -> None:
                raise OSError("unreachable")

            def __enter__(self) -> _FailingSocket:
                return self

            def __exit__(self, *args: Any) -> None:
                pass

        monkeypatch.setattr("socket.socket", _FailingSocket)
        fake_addrinfo = [
            (2, 1, 6, "", ("127.0.0.1", 0)),
            (2, 1, 6, "", ("172.17.0.1", 0)),  # docker0 bridge
            (2, 1, 6, "", ("100.64.1.2", 0)),  # Tailscale / RFC 6598
            (2, 1, 6, "", ("192.168.1.100", 0)),  # Valid LAN
        ]
        monkeypatch.setattr("socket.getaddrinfo", lambda *args, **kwargs: fake_addrinfo)
        assert detect_host_addresses() == ("192.168.1.100",)
