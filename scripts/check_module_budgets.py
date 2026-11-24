#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_REL = "holon-config/hygiene/module_budgets.json"
REPO_ROOT = Path(__file__).resolve().parent.parent


def _normalise_posix(path: str) -> str:
    norm = path.replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    return norm


def _is_strict_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _validate_excludes(raw: object) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        raise ValueError("Config 'exclude' must be a list")
    validated: list[dict[str, str]] = []
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(f"Config exclude[{idx}] must be an object")
        path, reason = entry.get("path"), entry.get("reason")
        if not isinstance(path, str) or not path.strip():
            raise ValueError(f"Config exclude[{idx}] missing non-empty 'path'")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"Config exclude[{idx}] missing non-empty 'reason'")
        validated.append({"path": _normalise_posix(path.strip()), "reason": reason.strip()})
    return validated


def _validate_overrides(raw: object, default_max: int) -> dict[str, int]:
    if not isinstance(raw, dict):
        raise ValueError("Config 'overrides' must be an object")
    validated: dict[str, int] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("Config override key must be a non-empty string")
        if not _is_strict_int(value) or value <= default_max:
            raise ValueError(f"Override for {key!r} must be an int > {default_max}")
        validated[_normalise_posix(key.strip())] = value
    return validated


def _validate_config(data: object) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError("Module budget config must be a JSON object")
    if "packages" in data:
        raise ValueError("Module budget config must not define a static 'packages' allowlist")
    default_max = data.get("default_max_lines")
    if not _is_strict_int(default_max) or default_max <= 0:
        raise ValueError("Config 'default_max_lines' must be a positive integer")
    return {
        "default_max_lines": default_max,
        "exclude": _validate_excludes(data.get("exclude")),
        "overrides": _validate_overrides(data.get("overrides"), default_max),
    }


def load_config(config_path: Path) -> dict[str, Any]:
    return _validate_config(json.loads(config_path.read_text(encoding="utf-8")))


def _matches_exclude(rel_path: str, pattern: str) -> bool:
    norm = _normalise_posix(pattern)
    return rel_path.startswith(norm) if norm.endswith("/") else (rel_path == norm or fnmatch.fnmatch(rel_path, norm))


def _is_excluded(rel_path: str, exclude: list[dict[str, str]]) -> bool:
    return rel_path.startswith("tests/") or any(_matches_exclude(rel_path, item["path"]) for item in exclude)


def discover_source_modules(repo_root: Path, exclude: list[dict[str, str]]) -> list[str]:
    cmd = ["git", "ls-files", "-z", "--", "src", "scripts"]
    res = subprocess.run(cmd, cwd=repo_root, capture_output=True, check=True)
    modules: list[str] = []
    for raw in res.stdout.decode("utf-8").split("\0"):
        rel = _normalise_posix(raw)
        if rel.endswith(".py") and not _is_excluded(rel, exclude) and (repo_root / rel).is_file():
            modules.append(rel)
    return sorted(modules)


def count_lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def evaluate_budgets(repo_root: Path, config: dict[str, Any], modules: list[str]) -> tuple[list[str], list[str]]:
    default_max: int = config["default_max_lines"]
    overrides: dict[str, int] = config["overrides"]
    exclude: list[dict[str, str]] = config["exclude"]
    errors: list[str] = []
    notices: list[str] = []
    for rel in modules:
        lines = count_lines(repo_root / rel)
        budget = overrides.get(rel, default_max)
        if lines > budget:
            errors.append(f"{rel}: {lines} lines exceeds budget of {budget} lines")
        elif rel in overrides and lines < budget:
            action = (
                f"shrunk to {lines} lines (<= {default_max}); remove override from module_budgets.json"
                if lines <= default_max
                else f"shrunk from {budget} to {lines} lines; lower override in module_budgets.json"
            )
            notices.append(f"RATCHET-DOWN: {rel} {action}")
    module_set = set(modules)
    for rel in sorted(overrides):
        if rel not in module_set and not _is_excluded(rel, exclude):
            notices.append(f"RATCHET-DOWN: stale override for {rel}; remove from module_budgets.json")
    return errors, notices


def resolve_merge_base(repo_root: Path, base_ref: str | None) -> str | None:
    for ref in [base_ref] if base_ref else ["origin/main", "main"]:
        res = subprocess.run(["git", "merge-base", "HEAD", ref], cwd=repo_root, capture_output=True, text=True)
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    return None


def load_config_at_ref(repo_root: Path, ref: str, config_rel: str) -> dict[str, Any] | None:
    res = subprocess.run(["git", "show", f"{ref}:{config_rel}"], cwd=repo_root, capture_output=True, text=True)
    return None if res.returncode != 0 else _validate_config(json.loads(res.stdout))


def verify_frozen_config(current: dict[str, Any], base: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if current["default_max_lines"] > base["default_max_lines"]:
        errors.append(f"default_max_lines increased from {base['default_max_lines']} to {current['default_max_lines']}")
    base_overrides: dict[str, int] = base["overrides"]
    for path, limit in sorted(current["overrides"].items()):
        if path not in base_overrides:
            errors.append(f"New override not allowed for {path} ({limit} lines)")
        elif limit > base_overrides[path]:
            errors.append(f"Override for {path} increased from {base_overrides[path]} to {limit} lines")
    return errors


def _config_rel_path(repo_root: Path, cfg_path: Path) -> str:
    try:
        return cfg_path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return DEFAULT_CONFIG_REL


def run_check(
    repo_root: Path = REPO_ROOT,
    config_path: Path | None = None,
    base_ref: str | None = None,
    use_merge_base: bool = True,
    require_base: bool = False,
) -> tuple[list[str], list[str]]:
    cfg_path = config_path if config_path is not None else repo_root / DEFAULT_CONFIG_REL
    try:
        config = load_config(cfg_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [f"Invalid module budget config ({cfg_path}): {exc}"], []
    modules = discover_source_modules(repo_root, config["exclude"])
    errors, notices = evaluate_budgets(repo_root, config, modules)
    if use_merge_base:
        config_rel = _config_rel_path(repo_root, cfg_path)
        merge_base = resolve_merge_base(repo_root, base_ref)
        base_config = load_config_at_ref(repo_root, merge_base, config_rel) if merge_base else None
        if base_config is None:
            if require_base:
                errors.append(f"Unable to load baseline module budget config from merge base ({config_rel})")
        else:
            errors.extend(verify_frozen_config(config, base_config))
    return errors, notices


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Python module line budgets.")
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--base-ref", type=str, default=None)
    parser.add_argument("--no-merge-base", action="store_true")
    parser.add_argument("--require-base", action="store_true")
    args = parser.parse_args(argv)
    errors, notices = run_check(args.repo_root, args.config, args.base_ref, not args.no_merge_base, args.require_base)
    for notice in notices:
        print(notice)
    for err in errors:
        print(f"ERROR: {err}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
