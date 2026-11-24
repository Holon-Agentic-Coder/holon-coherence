from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from scripts.check_module_budgets import DEFAULT_CONFIG_REL, REPO_ROOT, load_config, main

DEFAULT_CONFIG: dict[str, Any] = {
    "default_max_lines": 200,
    "exclude": [{"path": "tests/", "reason": "Test suites are excluded."}],
    "overrides": {},
}


def _lines(count: int) -> str:
    return "\n".join(f"x_{i} = {i}" for i in range(count)) + "\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    )


def _write_files(repo: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")


def _init_repo(tmp_path: Path, files: dict[str, str], config: dict[str, Any] | None = None) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    cfg = DEFAULT_CONFIG if config is None else config
    all_files = {DEFAULT_CONFIG_REL: json.dumps(cfg, indent=2) + "\n", **files}
    _write_files(repo, all_files)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "initial")
    return repo


def test_new_package_discovery_fails_at_201_lines(tmp_path: Path, capsys: Any) -> None:
    repo = _init_repo(tmp_path, {"src/brand_new_pkg/mod.py": _lines(200)})
    assert main(["--repo-root", str(repo), "--no-merge-base"]) == 0

    (repo / "src/brand_new_pkg/mod.py").write_text(_lines(201), encoding="utf-8")
    assert main(["--repo-root", str(repo), "--no-merge-base"]) == 1
    captured = capsys.readouterr()
    assert "src/brand_new_pkg/mod.py" in captured.err
    assert "201" in captured.err


def test_new_script_discovery_fails_at_201_lines(tmp_path: Path, capsys: Any) -> None:
    repo = _init_repo(tmp_path, {"scripts/new_tool.py": _lines(201)})
    assert main(["--repo-root", str(repo), "--no-merge-base"]) == 1
    captured = capsys.readouterr()
    assert "scripts/new_tool.py" in captured.err
    assert "201" in captured.err


def test_frozen_override_growth_fails_by_one_line(tmp_path: Path, capsys: Any) -> None:
    cfg = {**DEFAULT_CONFIG, "overrides": {"src/pkg/legacy.py": 250}}
    repo = _init_repo(tmp_path, {"src/pkg/legacy.py": _lines(250)}, config=cfg)
    assert main(["--repo-root", str(repo), "--no-merge-base"]) == 0

    (repo / "src/pkg/legacy.py").write_text(_lines(251), encoding="utf-8")
    assert main(["--repo-root", str(repo), "--no-merge-base"]) == 1
    captured = capsys.readouterr()
    assert "src/pkg/legacy.py" in captured.err
    assert "251" in captured.err


def test_frozen_override_shrink_emits_ratchet_down_notice(tmp_path: Path, capsys: Any) -> None:
    cfg = {**DEFAULT_CONFIG, "overrides": {"src/pkg/legacy.py": 250}}
    repo = _init_repo(tmp_path, {"src/pkg/legacy.py": _lines(240)}, config=cfg)
    assert main(["--repo-root", str(repo), "--no-merge-base"]) == 0
    captured = capsys.readouterr()
    assert "RATCHET-DOWN" in captured.out
    assert "240" in captured.out

    (repo / "src/pkg/legacy.py").write_text(_lines(180), encoding="utf-8")
    assert main(["--repo-root", str(repo), "--no-merge-base"]) == 0
    captured = capsys.readouterr()
    assert "RATCHET-DOWN" in captured.out
    assert "remove override" in captured.out


def test_exclusion_handling_and_reason_requirement(tmp_path: Path, capsys: Any) -> None:
    cfg = {
        "default_max_lines": 200,
        "exclude": [
            {"path": "tests/", "reason": "Test files are excluded."},
            {"path": "src/generated/", "reason": "Auto-generated code."},
            {"path": "scripts/vendor_*.py", "reason": "Vendored script."},
        ],
        "overrides": {},
    }
    repo = _init_repo(
        tmp_path,
        {
            "tests/test_big.py": _lines(350),
            "src/generated/proto.py": _lines(350),
            "scripts/vendor_helper.py": _lines(350),
            "src/pkg/ok.py": _lines(50),
        },
        config=cfg,
    )
    assert main(["--repo-root", str(repo), "--no-merge-base"]) == 0

    bad_reason_cfg = {**cfg, "exclude": [{"path": "src/generated/", "reason": "   "}]}
    (repo / DEFAULT_CONFIG_REL).write_text(json.dumps(bad_reason_cfg), encoding="utf-8")
    assert main(["--repo-root", str(repo), "--no-merge-base"]) == 1
    assert "reason" in capsys.readouterr().err

    allowlist_cfg = {**cfg, "packages": ["src/pkg"]}
    (repo / DEFAULT_CONFIG_REL).write_text(json.dumps(allowlist_cfg), encoding="utf-8")
    assert main(["--repo-root", str(repo), "--no-merge-base"]) == 1
    assert "packages" in capsys.readouterr().err


def test_frozen_config_merge_base_verification(tmp_path: Path, capsys: Any) -> None:
    base_cfg = {**DEFAULT_CONFIG, "overrides": {"src/pkg/legacy.py": 250}}
    repo = _init_repo(
        tmp_path,
        {"src/pkg/legacy.py": _lines(250), "src/pkg/other.py": _lines(150)},
        config=base_cfg,
    )
    _git(repo, "checkout", "-b", "feat/test")

    def write_cfg(cfg: dict[str, Any]) -> None:
        (repo / DEFAULT_CONFIG_REL).write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")

    write_cfg({**base_cfg, "default_max_lines": 220})
    assert main(["--repo-root", str(repo), "--base-ref", "main", "--require-base"]) == 1
    assert "default_max_lines increased" in capsys.readouterr().err

    write_cfg({**base_cfg, "overrides": {"src/pkg/legacy.py": 250, "src/pkg/other.py": 210}})
    assert main(["--repo-root", str(repo), "--base-ref", "main", "--require-base"]) == 1
    assert "New override not allowed" in capsys.readouterr().err

    write_cfg({**base_cfg, "overrides": {"src/pkg/legacy.py": 260}})
    assert main(["--repo-root", str(repo), "--base-ref", "main", "--require-base"]) == 1
    assert "increased from 250 to 260" in capsys.readouterr().err

    (repo / "src/pkg/legacy.py").write_text(_lines(240), encoding="utf-8")
    write_cfg({**base_cfg, "overrides": {"src/pkg/legacy.py": 240}})
    assert main(["--repo-root", str(repo), "--base-ref", "main", "--require-base"]) == 0

    (repo / "src/pkg/legacy.py").write_text(_lines(190), encoding="utf-8")
    write_cfg({**base_cfg, "overrides": {}})
    assert main(["--repo-root", str(repo), "--base-ref", "main", "--require-base"]) == 0


def test_live_repo_config_passes_and_has_no_package_allowlist() -> None:
    cfg_path = REPO_ROOT / DEFAULT_CONFIG_REL
    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert "packages" not in raw
    cfg = load_config(cfg_path)
    assert cfg["default_max_lines"] == 200
    assert all(item["reason"].strip() for item in cfg["exclude"])
    assert main(["--repo-root", str(REPO_ROOT)]) == 0
