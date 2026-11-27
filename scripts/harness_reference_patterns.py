#!/usr/bin/env python3
from __future__ import annotations

import re
from dataclasses import dataclass

_CALL_NESTING = 5
_TASK_DIR_TOKEN = "be" + "ans"
_AGENT_DIR_TOKEN = "sub" + "agent"
_SCRATCH_DIR_TOKEN = "to" + "do"
_TASK_ID_LOWER = "be" + "ans?"
_TASK_ID_TITLE = "Be" + "ans?"

_PATH_CALL = r"""(?:(?<![\w.])join|path\.join|(?:os|path)\.sep\.join|["'](?:/|\\{1,2})["']\.join|joinpath|Path)\("""
_PATH_ORIGIN = r"""(?:(?<![\w.])\.{1,2}|~|\$\w+|\$\{[^{}\n]*\}|\$\([^()\n]*\)|`[^`\n]*`)["']?(?:/|\\{1,2})"""


@dataclass(frozen=True)
class Finding:
    source: str
    line_number: int
    pattern_name: str
    match_text: str


@dataclass(frozen=True)
class NamedPattern:
    name: str
    regex: re.Pattern[str]


def _call_arguments(depth: int) -> str:
    inner = r"[^()]*"
    for _ in range(depth):
        inner = r"(?:[^()]|\(" + inner + r"\))*"
    return inner


def _build_scratch_dir_pattern() -> re.Pattern[str]:
    slash_form = r"(?<![\w.-])" + _SCRATCH_DIR_TOKEN + r"/"
    call_form = (
        "(?:"
        + _PATH_CALL
        + _call_arguments(_CALL_NESTING)
        + r"""(?:\*?\s*(?<![\w)\]])\([^()]*)?|/\s*)[rRbBuUfF]{0,2}["']"""
        + _SCRATCH_DIR_TOKEN
        + r"""["']|["']"""
        + _SCRATCH_DIR_TOKEN
        + r"""["']\s*/"""
    )
    quoted_path_form = r"""["'`][^"'`\s]*/""" + _SCRATCH_DIR_TOKEN + r"""["'`]"""
    origin_form = _PATH_ORIGIN + _SCRATCH_DIR_TOKEN + r"(?![\w-]|\.\w)"
    return re.compile(f"(?:{slash_form}|{call_form}|{quoted_path_form}|{origin_form})")


def compile_patterns() -> tuple[NamedPattern, ...]:
    return (
        NamedPattern(
            name="task_tracking_dir",
            regex=re.compile(r"(?<![\w-])\." + _TASK_DIR_TOKEN + r"(?:/|(?![\w-]))"),
        ),
        NamedPattern(
            name="agent_instruction_dir",
            regex=re.compile(r"(?<![\w-])\." + _AGENT_DIR_TOKEN + r"(?:/|(?![\w-]))"),
        ),
        NamedPattern(
            name="scratch_dir",
            regex=_build_scratch_dir_pattern(),
        ),
        NamedPattern(
            name="four_digit_task_id",
            regex=re.compile(r"(?:(?i:(?<![a-z])" + _TASK_ID_LOWER + r")|" + _TASK_ID_TITLE + r")[ _:#-]*\d{4}(?!\d)"),
        ),
    )


PATTERNS: tuple[NamedPattern, ...] = compile_patterns()


def scan_line(text: str, source: str, line_number: int) -> list[Finding]:
    findings: list[Finding] = []
    for named in PATTERNS:
        for match in named.regex.finditer(text):
            findings.append(
                Finding(
                    source=source,
                    line_number=line_number,
                    pattern_name=named.name,
                    match_text=match.group(0),
                )
            )
    return findings


def scan_text(text: str, source: str) -> list[Finding]:
    findings: list[Finding] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        findings.extend(scan_line(line, source, line_number))
    return findings
