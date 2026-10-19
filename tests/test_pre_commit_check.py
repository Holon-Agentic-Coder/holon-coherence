"""Unit tests for scripts/pre_commit_check.py."""

from __future__ import annotations

import pathlib
from unittest.mock import patch

from scripts.pre_commit_check import (
    check_content,
    get_staged_files,
    is_disallowed_path,
    main,
    mask_secret,
    scan_file,
)


def test_is_disallowed_path():
    # Scratch and temporary paths that must be blocked
    assert is_disallowed_path("tmp/scratch.txt")
    assert is_disallowed_path("subdir/tmp/scratch.txt")
    assert is_disallowed_path("debug.log")
    assert is_disallowed_path("logs/server.log")
    assert is_disallowed_path("data.tmp")
    assert is_disallowed_path("sub/test.tmp")
    assert is_disallowed_path(".index/store.db")
    assert is_disallowed_path("nested/.index/rag_cache")

    # Allowed canonical paths
    assert not is_disallowed_path("src/holon_coherence/cli.py")
    assert not is_disallowed_path("README.md")
    assert not is_disallowed_path("tests/test_cli.py")
    assert not is_disallowed_path("Makefile")
    assert not is_disallowed_path("docs/audit_report.md")


def test_mask_secret():
    # Construct strings dynamically to avoid scanner detection
    sec = "AIza" + "1234567890abcdef"
    assert mask_secret(sec) == "AIza...cdef"
    assert mask_secret("short") == "****"


def test_check_content_detects_secrets():
    # Dynamically assemble secret strings
    google_key = "AIza" + "SyD1234567890abcdefghijklmnopqrstuvw"
    github_classic = "ghp_" + "1234567890abcdefghijklmnopqrstuvwxyz1234"
    github_pat = "github_pat_" + "1234567890abcdefghijklmnopqrstuvwxyz1234"
    openai_key = "sk-" + "1234567890abcdefghijklmnopqrstuvwxyz"
    anthropic_key = "sk-ant-" + "1234567890abcdefghijklmnopqrstuvwxyz"

    content = f"""
    GOOGLE_KEY = "{google_key}"
    GITHUB_PAT = "{github_classic}"
    FINE_PAT = "{github_pat}"
    OPENAI = "{openai_key}"
    ANTHROPIC = "{anthropic_key}"
    """

    findings = check_content(content, filename="test_file.py")
    assert len(findings) == 5

    patterns = {f["pattern"] for f in findings}
    assert "Google AI API Key" in patterns
    assert "GitHub PAT (classic)" in patterns
    assert "GitHub PAT (fine-grained)" in patterns
    assert "OpenAI API Key" in patterns
    assert "Anthropic API Key" in patterns


def test_check_content_allows_exemptions():
    google_key = "AIza" + "SyD1234567890abcdefghijklmnopqrstuvw"
    content = f'GOOGLE_KEY = "{google_key}"  # holon:allow-secret\n'
    findings = check_content(content, filename="exempt.py")
    assert findings == []


def test_scan_file_detects_disallowed_path(tmp_path: pathlib.Path):
    disallowed_file = tmp_path / "scratch.tmp"
    disallowed_file.write_text("Clean content\n", encoding="utf-8")
    errors = scan_file(disallowed_file)
    assert len(errors) == 1
    assert "Disallowed ephemeral scratch path" in errors[0]


def test_scan_file_detects_secret(tmp_path: pathlib.Path):
    openai_key = "sk-" + "1234567890abcdefghijklmnopqrstuvwxyz"
    secret_file = tmp_path / "config.py"
    secret_file.write_text(f'API_KEY = "{openai_key}"\n', encoding="utf-8")
    errors = scan_file(secret_file)
    assert len(errors) == 1
    assert "Potential secret credential detected" in errors[0]


def test_scan_file_clean(tmp_path: pathlib.Path):
    clean_file = tmp_path / "valid.py"
    clean_file.write_text('print("Hello world")\n', encoding="utf-8")
    errors = scan_file(clean_file)
    assert errors == []


def test_main_with_arguments(tmp_path: pathlib.Path):
    clean_file = tmp_path / "clean.py"
    clean_file.write_text('print("All good")\n', encoding="utf-8")

    openai_key = "sk-" + "1234567890abcdefghijklmnopqrstuvwxyz"
    bad_file = tmp_path / "bad.py"
    bad_file.write_text(f'KEY = "{openai_key}"\n', encoding="utf-8")

    assert main([str(clean_file)]) == 0
    assert main([str(bad_file)]) == 1
    assert main([str(clean_file), str(bad_file)]) == 1


def test_main_empty_staged_files():
    with patch("scripts.pre_commit_check.get_staged_files", return_value=[]):
        assert main([]) == 0


def test_get_staged_files():
    # Should safely return a list without raising exceptions
    files = get_staged_files()
    assert isinstance(files, list)
