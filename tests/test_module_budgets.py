from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from scripts.check_module_budgets import DEFAULT_CONFIG_REL_PATH, main

REPO_ROOT = Path(__file__).resolve().parent.parent


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _lines(count: int) -> str:
    return "".join(f"x_{i} = {i}\n" for i in range(count))


def _write_config(repo: Path, config: dict[str, Any]) -> None:
    cfg_path = repo / DEFAULT_CONFIG_REL_PATH
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def _write_files(repo: Path, files: dict[str, str]) -> None:
    for rel_path, content in files.items():
        path = repo / rel_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _init_git_repo(tmp_path: Path, config: dict[str, Any] | None, files: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    if config is not None:
        _write_config(repo, config)
    _write_files(repo, files)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    return repo


def test_new_package_over_200_lines_fails_automatically(tmp_path: Path, capsys: Any) -> None:
    config = {"default_max_lines": 200, "exclude": [], "overrides": {}}
    repo = _init_git_repo(tmp_path, config, {"src/brand_new_pkg/module.py": _lines(200)})
    assert main(["--repo-root", str(repo)]) == 0

    (repo / "src/brand_new_pkg/module.py").write_text(_lines(201), encoding="utf-8")
    assert main(["--repo-root", str(repo)]) == 1
    captured = capsys.readouterr()
    assert "src/brand_new_pkg/module.py" in captured.err
    assert "201 > 200" in captured.err


def test_new_script_over_200_lines_fails_automatically(tmp_path: Path, capsys: Any) -> None:
    config = {"default_max_lines": 200, "exclude": [], "overrides": {}}
    repo = _init_git_repo(tmp_path, config, {"scripts/new_tool.py": _lines(201)})
    assert main(["--repo-root", str(repo)]) == 1
    captured = capsys.readouterr()
    assert "scripts/new_tool.py" in captured.err
    assert "201 > 200" in captured.err


def test_frozen_override_exact_passes_and_growth_by_one_fails(tmp_path: Path, capsys: Any) -> None:
    config = {"default_max_lines": 200, "exclude": [], "overrides": {"src/legacy_pkg/big.py": 250}}
    repo = _init_git_repo(tmp_path, config, {"src/legacy_pkg/big.py": _lines(250)})
    assert main(["--repo-root", str(repo)]) == 0

    (repo / "src/legacy_pkg/big.py").write_text(_lines(251), encoding="utf-8")
    assert main(["--repo-root", str(repo)]) == 1
    captured = capsys.readouterr()
    assert "src/legacy_pkg/big.py" in captured.err
    assert "251 > 250" in captured.err
    assert "frozen override exceeded" in captured.err


def test_frozen_override_shrink_emits_ratchet_notice(tmp_path: Path, capsys: Any) -> None:
    config = {"default_max_lines": 200, "exclude": [], "overrides": {"src/legacy_pkg/big.py": 250}}
    repo = _init_git_repo(tmp_path, config, {"src/legacy_pkg/big.py": _lines(240)})
    assert main(["--repo-root", str(repo)]) == 0
    out_240 = capsys.readouterr().out
    assert "Ratchet notice" in out_240
    assert "src/legacy_pkg/big.py" in out_240
    assert "240" in out_240

    (repo / "src/legacy_pkg/big.py").write_text(_lines(190), encoding="utf-8")
    assert main(["--repo-root", str(repo)]) == 0
    out_190 = capsys.readouterr().out
    assert "Ratchet notice" in out_190
    assert "190" in out_190
    assert "remove override" in out_190


def test_exclusion_with_reason_skips_oversized_file(tmp_path: Path) -> None:
    config = {
        "default_max_lines": 200,
        "exclude": [{"pattern": "src/generated/*.py", "reason": "Auto-generated protobuf bindings"}],
        "overrides": {},
    }
    repo = _init_git_repo(
        tmp_path,
        config,
        {
            "src/generated/proto_pb2.py": _lines(300),
            "tests/test_big.py": _lines(300),
            "src/app/clean.py": _lines(50),
        },
    )
    assert main(["--repo-root", str(repo)]) == 0


def test_exclusion_missing_reason_fails_validation(tmp_path: Path, capsys: Any) -> None:
    config = {
        "default_max_lines": 200,
        "exclude": [{"pattern": "src/generated/*.py", "reason": "   "}],
        "overrides": {},
    }
    repo = _init_git_repo(tmp_path, config, {"src/app/clean.py": _lines(10)})
    assert main(["--repo-root", str(repo)]) == 1
    assert "reason" in capsys.readouterr().err


def test_frozen_config_verification_against_merge_base(tmp_path: Path, capsys: Any) -> None:
    base_config = {"default_max_lines": 200, "exclude": [], "overrides": {"src/legacy/big.py": 250}}
    repo = _init_git_repo(
        tmp_path,
        base_config,
        {"src/legacy/big.py": _lines(250), "src/legacy/small.py": _lines(100)},
    )
    _git(repo, "checkout", "-b", "feat/budget-test")

    _write_config(repo, {"default_max_lines": 200, "exclude": [], "overrides": {"src/legacy/big.py": 251}})
    assert main(["--repo-root", str(repo), "--verify-base", "--base-ref", "main"]) == 1
    assert "override raised" in capsys.readouterr().err

    _write_config(
        repo,
        {
            "default_max_lines": 200,
            "exclude": [],
            "overrides": {"src/legacy/big.py": 250, "src/legacy/small.py": 210},
        },
    )
    assert main(["--repo-root", str(repo), "--verify-base", "--base-ref", "main"]) == 1
    assert "new override added" in capsys.readouterr().err

    _write_config(repo, {"default_max_lines": 210, "exclude": [], "overrides": {"src/legacy/big.py": 250}})
    assert main(["--repo-root", str(repo), "--verify-base", "--base-ref", "main"]) == 1
    assert "default_max_lines raised" in capsys.readouterr().err

    (repo / "src/legacy/big.py").write_text(_lines(240), encoding="utf-8")
    _write_config(repo, {"default_max_lines": 200, "exclude": [], "overrides": {"src/legacy/big.py": 240}})
    assert main(["--repo-root", str(repo), "--verify-base", "--base-ref", "main"]) == 0

    (repo / "src/legacy/big.py").write_text(_lines(180), encoding="utf-8")
    _write_config(repo, {"default_max_lines": 200, "exclude": [], "overrides": {}})
    assert main(["--repo-root", str(repo), "--verify-base", "--base-ref", "main"]) == 0


def test_frozen_config_bootstrap_when_absent_on_base(tmp_path: Path) -> None:
    repo = _init_git_repo(tmp_path, None, {"src/app/mod.py": _lines(220)})
    _git(repo, "checkout", "-b", "feat/bootstrap")
    _write_config(repo, {"default_max_lines": 200, "exclude": [], "overrides": {"src/app/mod.py": 220}})
    assert main(["--repo-root", str(repo), "--verify-base", "--base-ref", "main"]) == 0


def test_live_repository_passes_module_budgets(capsys: Any) -> None:
    assert main(["--repo-root", str(REPO_ROOT)]) == 0
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""
