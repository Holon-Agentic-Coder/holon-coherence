import pathlib
import re
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from holon_coherence.container.image import ensure_docker_image, resolve_build_context

SCRIPT_PATH = pathlib.Path(__file__).parent.parent / "build_image.sh"


def bash_supports_epochrealtime() -> bool:
    res = subprocess.run(
        ["bash", "-c", '[[ -n "${EPOCHREALTIME:-}" ]] && printf "%(%s)T" -1 >/dev/null 2>&1'],
        capture_output=True,
    )
    return res.returncode == 0


@pytest.mark.skipif(
    not bash_supports_epochrealtime(), reason="Host bash does not support EPOCHREALTIME (requires Bash >= 5.0)"
)
def test_get_timestamp_with_epochrealtime():
    cmd = ["bash", "-c", f'source {SCRIPT_PATH} && ts="" && get_timestamp ts && echo "$ts"']
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    ts = result.stdout.strip()
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}$", ts)


def test_get_timestamp_without_epochrealtime():
    cmd = ["bash", "-c", f'unset EPOCHREALTIME && source {SCRIPT_PATH} && ts="" && get_timestamp ts && echo "$ts"']
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    ts = result.stdout.strip()
    assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", ts)


def test_print_log_with_timestamps():
    cmd = ["bash", "-c", f'source {SCRIPT_PATH} && echo "test log line" | print_log_with_timestamps']
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    output = result.stdout.strip()
    assert re.match(r"^\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(\.\d{3})?\] test log line$", output)


def test_resolve_build_context_finds_repo_root_from_nested_dir(tmp_path: pathlib.Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    (tmp_path / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    nested_file = tmp_path / "a" / "b" / "c" / "d" / "mod.py"
    nested_file.parent.mkdir(parents=True)
    nested_file.write_text("", encoding="utf-8")

    repo_root, dockerfile = resolve_build_context(nested_file)

    assert repo_root == str(tmp_path.resolve())
    assert dockerfile == str((tmp_path / "Dockerfile").resolve())


def test_resolve_build_context_default_locates_repository_dockerfile() -> None:
    repo_root, dockerfile = resolve_build_context()
    expected_root = pathlib.Path(__file__).resolve().parent.parent

    assert repo_root == str(expected_root)
    assert dockerfile == str(expected_root / "Dockerfile")
    assert pathlib.Path(dockerfile).is_file()


def test_resolve_build_context_raises_when_dockerfile_or_pyproject_missing(tmp_path: pathlib.Path) -> None:
    only_pyproject = tmp_path / "only-pyproject" / "sub"
    only_pyproject.mkdir(parents=True)
    (tmp_path / "only-pyproject" / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match=r"pyproject\.toml.*Dockerfile"):
        resolve_build_context(only_pyproject)

    only_dockerfile = tmp_path / "only-dockerfile" / "sub"
    only_dockerfile.mkdir(parents=True)
    (tmp_path / "only-dockerfile" / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match=r"pyproject\.toml.*Dockerfile"):
        resolve_build_context(only_dockerfile)


def test_ensure_docker_image_falls_back_to_pull_when_build_context_missing() -> None:
    failed_inspect = MagicMock(returncode=1)
    succeeded_pull = MagicMock(returncode=0)

    with (
        patch("holon_coherence.container.image.resolve_build_context", side_effect=FileNotFoundError("missing")),
        patch("subprocess.run", side_effect=[failed_inspect, succeeded_pull]) as mock_run,
    ):
        ensure_docker_image("holon-coherence:latest", rebuild=False)

    assert mock_run.call_count == 2
    assert mock_run.call_args_list[1][0][0] == ["docker", "pull", "holon-coherence:latest"]
