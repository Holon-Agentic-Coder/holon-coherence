import os
import pathlib
import pty
import re
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="make is not installed on host")

REPO_ROOT = pathlib.Path(__file__).parent.parent
ENV_NO_COLOR = {**os.environ, "NO_COLOR": "1"}

CONDA_WRITE_TARGETS = ("holon", "custom_dev", "base")

STUB_CONDA_SCRIPT = """#!/bin/sh
printf '%s\\n' "$*" >> "$CONDA_STUB_LOG"
if [ "$1" = "env" ] && [ "$2" = "list" ]; then
    if [ -f "$CONDA_STUB_ENV_LIST" ]; then
        cat "$CONDA_STUB_ENV_LIST"
    fi
fi
exit 0
"""

PRUNE_GUARD_RE = re.compile(r'CONDA_PRUNE_FLAG="";\s*if \[ "([^"]*)" = "1" \] \|\| \[ "([^"]*)" = "true" \]')


def _shell_supports_timed_read():
    probe = subprocess.run(
        ["/bin/sh", "-c", "printf 'y\\n' | read -r -t 1 _holon_probe >/dev/null 2>&1"],
        capture_output=True,
        timeout=15,
    )
    return probe.returncode == 0


SHELL_HAS_TIMED_READ = _shell_supports_timed_read()
requires_timed_read = pytest.mark.skipif(
    not SHELL_HAS_TIMED_READ,
    reason="/bin/sh read has no -t timeout support (dash), so the timed prompt is skipped by design",
)


def _minimal_env(**overrides):
    env = {
        "PATH": "/bin:/usr/bin:/usr/local/bin",
        "HOME": os.environ.get("HOME", "/"),
        "NO_COLOR": "1",
        "CI": "true",
        "NONINTERACTIVE": "1",
    }
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def _create_conda_env_dry_run(make_vars=None, env_vars=None):
    command = ["make", "-n", "create-conda-env"]
    command += [f"{name}={value}" for name, value in (make_vars or {}).items()]
    return subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=_minimal_env(**(env_vars or {})),
        timeout=30,
    )


def _join_continuation_lines(stdout):
    commands, buffered = [], ""
    for line in stdout.splitlines():
        if line.endswith("\\"):
            buffered += line[:-1] + " "
        else:
            commands.append((buffered + line).strip())
            buffered = ""
    if buffered.strip():
        commands.append(buffered.strip())
    return commands


def _create_conda_env_recipe(make_vars=None, env_vars=None):
    result = _create_conda_env_dry_run(make_vars=make_vars, env_vars=env_vars)
    assert result.returncode == 0, result.stderr
    recipes = [command for command in _join_continuation_lines(result.stdout) if "CHOSEN_ENV=" in command]
    assert len(recipes) == 1, f"expected exactly one create-conda-env recipe, got {len(recipes)}"
    return result.stdout, recipes[0]


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


def _recorded_calls(call_log):
    return [line for line in call_log.read_text().splitlines() if line.strip()]


def _run_recipe_against_stub_conda(tmp_path, recipe, existing_envs=(), env_extra=None, expect_success=True):
    run_env, call_log = _stub_conda_run_env(tmp_path, existing_envs, env_extra)

    result = subprocess.run(
        ["/bin/sh", "-c", recipe],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=run_env,
        stdin=subprocess.DEVNULL,
        timeout=60,
    )
    if expect_success:
        assert result.returncode == 0, result.stderr
    else:
        assert result.returncode != 0, f"the recipe was expected to refuse, but it succeeded:\n{result.stdout}"
    return result, _recorded_calls(call_log)


def _run_recipe_on_tty(  # noqa: PLR0913
    tmp_path, recipe, keystrokes=None, existing_envs=(), env_extra=None, timeout=30, shell="/bin/sh"
):
    run_env, call_log = _stub_conda_run_env(tmp_path, existing_envs, env_extra)
    master, slave = pty.openpty()
    try:
        if keystrokes:
            os.write(master, keystrokes)
        result = subprocess.run(
            [shell, "-c", recipe],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=run_env,
            stdin=slave,
            timeout=timeout,
        )
    finally:
        os.close(master)
        os.close(slave)
    return result, _recorded_calls(call_log)


@pytest.mark.skipif(shutil.which("/bin/dash") is None, reason="dash is not available on this host")
def test_create_conda_env_refuses_on_a_shell_whose_read_cannot_time_out(tmp_path):
    stdout, recipe = _create_conda_env_recipe(
        make_vars={"CONDA_PROMPT_TIMEOUT": "1"},
        env_vars={"CI": None, "NONINTERACTIVE": None},
    )
    assert "CHOSEN_ENV='holon'" in stdout

    result, calls = _run_recipe_on_tty(tmp_path, recipe, existing_envs=("base", "holon"), shell="/bin/dash")

    assert result.returncode != 0, f"dash answered the unanswerable prompt:\n{result.stdout}"
    assert "cannot time out" in result.stdout
    assert "Nothing was installed" in result.stdout
    assert "CONDA_ENV=<name>" in result.stdout
    assert calls == []


def _emitted_prune_guard_is_enabled(stdout):
    emitted = " ".join(_join_continuation_lines(stdout))
    match = PRUNE_GUARD_RE.search(emitted)
    assert match is not None, "CONDA_PRUNE guard missing from the emitted recipe"
    assert 'env update -n "$CHOSEN_ENV" -f environment.yml $CONDA_PRUNE_FLAG' in emitted
    return match.group(1) in {"1", "true"}


def test_makefile_help():
    result = subprocess.run(
        ["make", "help"], cwd=REPO_ROOT, capture_output=True, text=True, env=ENV_NO_COLOR, timeout=15
    )
    assert result.returncode == 0
    assert "Usage: make [target]" in result.stdout
    assert "check-prerequisites" in result.stdout
    assert "check-docker" in result.stdout
    assert "install-docker" in result.stdout
    assert "install-miniforge" in result.stdout
    assert "create-conda-env" in result.stdout
    assert "activate-conda-env" in result.stdout
    assert "build-image" in result.stdout
    assert "build-images" in result.stdout
    assert "tools" in result.stdout
    assert "check" in result.stdout
    assert "lint" in result.stdout
    assert "lint-json" in result.stdout
    assert "lint-yaml" in result.stdout
    assert "lint-shell" in result.stdout
    assert "lint-md" in result.stdout
    assert "pre-commit-check" in result.stdout


def test_makefile_help_documents_conda_variables():
    result = subprocess.run(
        ["make", "help"], cwd=REPO_ROOT, capture_output=True, text=True, env=ENV_NO_COLOR, timeout=15
    )
    assert result.returncode == 0
    assert "Variables:" in result.stdout
    assert "CONDA_ENV" in result.stdout
    assert "CONDA_WRITE_ENV" in result.stdout
    assert "CONDA_PRUNE" in result.stdout
    assert "NONINTERACTIVE" in result.stdout
    assert "CONDA_ALLOW_BASE" in result.stdout
    assert "CONDA_PROMPT_TIMEOUT" in result.stdout


def test_makefile_default_goal():
    result = subprocess.run(["make"], cwd=REPO_ROOT, capture_output=True, text=True, env=ENV_NO_COLOR, timeout=15)
    assert result.returncode == 0
    assert "Usage: make [target]" in result.stdout


@pytest.mark.parametrize(
    "target",
    [
        "help",
        "check-docker",
        "check-prerequisites",
        "build-image",
        "build-images",
        "create-conda-env",
        "activate-conda-env",
        "tools",
        "check",
        "lint",
        "lint-json",
        "lint-yaml",
        "lint-shell",
        "lint-md",
        "pre-commit-check",
    ],
)
def test_makefile_dry_run(target):
    result = subprocess.run(
        ["make", "-n", target], cwd=REPO_ROOT, capture_output=True, text=True, env=ENV_NO_COLOR, timeout=15
    )
    assert result.returncode == 0


def test_create_conda_env_dry_run():
    result = _create_conda_env_dry_run(make_vars={"CONDA_ENV": "custom_dev"})
    assert result.returncode == 0
    assert "$CONDA_BIN" in result.stdout
    assert "CHOSEN_ENV='custom_dev'" in result.stdout


@pytest.mark.parametrize("env_name", CONDA_WRITE_TARGETS)
def test_create_conda_env_dry_run_targets_only_the_requested_env(env_name):
    stdout = _create_conda_env_dry_run(make_vars={"CONDA_ENV": env_name}).stdout
    assert f"CHOSEN_ENV='{env_name}'" in stdout
    for other in CONDA_WRITE_TARGETS:
        if other != env_name:
            assert f"CHOSEN_ENV='{other}'" not in stdout
    expected_consent = "true" if env_name == "base" else "false"
    refused_consent = "false" if expected_consent == "true" else "true"
    assert f'BASE_CONSENT="{expected_consent}"' in stdout
    assert f'BASE_CONSENT="{refused_consent}"' not in stdout
    assert not _emitted_prune_guard_is_enabled(stdout)


def test_create_conda_env_dry_run_active_base_does_not_target_base():
    stdout = _create_conda_env_dry_run(env_vars={"CONDA_DEFAULT_ENV": "base", "CONDA_PREFIX": "/tmp/fake/base"}).stdout
    assert "CHOSEN_ENV='holon'" in stdout
    assert "CHOSEN_ENV='base'" not in stdout
    assert 'BASE_CONSENT="false"' in stdout
    assert 'BASE_CONSENT="true"' not in stdout


@pytest.mark.parametrize(
    "prompt_timeout,expected_literal",
    [(None, "PROMPT_TIMEOUT='20'"), ("3", "PROMPT_TIMEOUT='3'"), ("1", "PROMPT_TIMEOUT='1'")],
)
def test_create_conda_env_dry_run_bounds_the_prompt_by_read_timeout(prompt_timeout, expected_literal):
    make_vars = {"CONDA_ENV": "holon"}
    if prompt_timeout is not None:
        make_vars["CONDA_PROMPT_TIMEOUT"] = prompt_timeout
    stdout = _create_conda_env_dry_run(make_vars=make_vars).stdout
    assert expected_literal in stdout
    assert 'read -r -t "$PROMPT_TIMEOUT" USER_INPUT' in stdout
    assert 'read -r -t "$PROMPT_TIMEOUT" BASE_REPLY' in stdout
    assert "read -r USER_INPUT" not in stdout


@pytest.mark.parametrize(
    "prune_value,prune_expected",
    [(None, False), ("false", False), ("0", False), ("1", True), ("true", True)],
)
def test_create_conda_env_dry_run_prune_tracks_conda_prune(prune_value, prune_expected):
    make_vars = {"CONDA_ENV": "holon"}
    if prune_value is not None:
        make_vars["CONDA_PRUNE"] = prune_value
    stdout = _create_conda_env_dry_run(make_vars=make_vars).stdout
    assert _emitted_prune_guard_is_enabled(stdout) is prune_expected


def test_create_conda_env_non_interactive_default_never_writes_to_base(tmp_path):
    stdout, recipe = _create_conda_env_recipe()
    assert "CHOSEN_ENV='holon'" in stdout

    result, calls = _run_recipe_against_stub_conda(tmp_path, recipe, existing_envs=("base", "holon"))

    assert "Setting up Conda environment 'holon'" in result.stdout
    assert "Enter target environment name" not in result.stdout
    assert "env update -n holon -f environment.yml" in calls
    assert not [call for call in calls if call.startswith("install")]
    assert not [call for call in calls if re.search(r"-n\s+base(\s|$)", call)]
    assert not [call for call in calls if call.startswith("env create")]


def test_create_conda_env_non_interactive_active_base_never_writes_to_base(tmp_path):
    stdout, recipe = _create_conda_env_recipe(env_vars={"CONDA_DEFAULT_ENV": "base"})
    assert "CHOSEN_ENV='holon'" in stdout
    assert 'BASE_CONSENT="false"' in stdout

    _, calls = _run_recipe_against_stub_conda(
        tmp_path,
        recipe,
        existing_envs=("base", "holon"),
        env_extra={"CONDA_DEFAULT_ENV": "base", "CONDA_PREFIX": str(tmp_path / "envs" / "base")},
    )

    assert "env update -n holon -f environment.yml" in calls
    assert not [call for call in calls if call.startswith("install")]
    assert not [call for call in calls if re.search(r"-n\s+base(\s|$)", call)]


def test_create_conda_env_non_interactive_base_request_installs_into_base(tmp_path):
    stdout, recipe = _create_conda_env_recipe(make_vars={"CONDA_ENV": "base"})
    assert "CHOSEN_ENV='base'" in stdout
    assert 'BASE_CONSENT="true"' in stdout

    _, calls = _run_recipe_against_stub_conda(tmp_path, recipe, existing_envs=("base", "holon"))

    assert calls == ["install -y -n base -c conda-forge uv python=3.13"]


def test_create_conda_env_non_interactive_new_env_uses_env_create(tmp_path):
    stdout, recipe = _create_conda_env_recipe(make_vars={"CONDA_ENV": "custom_dev"})
    assert "CHOSEN_ENV='custom_dev'" in stdout

    _, calls = _run_recipe_against_stub_conda(tmp_path, recipe, existing_envs=("base", "holon"))

    assert calls == ["env list", "env create -n custom_dev -f environment.yml"]
    assert not [call for call in calls if call.startswith("install")]


@pytest.mark.parametrize(
    "prune_value,prune_expected",
    [(None, False), ("false", False), ("1", True), ("true", True)],
)
def test_create_conda_env_non_interactive_prune_tracks_conda_prune(tmp_path, prune_value, prune_expected):
    make_vars = {"CONDA_ENV": "holon"}
    if prune_value is not None:
        make_vars["CONDA_PRUNE"] = prune_value
    _, recipe = _create_conda_env_recipe(make_vars=make_vars)

    _, calls = _run_recipe_against_stub_conda(tmp_path, recipe, existing_envs=("holon",))

    updates = [call for call in calls if call.startswith("env update")]
    assert len(updates) == 1
    assert ("--prune" in updates[0]) is prune_expected


def test_create_conda_env_inherited_base_env_is_refused_without_installing(tmp_path):
    stdout, recipe = _create_conda_env_recipe(env_vars={"CONDA_ENV": "base"})
    assert "CHOSEN_ENV='base'" in stdout
    assert 'BASE_CONSENT="false"' in stdout

    result, calls = _run_recipe_against_stub_conda(
        tmp_path, recipe, existing_envs=("base", "holon"), expect_success=False
    )

    assert "Refusing to write to 'base'" in result.stdout
    assert "is not consent" in result.stdout
    assert calls == []


def test_create_conda_env_inherited_allow_base_env_is_refused_without_installing(tmp_path):
    stdout, recipe = _create_conda_env_recipe(env_vars={"CONDA_ENV": "base", "CONDA_ALLOW_BASE": "1"})
    assert 'BASE_CONSENT="false"' in stdout

    result, calls = _run_recipe_against_stub_conda(
        tmp_path, recipe, existing_envs=("base", "holon"), expect_success=False
    )

    assert "Refusing to write to 'base'" in result.stdout
    assert calls == []


def test_create_conda_env_command_line_allow_base_arms_base_consent(tmp_path):
    stdout, recipe = _create_conda_env_recipe(make_vars={"CONDA_WRITE_ENV": "base", "CONDA_ALLOW_BASE": "1"})
    assert "CHOSEN_ENV='base'" in stdout
    assert 'BASE_CONSENT="true"' in stdout

    _, calls = _run_recipe_against_stub_conda(tmp_path, recipe, existing_envs=("base", "holon"))

    assert calls == ["install -y -n base -c conda-forge uv python=3.13"]


def test_create_conda_env_command_line_allow_base_zero_does_not_arm_consent(tmp_path):
    stdout, recipe = _create_conda_env_recipe(make_vars={"CONDA_WRITE_ENV": "base", "CONDA_ALLOW_BASE": "0"})
    assert 'BASE_CONSENT="false"' in stdout

    _, calls = _run_recipe_against_stub_conda(tmp_path, recipe, existing_envs=("base", "holon"), expect_success=False)

    assert calls == []


@requires_timed_read
def test_create_conda_env_tty_timeout_refuses_and_installs_nothing(tmp_path):
    stdout, recipe = _create_conda_env_recipe(
        make_vars={"CONDA_ALLOW_BASE": "1", "CONDA_PROMPT_TIMEOUT": "1"},
        env_vars={"CI": None, "NONINTERACTIVE": None},
    )
    assert "CHOSEN_ENV='holon'" in stdout
    assert 'BASE_CONSENT="true"' in stdout

    result, calls = _run_recipe_on_tty(tmp_path, recipe, existing_envs=("base", "holon"))

    assert result.returncode != 0
    assert "Enter target environment name" in result.stdout
    assert "No answer within 1 s" in result.stdout
    assert "nothing was installed" in result.stdout
    assert calls == []


@requires_timed_read
def test_create_conda_env_tty_prompt_honours_the_typed_environment_name(tmp_path):
    stdout, recipe = _create_conda_env_recipe(
        make_vars={"CONDA_PROMPT_TIMEOUT": "5"}, env_vars={"CI": None, "NONINTERACTIVE": None}
    )
    assert "CHOSEN_ENV='holon'" in stdout

    result, calls = _run_recipe_on_tty(tmp_path, recipe, keystrokes=b"custom_dev\n", existing_envs=("base", "holon"))

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == ["env list", "env create -n custom_dev -f environment.yml"]


@requires_timed_read
def test_create_conda_env_tty_typed_yes_grants_base_consent(tmp_path):
    stdout, recipe = _create_conda_env_recipe(
        make_vars={"CONDA_WRITE_ENV": "base", "CONDA_PROMPT_TIMEOUT": "5"},
        env_vars={"CI": None, "NONINTERACTIVE": None},
    )
    assert "CHOSEN_ENV='base'" in stdout
    assert 'BASE_CONSENT="false"' in stdout

    result, calls = _run_recipe_on_tty(tmp_path, recipe, keystrokes=b"\nyes\n", existing_envs=("base", "holon"))

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == ["install -y -n base -c conda-forge uv python=3.13"]


@requires_timed_read
def test_create_conda_env_tty_timeout_on_base_confirmation_refuses(tmp_path):
    stdout, recipe = _create_conda_env_recipe(
        make_vars={"CONDA_WRITE_ENV": "base", "CONDA_PROMPT_TIMEOUT": "1"},
        env_vars={"CI": None, "NONINTERACTIVE": None},
    )
    assert 'BASE_CONSENT="false"' in stdout

    result, calls = _run_recipe_on_tty(tmp_path, recipe, keystrokes=b"base\n", existing_envs=("base", "holon"))

    assert result.returncode != 0
    assert "Type 'yes' to install into it" in result.stdout
    assert "refusing to write to 'base'" in result.stdout
    assert "install -y -n base -c conda-forge uv python=3.13" in result.stdout
    assert calls == []


def test_create_conda_env_tty_run_never_writes_to_unconsented_base(tmp_path):
    stdout, recipe = _create_conda_env_recipe(
        make_vars={"CONDA_WRITE_ENV": "base", "CONDA_PROMPT_TIMEOUT": "1"},
        env_vars={"CI": None, "NONINTERACTIVE": None},
    )
    assert "CHOSEN_ENV='base'" in stdout
    assert 'BASE_CONSENT="false"' in stdout

    result, calls = _run_recipe_on_tty(tmp_path, recipe, existing_envs=("base", "holon"))

    assert result.returncode != 0
    assert not [call for call in calls if call.startswith("install")]
    assert calls == []


def test_config_mk_macros():
    result_conda = subprocess.run(
        ["make", "-f", "-", "test-find-conda"],
        input='include config/config.mk\ntest-find-conda:\n\t@$(FIND_CONDA_BIN); echo "EVAL_CONDA_BIN=$$CONDA_BIN"\n',
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=ENV_NO_COLOR,
        timeout=15,
    )
    assert result_conda.returncode == 0
    assert result_conda.stdout.strip().startswith("EVAL_CONDA_BIN=")
    conda_host = shutil.which("conda") or os.environ.get("CONDA_EXE")
    if conda_host and os.path.exists(conda_host):
        conda_bin_output = result_conda.stdout.strip().removeprefix("EVAL_CONDA_BIN=")
        assert conda_bin_output != ""
        assert os.path.exists(conda_bin_output)

    result_help = subprocess.run(
        ["make", "-f", "-", "test-help-format"],
        input="include config/config.mk\ntest-help-format:\n\t@printf $(HELP_FORMAT) 'target' 'description'\n",
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=ENV_NO_COLOR,
        timeout=15,
    )
    assert result_help.returncode == 0
    assert "target" in result_help.stdout
    assert "description" in result_help.stdout


def test_check_prerequisites_dry_run():
    result = subprocess.run(
        ["make", "-n", "check-prerequisites"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=ENV_NO_COLOR,
        timeout=15,
    )
    assert result.returncode == 0
    assert "check-docker AUTO_INSTALL=false" in result.stdout
    assert "Checking uv in Conda env" in result.stdout
    assert "Checking OpenSSL" in result.stdout
    assert "Checking npx (Prettier)" in result.stdout


def test_install_miniforge_checksum_dry_run():
    result = subprocess.run(
        ["make", "-n", "install-miniforge"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=ENV_NO_COLOR,
        timeout=15,
    )
    assert result.returncode == 0
    assert "EXPECTED_SHA=" in result.stdout
    assert "sha256sum" in result.stdout


def test_create_conda_env_prune_ignores_a_shell_exported_value(tmp_path):
    exported = _create_conda_env_dry_run(make_vars={"CONDA_ENV": "holon"}, env_vars={"CONDA_PRUNE": "1"}).stdout
    assert _emitted_prune_guard_is_enabled(exported) is False

    command_line = _create_conda_env_dry_run(make_vars={"CONDA_ENV": "holon", "CONDA_PRUNE": "1"}).stdout
    assert _emitted_prune_guard_is_enabled(command_line) is True


def test_create_conda_env_allow_base_does_not_bless_an_inherited_base_name(tmp_path):
    stdout, recipe = _create_conda_env_recipe(make_vars={"CONDA_ALLOW_BASE": "1"}, env_vars={"CONDA_ENV": "base"})
    assert "CHOSEN_ENV='base'" in stdout
    assert 'BASE_CONSENT="false"' in stdout

    result, calls = _run_recipe_against_stub_conda(
        tmp_path, recipe, existing_envs=("base", "holon"), expect_success=False
    )

    assert "Refusing to write to 'base'" in result.stdout
    assert calls == []


@pytest.mark.skipif(shutil.which("/bin/dash") is None, reason="dash is not available on this host")
def test_create_conda_env_explicit_name_is_honoured_under_dash(tmp_path):
    stdout, recipe = _create_conda_env_recipe(
        make_vars={"CONDA_ENV": "mydev"}, env_vars={"CI": None, "NONINTERACTIVE": None}
    )
    assert "CHOSEN_ENV='mydev'" in stdout

    result, calls = _run_recipe_on_tty(tmp_path, recipe, existing_envs=("base",), shell="/bin/dash")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "cannot time out" not in result.stdout
    assert any(call.startswith("env create") and "mydev" in call for call in calls), calls


@pytest.mark.parametrize("bad_name", ["-evil", "has space", "a;b"], ids=["leading-dash", "space", "semicolon"])
def test_create_conda_env_rejects_malformed_environment_names(tmp_path, bad_name):
    _stdout, recipe = _create_conda_env_recipe(make_vars={"CONDA_ENV": bad_name})

    result, calls = _run_recipe_against_stub_conda(
        tmp_path, recipe, existing_envs=("base", "holon"), expect_success=False
    )

    assert "Invalid environment name" in result.stdout
    assert calls == []


def test_create_conda_env_exported_name_is_data_not_shell_code(tmp_path):
    marker = tmp_path / "pwned"
    _stdout, recipe = _create_conda_env_recipe(env_vars={"CONDA_ENV": f"`touch {marker}`"})

    result, calls = _run_recipe_against_stub_conda(
        tmp_path, recipe, existing_envs=("base", "holon"), expect_success=False
    )

    assert not marker.exists(), "an exported CONDA_ENV was executed as shell code"
    assert "Invalid environment name" in result.stdout
    assert calls == []


def test_create_conda_env_rejects_a_non_numeric_prompt_timeout(tmp_path):
    _stdout, recipe = _create_conda_env_recipe(make_vars={"CONDA_PROMPT_TIMEOUT": "abc"})

    result, calls = _run_recipe_against_stub_conda(tmp_path, recipe, existing_envs=("holon",), expect_success=False)

    assert "CONDA_PROMPT_TIMEOUT must be a whole number" in result.stdout
    assert calls == []


def test_makefile_build_images_alias():
    result = subprocess.run(
        ["make", "-n", "build-images"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=ENV_NO_COLOR,
        timeout=15,
    )
    assert result.returncode == 0
    assert "build_image.sh" in result.stdout


def test_makefile_tools_inspection():
    result = subprocess.run(
        ["make", "-n", "tools"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=ENV_NO_COLOR,
        timeout=15,
    )
    assert result.returncode == 0
    assert "git jq shellcheck uv gh npx openssl" in result.stdout


def test_makefile_lint_and_check_targets():
    result_lint = subprocess.run(
        ["make", "-n", "lint"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=ENV_NO_COLOR,
        timeout=15,
    )
    assert result_lint.returncode == 0
    assert "prettier" in result_lint.stdout
    assert "pre_commit_check.py" in result_lint.stdout

    result_check = subprocess.run(
        ["make", "-n", "check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=ENV_NO_COLOR,
        timeout=15,
    )
    assert result_check.returncode == 0
    assert "prettier" in result_check.stdout


def test_makefile_pre_commit_check_target():
    result = subprocess.run(
        ["make", "-n", "pre-commit-check"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=ENV_NO_COLOR,
        timeout=15,
    )
    assert result.returncode == 0
    assert "pre_commit_check.py" in result.stdout
