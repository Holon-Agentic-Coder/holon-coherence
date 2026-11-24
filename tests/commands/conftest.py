from __future__ import annotations

import os
from collections.abc import Iterator
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _never_persist_real_web_token() -> Iterator[MagicMock]:
    with (
        patch.dict(os.environ, {}, clear=False),
        patch("holon_coherence.commands.start.save_web_token") as mock_save,
    ):
        os.environ.pop("HOLON_COHERENCE_WEB", None)
        yield mock_save
