#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any

try:
    from scripts.module_budget_base import (
        DISCOVERY_ROOTS,
        discover_source_modules,
        resolve_base_ref,
        verify_frozen_config,
    )
except ModuleNotFoundError:
    from module_budget_base import (
        DISCOVERY_ROOTS,
        discover_source_modules,
        resolve_base_ref,
        verify_frozen_config,
    )

DEFAULT_CONFIG_REL_PATH = "holon-config/hygiene/module_budgets.json"
__all__ = [
    "DEFAULT_CONFIG_REL_PATH",
    "DISCOVERY_ROOTS",
    "check_repo_budgets",
    "discover_source_modules",
    "evaluate_budgets",
    "load_config",
    "main",
    "verify_frozen_config",
]


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _validate_excludes(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return ["Config field 'exclude' must be a list."]
    errors: list[str] = []
    for idx, entry in enumerate(raw):
        if not isinstance(entry, dict):
            errors.append(f"Config exclude[{idx}] must be an object with 'pattern' and 'reason'.")
            continue
        if not isinstance(entry.get("pattern"), str) or not entry["pattern"].strip():
            errors.append(f"Config exclude[{idx}] is missing a non-empty 'pattern'.")
        if not isinstance(entry.get("reason"), str) or not entry["reason"].strip():
            errors.append(f"Config exclude[{idx}] is missing a non-empty 'reason'.")
    return errors


def _validate_overrides(raw: Any) -> list[str]:
    if not isinstance(raw, dict):
        return ["Config field 'overrides' must be an object mapping path to max_lines."]
    errors: list[str] = []
    for rel_path, limit in raw.items():
        if not isinstance(rel_path, str) or not rel_path.strip():
            errors.append("Config 'overrides' contains an empty path key.")
        elif not _is_positive_int(limit):
            errors.append(f"Config override for '{rel_path}' must be a positive integer.")
    return errors


def load_config(config_path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    if not config_path.is_file():
        return None, [f"Budget config not found: {config_path}"]
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"Failed to parse budget config {config_path}: {exc}"]
    if not isinstance(data, dict):
        return None, ["Budget config root must be a JSON object."]
    errors: list[str] = []
    if not _is_positive_int(data.get("default_max_lines")):
        errors.append("Config field 'default_max_lines' must be a positive integer.")
    errors.extend(_validate_excludes(data.get("exclude", [])))
    errors.extend(_validate_overrides(data.get("overrides", {})))
    return (None, errors) if errors else (data, [])


def is_excluded(rel_path: str, excludes: list[dict[str, str]]) -> bool:
    posix = PurePosixPath(rel_path)
    return any(fnmatch.fnmatch(rel_path, e["pattern"]) or posix.match(e["pattern"]) for e in excludes)


def count_lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def evaluate_budgets(repo_root: Path, config: dict[str, Any], modules: list[str]) -> tuple[list[str], list[str]]:
    default_limit: int = config["default_max_lines"]
    overrides: dict[str, int] = config.get("overrides", {})
    active = [m for m in modules if not is_excluded(m, config.get("exclude", []))]
    active_set = set(active)
    errors: list[str] = []
    notices: list[str] = []
    for rel_path in active:
        actual = count_lines(repo_root / rel_path)
        in_overrides = rel_path in overrides
        limit = overrides[rel_path] if in_overrides else default_limit
        if actual > limit:
            kind = "frozen override exceeded" if in_overrides else f"exceeds default budget of {default_limit}"
            errors.append(f"{rel_path}: {actual} > {limit} lines ({kind})")
        elif in_overrides and actual < limit:
            action = (
                f"remove override (<= {default_limit})" if actual <= default_limit else f"lower override to {actual}"
            )
            notices.append(f"Ratchet notice: {rel_path} shrunk to {actual} lines (< {limit}); {action}")
    for rel_path in sorted(overrides):
        if rel_path not in active_set:
            notices.append(f"Stale override notice: {rel_path} is not an active source module; remove override")
    return errors, notices


def check_repo_budgets(
    repo_root: Path,
    config_rel_path: str = DEFAULT_CONFIG_REL_PATH,
    base_ref: str | None = None,
    verify_base: bool = False,
) -> tuple[list[str], list[str]]:
    config, config_errors = load_config(repo_root / config_rel_path)
    if config is None:
        return config_errors, []
    modules, discovery_errors = discover_source_modules(repo_root)
    if discovery_errors:
        return discovery_errors, []
    errors, notices = evaluate_budgets(repo_root, config, modules)
    if verify_base:
        resolved = resolve_base_ref(repo_root, base_ref)
        if not resolved:
            errors.append("Failed to resolve base ref for frozen config verification (tried origin/main, main).")
        else:
            errors.extend(verify_frozen_config(repo_root, config_rel_path, config, resolved))
    return errors, notices


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Enforce discovery-based module line budgets.")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--config", default=DEFAULT_CONFIG_REL_PATH)
    parser.add_argument("--base-ref", default=None)
    parser.add_argument("--verify-base", action="store_true")
    args = parser.parse_args(argv)
    errors, notices = check_repo_budgets(
        repo_root=args.repo_root.resolve(),
        config_rel_path=args.config,
        base_ref=args.base_ref,
        verify_base=args.verify_base or args.base_ref is not None,
    )
    for notice in notices:
        print(notice)
    for err in errors:
        print(f"ERROR: {err}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
