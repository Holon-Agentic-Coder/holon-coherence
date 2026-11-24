from __future__ import annotations

import pathlib
from unittest.mock import patch

from scripts.pre_commit_check import (
    BUDGET_CONFIG_REL_PATH,
    REPO_ROOT,
    _run_module_budget_check,
    _should_check_module_budgets,
    _to_repo_relative,
    check_content,
    get_staged_files,
    is_disallowed_path,
    main,
    mask_secret,
    scan_file,
)


def test_is_disallowed_path():
    disallowed_scratch_paths = (
        "tmp/scratch.txt",
        "subdir/tmp/scratch.txt",
        "debug.log",
        "logs/server.log",
        "data.tmp",
        "sub/test.tmp",
        ".index/store.db",
        "nested/.index/rag_cache",
    )
    for path in disallowed_scratch_paths:
        assert is_disallowed_path(path)

    allowed_canonical_paths = (
        "src/holon_coherence/cli.py",
        "README.md",
        "tests/test_cli.py",
        "Makefile",
        "docs/audit_report.md",
    )
    for path in allowed_canonical_paths:
        assert not is_disallowed_path(path)


def test_mask_secret():
    sec = "AIza" + "1234567890abcdef"
    assert mask_secret(sec) == "AIza...cdef"
    assert mask_secret("short") == "****"


def test_check_content_detects_secrets():
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
    files = get_staged_files()
    assert isinstance(files, list)


def test_to_repo_relative(tmp_path: pathlib.Path):
    assert _to_repo_relative("./src/holon_coherence/cli.py") == "src/holon_coherence/cli.py"
    assert _to_repo_relative(REPO_ROOT / "scripts/pre_commit_check.py") == "scripts/pre_commit_check.py"
    assert _to_repo_relative(tmp_path / "outside.py") is None


def test_should_check_module_budgets(tmp_path: pathlib.Path):
    assert _should_check_module_budgets(["README.md"], check_all=True)
    assert _should_check_module_budgets(["src/holon_coherence/cli.py"], check_all=False)
    assert _should_check_module_budgets(["scripts/check_module_budgets.py"], check_all=False)
    assert _should_check_module_budgets([str(REPO_ROOT / "scripts/pre_commit_check.py")], check_all=False)
    assert _should_check_module_budgets([BUDGET_CONFIG_REL_PATH], check_all=False)
    assert not _should_check_module_budgets(["README.md", "tests/test_pre_commit_check.py"], check_all=False)
    assert not _should_check_module_budgets([str(tmp_path / "outside.py")], check_all=False)


def test_run_module_budget_check_prints_notices_and_returns_errors(capsys):
    with patch(
        "scripts.check_module_budgets.check_repo_budgets",
        return_value=(["src/app/mod.py: 205 > 200 lines"], ["Ratchet notice: src/app/old.py"]),
    ) as mock_check:
        errors = _run_module_budget_check()
    mock_check.assert_called_once_with(REPO_ROOT)
    assert errors == ["src/app/mod.py: 205 > 200 lines"]
    assert "Ratchet notice: src/app/old.py" in capsys.readouterr().out


def test_main_propagates_module_budget_failures_and_skips_unrelated(tmp_path: pathlib.Path, capsys):
    unrelated = tmp_path / "clean.py"
    unrelated.write_text('print("ok")\n', encoding="utf-8")
    with patch("scripts.pre_commit_check._run_module_budget_check", return_value=["budget failure"]) as mock_budget:
        assert main([str(unrelated)]) == 0
        mock_budget.assert_not_called()

    with (
        patch("scripts.pre_commit_check.scan_file", return_value=[]),
        patch(
            "scripts.pre_commit_check._run_module_budget_check",
            return_value=["src/app/mod.py: 205 > 200 lines"],
        ) as mock_budget,
    ):
        assert main(["src/app/mod.py"]) == 1
        mock_budget.assert_called_once_with()
    assert "src/app/mod.py: 205 > 200 lines" in capsys.readouterr().out

    with (
        patch("scripts.pre_commit_check.scan_file", return_value=[]),
        patch("scripts.pre_commit_check._run_module_budget_check", return_value=[]) as mock_budget,
    ):
        assert main([BUDGET_CONFIG_REL_PATH]) == 0
        mock_budget.assert_called_once_with()
