from __future__ import annotations

import re
import string
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "holon-config" / "prompts" / "planner.template.md"

BASELINE_PLACEHOLDERS = frozenset(
    {
        "agent",
        "agent_version",
        "model",
        "safe_model",
        "intent_id",
        "parent_intent_id",
        "timestamp",
        "date",
        "plan_id",
        "budget_from_intent",
        "description",
        "intent_json",
    }
)
TOUCH_SET_PLACEHOLDER = "repository_relative_path_or_glob"
EXCLUDED_DIRS = ("plans/", "executions/", "holon-knowledge/")
TOUCH_SET_HEADING = re.compile(r"^### \d+\. Touch Set$", re.MULTILINE)
EXAMPLE_BLOCK = re.compile(
    r"^```markdown\n(?:(?!^```).*\n)*?^## Touch Set\n\n- `\{" + TOUCH_SET_PLACEHOLDER + r"\}`\n(?:(?!^```).*\n)*?^```$",
    re.MULTILINE,
)
TOUCH_SET_BULLET = re.compile(r"^- `([^`]+)`$", re.MULTILINE)


def template_text() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def placeholders(text: str) -> set[str]:
    return {field for _, field, _, _ in string.Formatter().parse(text) if field}


def heading_index(text: str, title: str) -> int:
    match = re.search(r"^### \d+\. " + re.escape(title) + r"$", text, re.MULTILINE)
    assert match is not None, title
    return match.start()


def section(text: str, title: str) -> str:
    start = heading_index(text, title)
    following = re.search(r"^### ", text[start + 1 :], re.MULTILINE)
    end = start + 1 + following.start() if following else len(text)
    return text[start:end]


def normalised(text: str) -> str:
    return " ".join(text.split())


def has_touch_set_instruction(text: str) -> bool:
    return TOUCH_SET_HEADING.search(text) is not None


def has_touch_set_example(text: str) -> bool:
    return EXAMPLE_BLOCK.search(text) is not None


def touch_set_entries(plan: str) -> list[str] | None:
    match = re.search(r"^## Touch Set\n(.*?)(?=^## |\Z)", plan, re.MULTILINE | re.DOTALL)
    if match is None:
        return None
    body = match.group(1)
    if re.search(r"^- none$", body, re.MULTILINE):
        return []
    return TOUCH_SET_BULLET.findall(body)


def rendered_template() -> str:
    names = BASELINE_PLACEHOLDERS | {TOUCH_SET_PLACEHOLDER}
    return template_text().format(**{name: f"<{name}>" for name in names})


def test_template_instructs_touch_set_section() -> None:
    text = template_text()
    assert has_touch_set_instruction(text)
    body = normalised(section(text, "Touch Set"))
    assert "`## Touch Set`" in body
    assert "module granularity" in body
    assert "one backticked repository-relative path" in body
    assert "per top-level bullet" in body
    assert "`- none`" in body


def test_touch_set_section_follows_plan_description_and_strategy() -> None:
    text = template_text()
    touch_set = heading_index(text, "Touch Set")
    assert heading_index(text, "Plan Description & Strategy") < touch_set
    assert touch_set < heading_index(text, "Step-by-Step Breakdown")


def test_touch_set_excludes_provenance_dirs() -> None:
    body = section(template_text(), "Touch Set")
    for excluded in EXCLUDED_DIRS:
        assert f"`{excluded}`" in body


def test_plan_format_example_has_touch_set_block() -> None:
    assert has_touch_set_example(template_text())


def test_baseline_placeholders_preserved() -> None:
    found = placeholders(template_text())
    assert found >= BASELINE_PLACEHOLDERS
    assert found - BASELINE_PLACEHOLDERS == {TOUCH_SET_PLACEHOLDER}


def test_template_renders_with_planner_format_call() -> None:
    rendered = rendered_template()
    assert re.search(r"\{[A-Za-z_][A-Za-z0-9_]*\}", rendered) is None
    assert "## Touch Set" in rendered


def test_rendered_plan_touch_set_is_parsable() -> None:
    example = EXAMPLE_BLOCK.search(template_text())
    assert example is not None
    block = example.group(0)
    plan = block.replace("{" + TOUCH_SET_PLACEHOLDER + "}", "holon-config/prompts/planner.template.md")
    assert touch_set_entries(plan) == ["holon-config/prompts/planner.template.md"]
    empty_plan = re.sub(r"^- `\{" + TOUCH_SET_PLACEHOLDER + r"\}`$", "- none", block, flags=re.MULTILINE)
    assert touch_set_entries(empty_plan) == []
    assert touch_set_entries(block.replace("## Touch Set", "## Other")) is None


def test_missing_touch_set_section_is_detected() -> None:
    text = template_text()
    stripped = text.replace(section(text, "Touch Set"), "")
    stripped = EXAMPLE_BLOCK.sub("", stripped)
    assert not has_touch_set_instruction(stripped)
    assert not has_touch_set_example(stripped)
