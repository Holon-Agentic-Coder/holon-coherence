"""Dedicated stop command implementation and container teardown dispatch."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from typing import Any

from holon_coherence.proxy.lifecycle import ProxyLifecycle, get_container_name


def stop_proxy_container(container_name: str | None = None) -> None:
    """Stop and remove the holon-coherence background Docker container on demand."""
    lifecycle = ProxyLifecycle()
    lifecycle.stop(container_name)


def handle_stop(
    args: Any = None,
    *,
    stopper_fn: Callable[[str | None], None] | None = None,
) -> int:
    """Stop and remove running holon-coherence Docker container."""
    stopper = stopper_fn or stop_proxy_container
    target_container = getattr(args, "name", None) or get_container_name()
    stopper(target_container)
    return 0


def handle(args: Any) -> int:
    """Handle stop command."""
    return handle_stop(args)


def register(subparsers: Any) -> argparse.ArgumentParser:
    """Register stop subparser."""
    stop_parser = subparsers.add_parser("stop", help="Stop and remove running holon-coherence Docker container")
    stop_parser.add_argument(
        "--name",
        default=None,
        help="Container name (defaults to HOLON_CONTAINER_NAME or holon-coherence-proxy)",
    )
    stop_parser.set_defaults(handler=handle)
    return stop_parser
