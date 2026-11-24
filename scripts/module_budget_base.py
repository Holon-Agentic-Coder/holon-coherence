#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

DISCOVERY_ROOTS = ("src", "scripts")


def _run_git(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo_root, capture_output=True, text=True, check=False)


def _git_err(res: subprocess.CompletedProcess[str]) -> str:
    return (res.stderr or res.stdout).strip() or f"exit code {res.returncode}"


def _is_test_path(rel_path: str) -> bool:
    posix = PurePosixPath(rel_path)
    return "tests" in posix.parts or posix.name.startswith("test_")


def discover_source_modules(repo_root: Path) -> tuple[list[str], list[str]]:
    res = _run_git(repo_root, ["ls-files", "-z", "--", *DISCOVERY_ROOTS])
    if res.returncode != 0:
        return [], [f"Failed to discover source modules via git ls-files: {_git_err(res)}"]
    modules = []
    for raw in res.stdout.split("\0"):
        rel = raw.strip().replace("\\", "/")
        if rel and rel.endswith(".py") and not _is_test_path(rel) and (repo_root / rel).is_file():
            modules.append(rel)
    return sorted(modules), []


def resolve_base_ref(repo_root: Path, base_ref: str | None) -> str | None:
    if base_ref:
        return base_ref
    for candidate in ("origin/main", "main"):
        if _run_git(repo_root, ["rev-parse", "--verify", "--quiet", candidate]).returncode == 0:
            return candidate
    return None


def _exclude_patterns(config: dict[str, Any]) -> set[str]:
    raw = config.get("exclude", [])
    if not isinstance(raw, list):
        return set()
    return {e["pattern"] for e in raw if isinstance(e, dict) and isinstance(e.get("pattern"), str)}


def _parse_base_config(raw: str, config_rel_path: str, merge_base: str) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        base_config = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, [f"Failed to parse base config '{config_rel_path}' at {merge_base}: {exc}"]
    if not isinstance(base_config, dict):
        return None, [f"Base config '{config_rel_path}' at {merge_base} must be a JSON object."]
    return base_config, []


def _load_base_config(repo_root: Path, config_rel_path: str, base_ref: str) -> tuple[dict[str, Any] | None, list[str]]:
    mb = _run_git(repo_root, ["merge-base", base_ref, "HEAD"])
    if mb.returncode != 0 or not mb.stdout.strip():
        return None, [f"Failed to compute merge-base with '{base_ref}': {_git_err(mb)}"]
    merge_base = mb.stdout.strip()
    tree = _run_git(repo_root, ["ls-tree", "--name-only", merge_base, "--", config_rel_path])
    if tree.returncode != 0:
        return None, [f"Failed to inspect base config '{config_rel_path}' at {merge_base}: {_git_err(tree)}"]
    if not tree.stdout.strip():
        return None, []
    show = _run_git(repo_root, ["show", f"{merge_base}:{config_rel_path}"])
    if show.returncode != 0:
        return None, [f"Failed to read base config '{config_rel_path}' at {merge_base}: {_git_err(show)}"]
    return _parse_base_config(show.stdout, config_rel_path, merge_base)


def verify_frozen_config(
    repo_root: Path,
    config_rel_path: str,
    current_config: dict[str, Any],
    base_ref: str,
) -> list[str]:
    base_config, load_errors = _load_base_config(repo_root, config_rel_path, base_ref)
    if base_config is None:
        return load_errors
    errors: list[str] = []
    base_default = base_config.get("default_max_lines", 0)
    cur_default = current_config["default_max_lines"]
    if cur_default > base_default:
        errors.append(f"Frozen config violation: default_max_lines raised ({base_default} -> {cur_default})")
    for pattern in sorted(_exclude_patterns(current_config) - _exclude_patterns(base_config)):
        errors.append(f"Frozen config violation: new exclude pattern added ({pattern})")
    base_overrides: dict[str, int] = base_config.get("overrides", {})
    for rel_path, limit in sorted(current_config.get("overrides", {}).items()):
        if rel_path not in base_overrides:
            errors.append(f"Frozen config violation: new override added for {rel_path} ({limit})")
        elif limit > base_overrides[rel_path]:
            prev = base_overrides[rel_path]
            errors.append(f"Frozen config violation: override raised for {rel_path} ({prev} -> {limit})")
    return errors
