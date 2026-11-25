import os
import pathlib
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="make is not installed on host")

REPO_ROOT = pathlib.Path(__file__).parent.parent

STUB_CONDA_SCRIPT = """#!/bin/sh
printf '%s\\n' "$*" >> "$CONDA_STUB_LOG"
if [ "$1" = "env" ] && [ "$2" = "list" ]; then
    if [ -f "$CONDA_STUB_ENV_LIST" ]; then
        cat "$CONDA_STUB_ENV_LIST"
    fi
fi
exit 0
"""

STUB_TOOL_SCRIPT = """#!/bin/sh
printf '%s-stub\\n' "$*"
exit 0
"""

PROBE_PATH_TOOLS = ("docker", "openssl", "npx", "uv")
PREREQUISITES_SYSTEM_TOOLS = ("awk", "cat", "grep", "make", "printf", "sed", "sleep", "tr", "uname")
INSTALLING_TARGETS = ("install-homebrew", "install-docker", "install-miniforge", "check-docker")


def _stub_conda_run_env(tmp_path, existing_envs=(), env_extra=None):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "conda"
    stub.write_text(STUB_CONDA_SCRIPT)
    stub.chmod(0o755)
    call_log = tmp_path / "conda-calls.log"
    call_log.write_text("")
    env_list = tmp_path / "conda-env-list.txt"
    env_list.write_text("".join(f"{name} {tmp_path / 'envs' / name}\n" for name in existing_envs))

    run_env = {
        "PATH": os.pathsep.join([str(bin_dir), "/bin", "/usr/bin"]),
        "HOME": str(tmp_path),
        "CONDA_EXE": str(stub),
        "CONDA_STUB_LOG": str(call_log),
        "CONDA_STUB_ENV_LIST": str(env_list),
        "CI": "true",
        "NONINTERACTIVE": "1",
    }
    run_env.update(env_extra or {})

    resolved = subprocess.run(
        ["/bin/sh", "-c", "command -v conda"], capture_output=True, text=True, env=run_env, timeout=15
    )
    assert resolved.stdout.strip() == str(stub), "the stub conda must shadow any conda on the host"
    return run_env, call_log


def _link_prerequisite_system_tools(bin_dir):
    tools_dir = bin_dir / "system"
    tools_dir.mkdir(exist_ok=True)
    for tool in PREREQUISITES_SYSTEM_TOOLS:
        source = shutil.which(tool)
        assert source is not None, f"{tool} is required to run the prerequisite probe"
        link = tools_dir / tool
        if not link.exists():
            link.symlink_to(source)
    return tools_dir


def _assert_stub_path_isolation(
    probe_path: str,
    tmp_path: pathlib.Path,
    path_tools: tuple[str, ...],
) -> None:
    sandbox = os.path.realpath(tmp_path)
    for tool in PROBE_PATH_TOOLS:
        resolved = shutil.which(tool, path=probe_path)
        if tool in path_tools:
            assert resolved is not None and os.path.realpath(resolved).startswith(sandbox + os.sep), (
                f"{tool} resolved outside the sandbox: {resolved}"
            )
        else:
            assert resolved is None, f"{tool} leaked into the stub PATH: {resolved}"
    conda_resolved = shutil.which("conda", path=probe_path)
    assert conda_resolved is not None and os.path.realpath(conda_resolved).startswith(sandbox + os.sep), (
        f"conda resolved outside the sandbox: {conda_resolved}"
    )


def _prerequisites_run_env(tmp_path, *, path_tools=(), uv_prefix="default", env_list_line=None):
    run_env, _ = _stub_conda_run_env(tmp_path, existing_envs=("holon",))
    bin_dir = tmp_path / "bin"
    system_dir = _link_prerequisite_system_tools(bin_dir)
    isolated_stub_and_allowlist_path = os.pathsep.join([str(bin_dir), str(system_dir)])
    run_env["PATH"] = isolated_stub_and_allowlist_path
    run_env.pop("CI", None)
    run_env.pop("NONINTERACTIVE", None)
    run_env["NO_COLOR"] = "1"
    for tool in path_tools:
        script = tmp_path / "bin" / tool
        script.write_text(STUB_TOOL_SCRIPT)
        script.chmod(0o755)
    if uv_prefix == "default":
        uv_prefix = tmp_path / "envs" / "holon"
    if uv_prefix is not None:
        uv = pathlib.Path(uv_prefix) / "bin" / "uv"
        uv.parent.mkdir(parents=True, exist_ok=True)
        uv.write_text(STUB_TOOL_SCRIPT)
        uv.chmod(0o755)
    if env_list_line is not None:
        pathlib.Path(run_env["CONDA_STUB_ENV_LIST"]).write_text(env_list_line)
    _assert_stub_path_isolation(run_env["PATH"], tmp_path, path_tools)
    return run_env


def _run_check_prerequisites(tmp_path, extra_args=(), **kwargs):
    run_env = _prerequisites_run_env(tmp_path, **kwargs)
    return subprocess.run(
        ["make", *extra_args, "check-prerequisites"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=run_env,
        timeout=120,
    )


def _probe_lines(stdout):
    return [line for line in stdout.splitlines() if line.startswith("Checking ")]


def _makefile_recipe_lines(target):
    lines = (REPO_ROOT / "Makefile").read_text().splitlines()
    best: list[str] = []
    for index, line in enumerate(lines):
        if not line.startswith(f"{target}:"):
            continue
        recipe = []
        for following in lines[index + 1 :]:
            if not following.startswith("\t"):
                break
            recipe.append(following.lstrip("\t@"))
        if len(recipe) > len(best):
            best = recipe
    assert best, f"no recipe found for {target}"
    return " ".join(best).split(";")


def test_check_prerequisites_succeeds_when_every_probe_is_satisfied(tmp_path):
    result = _run_check_prerequisites(
        tmp_path, path_tools=("docker", "openssl", "npx"), uv_prefix=tmp_path / "envs" / "holon"
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "uv inside conda env holon" in result.stdout
    assert "Missing: openssl" not in result.stdout
    assert "All prerequisites are satisfied" in result.stdout


def test_check_prerequisites_fails_when_openssl_is_missing(tmp_path):
    result = _run_check_prerequisites(tmp_path, path_tools=("docker", "npx"), uv_prefix=tmp_path / "envs" / "holon")
    assert result.returncode != 0
    assert "Missing: openssl not found" in result.stdout
    assert "ca_generator.py" in result.stdout


def test_check_prerequisites_fails_when_uv_is_missing_from_env_and_path(tmp_path):
    result = _run_check_prerequisites(tmp_path, path_tools=("docker", "openssl", "npx"), uv_prefix=None)
    assert result.returncode != 0
    assert "Missing: uv not found on PATH or in conda env 'holon'" in result.stdout


def test_check_prerequisites_advisory_npx_warning_exits_zero(tmp_path):
    result = _run_check_prerequisites(tmp_path, path_tools=("docker", "openssl"), uv_prefix=tmp_path / "envs" / "holon")
    assert result.returncode == 0, result.stdout
    assert "Missing: npx not found" in result.stdout
    assert "optional/advisory check(s) raised warnings" in result.stdout
    assert "All prerequisites are satisfied" not in result.stdout


def test_check_prerequisites_uv_on_path_only_warns_instead_of_failing(tmp_path):
    result = _run_check_prerequisites(tmp_path, path_tools=("docker", "openssl", "npx", "uv"), uv_prefix=None)
    assert result.returncode == 0, result.stdout
    assert "Found on PATH only" in result.stdout
    assert "uv is NOT installed in conda env 'holon'" in result.stdout


def test_check_prerequisites_hard_failure_outweighs_advisory_warnings(tmp_path):
    result = _run_check_prerequisites(tmp_path, path_tools=("docker",), uv_prefix=tmp_path / "envs" / "holon")
    assert result.returncode != 0
    assert "Missing: openssl not found" in result.stdout
    assert "Missing: npx not found" in result.stdout


def test_check_prerequisites_accepts_an_env_prefix_containing_whitespace(tmp_path):
    prefix = tmp_path / "envs" / "my dev env"
    result = _run_check_prerequisites(
        tmp_path,
        path_tools=("docker", "openssl", "npx"),
        uv_prefix=prefix,
        env_list_line=f"holon {prefix}\n",
    )
    assert result.returncode == 0, result.stdout
    assert "uv inside conda env holon" in result.stdout


@pytest.mark.parametrize(
    "flags",
    [
        ["-n"],
        ["-s", "-n"],
        ["--dry-run"],
        ["-Bn"],
        ["--no-print-directory", "-n"],
        ["-n", "--no-print-directory"],
        ["-B", "--no-print-directory", "-n"],
        ["--warn-undefined-variables", "-n"],
    ],
    ids=["n", "s-n", "long", "bundled", "npd-then-n", "n-then-npd", "B-npd-n", "warn-undef-n"],
)
def test_check_prerequisites_stays_inert_under_every_dry_run_spelling(tmp_path, flags):
    result = _run_check_prerequisites(
        tmp_path,
        extra_args=flags,
        path_tools=("docker", "openssl", "npx"),
        uv_prefix=tmp_path / "envs" / "holon",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert _probe_lines(result.stdout) == [], f"{flags} executed the checks:\n{result.stdout}"


@pytest.mark.parametrize(
    "flags",
    [
        ["--no-print-directory"],
        ["--warn-undefined-variables"],
        ["-I", "n"],
        ["--no-print-directory", "-I", "n"],
    ],
    ids=["npd-only", "warn-undef-only", "include-dir-n", "npd-include-dir-n"],
)
def test_check_prerequisites_probes_when_no_dry_run_was_asked_for(tmp_path, flags):
    include_dir = tmp_path / "n"
    include_dir.mkdir(exist_ok=True)
    result = _run_check_prerequisites(
        tmp_path,
        extra_args=flags,
        path_tools=("docker", "openssl", "npx"),
        uv_prefix=tmp_path / "envs" / "holon",
    )
    probes = _probe_lines(result.stdout)
    assert probes, f"{flags} was read as a dry run and skipped the checks:\n{result.stdout}"
    assert result.returncode == 0, result.stdout + result.stderr


def test_installing_recipes_never_reference_make():
    for target in INSTALLING_TARGETS:
        offenders = [command for command in _makefile_recipe_lines(target) if "$(MAKE)" in command]
        assert offenders == [], f"{target} can install from a line that runs even under -n: {offenders}"


def test_check_prerequisites_runs_when_an_option_argument_spells_n(tmp_path):
    include_dir = tmp_path / "incdir_n"
    include_dir.mkdir()
    result = _run_check_prerequisites(
        tmp_path,
        extra_args=["-I", str(include_dir)],
        path_tools=("docker", "openssl", "npx"),
        uv_prefix=tmp_path / "envs" / "holon",
    )
    probes = _probe_lines(result.stdout)
    assert probes, f"the guard misread the -I argument as a dry run:\n{result.stdout}"
    assert any(line.startswith("Checking OpenSSL") for line in probes)
    assert result.returncode == 0, result.stdout + result.stderr


def test_check_prerequisites_openssl_hint_names_the_host_package_manager(tmp_path):
    result = _run_check_prerequisites(tmp_path, path_tools=("docker", "npx"), uv_prefix=tmp_path / "envs" / "holon")
    assert "openssl not found" in result.stdout
    assert "ca_generator.py" in result.stdout
    if os.uname().sysname == "Darwin":
        assert "brew install openssl" in result.stdout
        assert "sudo apt install openssl" not in result.stdout
    else:
        assert "sudo apt install openssl" in result.stdout
        assert "brew install openssl" not in result.stdout


def test_check_prerequisites_runs_when_a_command_line_assignment_spells_n(tmp_path):
    result = _run_check_prerequisites(
        tmp_path,
        extra_args=["DETECTED_OS=Linux"],
        path_tools=("docker", "openssl", "npx"),
        uv_prefix=tmp_path / "envs" / "holon",
    )
    probes = _probe_lines(result.stdout)
    assert probes, f"the guard misread an assignment as a dry run:\n{result.stdout}"
    assert any(line.startswith("Checking Docker CLI") for line in probes)


def test_check_prerequisites_uv_probe_inspects_the_requested_env_not_the_active_one(tmp_path):
    active_prefix = tmp_path / "envs" / "active"
    run_env = _prerequisites_run_env(
        tmp_path,
        path_tools=("docker", "openssl", "npx"),
        uv_prefix=active_prefix,
        env_list_line=f"active {active_prefix}\nother {tmp_path / 'envs' / 'other'}\n",
    )
    run_env["CONDA_PREFIX"] = str(active_prefix)
    run_env["CONDA_DEFAULT_ENV"] = "active"

    result = subprocess.run(
        ["make", "check-prerequisites", "CONDA_ENV=other"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=run_env,
        timeout=120,
    )

    assert "uv inside conda env active" not in result.stdout, result.stdout
    assert "other" in result.stdout
    assert result.returncode != 0, "uv is not installed in 'other', so the probe must fail"
