"""Shared fixtures for command module tests."""

from __future__ import annotations

import os
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _never_persist_real_web_token() -> Iterator[MagicMock]:
    """A ``start --web`` resolves an inspector token; keep it out of the real ~/.holon/web-token.

    ``HOLON_COHERENCE_WEB`` is cleared so a developer's shell opt-in cannot flip the headless default under test.
    """
    with (
        patch.dict(os.environ, {}, clear=False),
        patch("holon_coherence.commands.start.save_web_token") as mock_save,
    ):
        os.environ.pop("HOLON_COHERENCE_WEB", None)
        yield mock_save
