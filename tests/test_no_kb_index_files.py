from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
KB_ROOT = REPO_ROOT / "holon-knowledge" / "kb"


def find_kb_index_files(kb_root: Path) -> list[str]:
    return sorted(path.relative_to(kb_root).as_posix() for path in kb_root.rglob("index.json") if path.is_file())


def test_no_index_json_files_under_holon_knowledge_kb() -> None:
    assert KB_ROOT.is_dir()
    assert find_kb_index_files(KB_ROOT) == []


def test_find_kb_index_files_detects_nested_index_json(tmp_path: Path) -> None:
    nested = tmp_path / "patterns" / "index.json"
    nested.parent.mkdir(parents=True)
    nested.write_text("{}\n", encoding="utf-8")
    assert find_kb_index_files(tmp_path) == ["patterns/index.json"]
