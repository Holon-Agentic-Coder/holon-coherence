import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).parent.parent

BUILD_SELF_DOC_FILES = (
    "Makefile",
    "config/config.mk",
    "Dockerfile",
    "build_image.sh",
    "docker-bake.hcl",
)

ALLOWED_DIRECTIVE_PREFIXES = (
    "# syntax=",
    "# escape=",
    "# check=",
    "# shellcheck ",
    "# -*-",
    "# vim:",
    "# SPDX-License-Identifier:",
)


def _is_allowed_directive_comment(line: str, *, is_first_line: bool) -> bool:
    stripped = line.strip()
    if is_first_line and stripped.startswith("#!"):
        return True
    return stripped.startswith(ALLOWED_DIRECTIVE_PREFIXES)


def _find_explanatory_comment_lines(text: str) -> list[tuple[int, str]]:
    offenders: list[tuple[int, str]] = []
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        is_comment = stripped.startswith(("#", "//", "/*"))
        if is_comment and not _is_allowed_directive_comment(stripped, is_first_line=(lineno == 1)):
            offenders.append((lineno, raw_line))
    return offenders


@pytest.mark.parametrize("relative_path", BUILD_SELF_DOC_FILES)
def test_build_files_contain_no_explanatory_comments(relative_path):
    content = (REPO_ROOT / relative_path).read_text(encoding="utf-8")
    offenders = _find_explanatory_comment_lines(content)
    assert offenders == [], f"{relative_path} contains explanatory comments: {offenders}"


@pytest.mark.parametrize(
    "line,is_first_line,expected",
    [
        ("#!/usr/bin/env bash", True, True),
        ("#!/usr/bin/env bash", False, False),
        ("# syntax=docker/dockerfile:1", True, True),
        ("# escape=`", False, True),
        ("# check=skip=JSONArgsRecommended", False, True),
        ("# shellcheck disable=SC2034", False, True),
        ("# SPDX-License-Identifier: MIT", True, True),
        ("# Install Docker based on operating system", False, False),
        ("## Section Banner", False, False),
        ("// HCL comment", False, False),
        ("/* block comment */", False, False),
    ],
)
def test_is_allowed_directive_comment_classifier(line, is_first_line, expected):
    assert _is_allowed_directive_comment(line, is_first_line=is_first_line) is expected
