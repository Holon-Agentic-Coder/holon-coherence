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

# Candidate write targets exercised by the create-conda-env cases below.
CONDA_WRITE_TARGETS = ("holon", "custom_dev", "base")

# A stub `conda` that records one line per invocation and always exits 0. Tests run the
# emitted recipe with PATH and HOME pointing only at a temp dir, so this stub - never a
# real conda - is what the recipe resolves, even on a host with conda installed.
STUB_CONDA_SCRIPT = """#!/bin/sh
printf '%s\\n' "$*" >> "$CONDA_STUB_LOG"
if [ "$1" = "env" ] && [ "$2" = "list" ]; then
    if [ -f "$CONDA_STUB_ENV_LIST" ]; then
        cat "$CONDA_STUB_ENV_LIST"
    fi
fi
exit 0
"""

# A stub tool that succeeds and echoes its argv: stands in for docker, openssl, npx or uv
# so `check-prerequisites` can be executed for real against a fully controlled PATH.
STUB_TOOL_SCRIPT = """#!/bin/sh
printf '%s-stub\\n' "$*"
exit 0
"""

# The `CONDA_PRUNE` guard as make expands it; the compared literal is what make-time
# variable substitution produces, so it differs per CONDA_PRUNE value.
PRUNE_GUARD_RE = re.compile(r'CONDA_PRUNE_FLAG="";\s*if \[ "([^"]*)" = "1" \] \|\| \[ "([^"]*)" = "true" \]')


def _shell_supports_timed_read():
    """True when /bin/sh's `read` understands -t (bash, ksh and busybox ash do; dash does not).

    The probe feeds a complete line, because `read` also exits non-zero on an empty EOF in
    bash; only an unsupported `-t` option fails the pipeline. Mirrors the Makefile probe.
    """
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
    """Build a deterministic environment: no inherited conda activation, CI, or proxy state.

    A value of None removes the key. The tty tests need that, because make expands
    CI/NONINTERACTIVE into the emitted prompt condition, so capturing a recipe with the
    prompt branch live requires those variables to be absent from make's environment.
    """
    env = {
        "PATH": "/bin:/usr/bin:/usr/local/bin",
        "HOME": os.environ.get("HOME", "/"),
        "NO_COLOR": "1",
        # The create-conda-env prompt is skipped when CI=true, NONINTERACTIVE=1, or stdin
        # is not a tty; pin the first two so captured recipes are non-interactive text.
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
    """Rejoin make's dry-run output into the shell commands it would actually execute."""
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
    """Return (dry-run stdout, executable create-conda-env recipe) without prerequisite recipes."""
    result = _create_conda_env_dry_run(make_vars=make_vars, env_vars=env_vars)
    assert result.returncode == 0, result.stderr
    recipes = [command for command in _join_continuation_lines(result.stdout) if "CHOSEN_ENV=" in command]
    assert len(recipes) == 1, f"expected exactly one create-conda-env recipe, got {len(recipes)}"
    return result.stdout, recipes[0]


def _stub_conda_run_env(tmp_path, existing_envs=(), env_extra=None):
    """Build a run environment whose only conda is a recording stub inside tmp_path.

    PATH holds only the stub dir plus system bins, HOME points at tmp_path (so the
    $HOME/miniforge3 fallbacks cannot resolve), CONDA_EXE is the stub, and the stub is
    asserted to shadow any conda on the host before anything is allowed to run.
    """
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
    """Execute an emitted recipe against a stub conda confined to tmp_path (stdin not a tty).

    Returns the shell result plus the argv lines the stub recorded. CI=true and
    NONINTERACTIVE=1 are exported, so the interactive prompt is skipped and only the
    non-interactive guards decide what runs.
    """
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


def _run_recipe_on_tty(tmp_path, recipe, keystrokes=None, existing_envs=(), env_extra=None, timeout=30):
    """Execute an emitted recipe with stdin on a real pty, so the recipe's `[ -t 0 ]` is true.

    `keystrokes` are written to the pty master before the recipe runs; passing None leaves
    the terminal silent, which is how the prompt-timeout refusal is exercised. The
    subprocess timeout is the hang detector: an unbounded `read` fails this test rather
    than blocking forever, which is the I-C regression this guards against.
    """
    run_env, call_log = _stub_conda_run_env(tmp_path, existing_envs, env_extra)
    master, slave = pty.openpty()
    try:
        if keystrokes:
            os.write(master, keystrokes)
        result = subprocess.run(
            ["/bin/sh", "-c", recipe],
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


def _emitted_prune_guard_is_enabled(stdout):
    """Read the make-expanded CONDA_PRUNE guard: the branch make would take, not recipe text."""
    emitted = " ".join(_join_continuation_lines(stdout))
    match = PRUNE_GUARD_RE.search(emitted)
    assert match is not None, "CONDA_PRUNE guard missing from the emitted recipe"
    # `conda env update` must take the guarded shell variable, never a literal flag: a
    # hardcoded --prune would prune an environment this target did not create.
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
        "create-conda-env",
        "activate-conda-env",
    ],
)
def test_makefile_dry_run(target):
    result = subprocess.run(
        ["make", "-n", target], cwd=REPO_ROOT, capture_output=True, text=True, env=ENV_NO_COLOR, timeout=15
    )
    assert result.returncode == 0


def test_create_conda_env_dry_run():
    """The recipe must resolve conda through FIND_CONDA_BIN and arm the requested target.

    Only `CHOSEN_ENV="custom_dev"` is input-dependent here. The branch text (`env create
    ...`, `install -y -n base ...`) is echoed for every CONDA_ENV value, so asserting on it
    would be vacuous; branch exclusivity is pinned by
    `test_create_conda_env_dry_run_targets_only_the_requested_env` and by the stub-conda
    tests that execute the emitted recipe.
    """
    result = _create_conda_env_dry_run(make_vars={"CONDA_ENV": "custom_dev"})
    assert result.returncode == 0
    assert "$CONDA_BIN" in result.stdout
    assert 'CHOSEN_ENV="custom_dev"' in result.stdout


@pytest.mark.parametrize("env_name", CONDA_WRITE_TARGETS)
def test_create_conda_env_dry_run_targets_only_the_requested_env(env_name):
    """Pin which environment make arms as the write target.

    `create-conda-env` chooses its conda subcommand with a runtime shell `if`, so every
    branch's text (`install -y -n base ...`, `env create ...`, `env update ...`) appears in
    `make -n` output for every CONDA_ENV value; asserting on that text alone cannot fail.
    What make does expand - and therefore what is exclusive here - is the decision it bakes
    into the recipe: the `CHOSEN_ENV` and `BASE_CONSENT` literals and the CONDA_PRUNE guard.
    Which branch actually runs (env create vs env update vs install into base) is pinned by
    the stub-conda tests below, which execute the emitted recipe.
    """
    stdout = _create_conda_env_dry_run(make_vars={"CONDA_ENV": env_name}).stdout
    assert f'CHOSEN_ENV="{env_name}"' in stdout
    for other in CONDA_WRITE_TARGETS:
        if other != env_name:
            assert f'CHOSEN_ENV="{other}"' not in stdout
    expected_consent = "true" if env_name == "base" else "false"
    refused_consent = "false" if expected_consent == "true" else "true"
    assert f'BASE_CONSENT="{expected_consent}"' in stdout
    assert f'BASE_CONSENT="{refused_consent}"' not in stdout
    assert not _emitted_prune_guard_is_enabled(stdout)


def test_create_conda_env_dry_run_active_base_does_not_target_base():
    """An activated `base` is not consent: without an explicit request the write stays on holon."""
    stdout = _create_conda_env_dry_run(env_vars={"CONDA_DEFAULT_ENV": "base", "CONDA_PREFIX": "/tmp/fake/base"}).stdout
    assert 'CHOSEN_ENV="holon"' in stdout
    assert 'CHOSEN_ENV="base"' not in stdout
    assert 'BASE_CONSENT="false"' in stdout
    assert 'BASE_CONSENT="true"' not in stdout


@pytest.mark.parametrize(
    "prompt_timeout,expected_literal",
    [(None, 'PROMPT_TIMEOUT="20"'), ("3", 'PROMPT_TIMEOUT="3"'), ("1", 'PROMPT_TIMEOUT="1"')],
)
def test_create_conda_env_dry_run_bounds_the_prompt_by_read_timeout(prompt_timeout, expected_literal):
    """The prompt must be offered through `read -t`, bounded by CONDA_PROMPT_TIMEOUT.

    Without `-t` a pty-backed automation run blocks forever, because the prompt is offered
    precisely when stdin is a terminal. Removing `-t "$$PROMPT_TIMEOUT"` from the recipe
    fails the literal assertion below; the behaviour is pinned by
    `test_create_conda_env_tty_timeout_refuses_and_installs_nothing`.
    """
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
    """Run the emitted recipe non-interactively: a bare run provisions holon, never base."""
    stdout, recipe = _create_conda_env_recipe()
    assert 'CHOSEN_ENV="holon"' in stdout

    result, calls = _run_recipe_against_stub_conda(tmp_path, recipe, existing_envs=("base", "holon"))

    assert "Setting up Conda environment 'holon'" in result.stdout
    assert "Enter target environment name" not in result.stdout
    assert "env update -n holon -f environment.yml" in calls
    assert not [call for call in calls if call.startswith("install")]
    assert not [call for call in calls if re.search(r"-n\s+base(\s|$)", call)]
    assert not [call for call in calls if call.startswith("env create")]


def test_create_conda_env_non_interactive_active_base_never_writes_to_base(tmp_path):
    """With `base` activated but not requested, the emitted recipe must not install into base."""
    stdout, recipe = _create_conda_env_recipe(env_vars={"CONDA_DEFAULT_ENV": "base"})
    assert 'CHOSEN_ENV="holon"' in stdout
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
    """An explicit CONDA_ENV=base is the only non-interactive route that writes to base."""
    stdout, recipe = _create_conda_env_recipe(make_vars={"CONDA_ENV": "base"})
    assert 'CHOSEN_ENV="base"' in stdout
    assert 'BASE_CONSENT="true"' in stdout

    _, calls = _run_recipe_against_stub_conda(tmp_path, recipe, existing_envs=("base", "holon"))

    # Exact call list: the base route must not also create or update an environment.
    assert calls == ["install -y -n base -c conda-forge uv python=3.13"]


def test_create_conda_env_non_interactive_new_env_uses_env_create(tmp_path):
    """A custom environment that does not exist goes through `conda env create`, never base."""
    stdout, recipe = _create_conda_env_recipe(make_vars={"CONDA_ENV": "custom_dev"})
    assert 'CHOSEN_ENV="custom_dev"' in stdout

    _, calls = _run_recipe_against_stub_conda(tmp_path, recipe, existing_envs=("base", "holon"))

    assert calls == ["env list", "env create -n custom_dev -f environment.yml"]
    assert not [call for call in calls if call.startswith("install")]


@pytest.mark.parametrize(
    "prune_value,prune_expected",
    [(None, False), ("false", False), ("1", True), ("true", True)],
)
def test_create_conda_env_non_interactive_prune_tracks_conda_prune(tmp_path, prune_value, prune_expected):
    """`--prune` reaches the stub only when CONDA_PRUNE asks for it."""
    make_vars = {"CONDA_ENV": "holon"}
    if prune_value is not None:
        make_vars["CONDA_PRUNE"] = prune_value
    _, recipe = _create_conda_env_recipe(make_vars=make_vars)

    _, calls = _run_recipe_against_stub_conda(tmp_path, recipe, existing_envs=("holon",))

    updates = [call for call in calls if call.startswith("env update")]
    assert len(updates) == 1
    assert ("--prune" in updates[0]) is prune_expected


def test_create_conda_env_inherited_base_env_is_refused_without_installing(tmp_path):
    """An inherited `CONDA_ENV=base` is not consent: refuse, explain, and run no conda.

    This is the last-line-of-defence guard: deleting the `BASE_CONSENT != true` branch lets
    the recipe reach `conda install -y -n base`, which this test sees in the stub log.
    """
    stdout, recipe = _create_conda_env_recipe(env_vars={"CONDA_ENV": "base"})
    assert 'CHOSEN_ENV="base"' in stdout
    assert 'BASE_CONSENT="false"' in stdout

    result, calls = _run_recipe_against_stub_conda(
        tmp_path, recipe, existing_envs=("base", "holon"), expect_success=False
    )

    assert "Refusing to write to 'base'" in result.stdout
    assert "is not consent" in result.stdout
    assert calls == []


def test_create_conda_env_inherited_allow_base_env_is_refused_without_installing(tmp_path):
    """`export CONDA_ALLOW_BASE=1` is inherited state too, so it must not arm consent."""
    stdout, recipe = _create_conda_env_recipe(env_vars={"CONDA_ENV": "base", "CONDA_ALLOW_BASE": "1"})
    assert 'BASE_CONSENT="false"' in stdout

    result, calls = _run_recipe_against_stub_conda(
        tmp_path, recipe, existing_envs=("base", "holon"), expect_success=False
    )

    assert "Refusing to write to 'base'" in result.stdout
    assert calls == []


def test_create_conda_env_command_line_allow_base_arms_base_consent(tmp_path):
    """`CONDA_ALLOW_BASE=1` passed to make IS the deliberate act, so the write may proceed."""
    stdout, recipe = _create_conda_env_recipe(make_vars={"CONDA_WRITE_ENV": "base", "CONDA_ALLOW_BASE": "1"})
    assert 'CHOSEN_ENV="base"' in stdout
    assert 'BASE_CONSENT="true"' in stdout

    _, calls = _run_recipe_against_stub_conda(tmp_path, recipe, existing_envs=("base", "holon"))

    assert calls == ["install -y -n base -c conda-forge uv python=3.13"]


def test_create_conda_env_command_line_allow_base_zero_does_not_arm_consent(tmp_path):
    """`CONDA_ALLOW_BASE=0` is a command-line act that declines consent, so it must refuse."""
    stdout, recipe = _create_conda_env_recipe(make_vars={"CONDA_WRITE_ENV": "base", "CONDA_ALLOW_BASE": "0"})
    assert 'BASE_CONSENT="false"' in stdout

    _, calls = _run_recipe_against_stub_conda(tmp_path, recipe, existing_envs=("base", "holon"), expect_success=False)

    assert calls == []


@requires_timed_read
def test_create_conda_env_tty_timeout_refuses_and_installs_nothing(tmp_path):
    """A pty run that never answers must time out as a refusal, never as an implicit yes.

    Consent is armed here (CONDA_ENV=base on the command line), so an unbounded `read`
    hangs and hits the subprocess timeout, and a timeout treated as "yes" would record
    `install -y -n base ...` in the stub log. Both regressions fail this test.
    """
    stdout, recipe = _create_conda_env_recipe(
        make_vars={"CONDA_ENV": "base", "CONDA_PROMPT_TIMEOUT": "1"},
        env_vars={"CI": None, "NONINTERACTIVE": None},
    )
    assert 'CHOSEN_ENV="base"' in stdout
    assert 'BASE_CONSENT="true"' in stdout

    result, calls = _run_recipe_on_tty(tmp_path, recipe, existing_envs=("base", "holon"))

    assert result.returncode != 0
    assert "Enter target environment name" in result.stdout
    assert "No answer within 1 s" in result.stdout
    assert "nothing was installed" in result.stdout
    assert calls == []


@requires_timed_read
def test_create_conda_env_tty_prompt_honours_the_typed_environment_name(tmp_path):
    """Deleting or short-circuiting the prompt makes this fail: the typed name never lands."""
    stdout, recipe = _create_conda_env_recipe(
        make_vars={"CONDA_PROMPT_TIMEOUT": "5"}, env_vars={"CI": None, "NONINTERACTIVE": None}
    )
    assert 'CHOSEN_ENV="holon"' in stdout

    result, calls = _run_recipe_on_tty(tmp_path, recipe, keystrokes=b"custom_dev\n", existing_envs=("base", "holon"))

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == ["env list", "env create -n custom_dev -f environment.yml"]


@requires_timed_read
def test_create_conda_env_tty_typed_yes_grants_base_consent(tmp_path):
    """Without make-time consent, a typed `yes` at the prompt is what unlocks the base write."""
    stdout, recipe = _create_conda_env_recipe(
        make_vars={"CONDA_WRITE_ENV": "base", "CONDA_PROMPT_TIMEOUT": "5"},
        env_vars={"CI": None, "NONINTERACTIVE": None},
    )
    assert 'CHOSEN_ENV="base"' in stdout
    assert 'BASE_CONSENT="false"' in stdout

    result, calls = _run_recipe_on_tty(tmp_path, recipe, keystrokes=b"\nyes\n", existing_envs=("base", "holon"))

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls == ["install -y -n base -c conda-forge uv python=3.13"]


@requires_timed_read
def test_create_conda_env_tty_timeout_on_base_confirmation_refuses(tmp_path):
    """Silence at the 'type yes' confirmation is a refusal, and prints the base command."""
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
    """Runs on every shell: a tty run must never install into an unconsented `base`.

    On a shell with `read -t` the silent terminal times out and the prompt refuses; on a
    shell without it (dash) the prompt is skipped by design and the runtime consent guard
    refuses. Either way the stub must record zero conda invocations.
    """
    stdout, recipe = _create_conda_env_recipe(
        make_vars={"CONDA_WRITE_ENV": "base", "CONDA_PROMPT_TIMEOUT": "1"},
        env_vars={"CI": None, "NONINTERACTIVE": None},
    )
    assert 'CHOSEN_ENV="base"' in stdout
    assert 'BASE_CONSENT="false"' in stdout

    result, calls = _run_recipe_on_tty(tmp_path, recipe, existing_envs=("base", "holon"))

    assert result.returncode != 0
    assert not [call for call in calls if call.startswith("install")]
    assert calls == []


def test_config_mk_macros():
    # Verify FIND_CONDA_BIN macro sets CONDA_BIN shell variable
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

    # Verify HELP_FORMAT macro formats output correctly
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


# Tools the prerequisite probe needs from the system, exposed through a private dir so the
# executed probe sees a PATH without openssl/npx/uv unless the test stubs them explicitly.
PREREQUISITES_SYSTEM_TOOLS = ("awk", "grep", "make", "printf", "sed", "sleep", "tr", "uname")


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


def _prerequisites_run_env(tmp_path, *, path_tools=(), uv_prefix="default", env_list_line=None):
    """Stub-only environment for executing `make check-prerequisites` for real.

    `path_tools` names which stand-in tools (docker, openssl, npx, uv) exist on PATH; a
    `uv_prefix` gets `bin/uv` inside that conda env prefix; `env_list_line` overrides the
    stub's `conda env list` output. PATH carries only these stubs plus an allowlist of
    system tools, so a tool the test does not stub is genuinely absent from the probe - no
    host openssl, npx or uv can quietly green-light a check. Everything lives in tmp_path,
    so nothing reaches a real conda or the host's package set.
    """
    run_env, _ = _stub_conda_run_env(tmp_path, existing_envs=("holon",))
    bin_dir = tmp_path / "bin"
    system_dir = _link_prerequisite_system_tools(bin_dir)
    run_env["PATH"] = os.pathsep.join([str(bin_dir), str(system_dir), "/bin"])
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
    return run_env


def _run_check_prerequisites(tmp_path, **kwargs):
    """Execute the real `make check-prerequisites` target (a read-only probe) with stubs.

    The target runs with AUTO_INSTALL=false, so it only probes: nothing here installs
    software or touches the host's conda environments.
    """
    run_env = _prerequisites_run_env(tmp_path, **kwargs)
    return subprocess.run(
        ["make", "check-prerequisites"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=run_env,
        timeout=120,
    )


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
    """npx is documentation hygiene only: its absence warns and must still exit 0."""
    result = _run_check_prerequisites(tmp_path, path_tools=("docker", "openssl"), uv_prefix=tmp_path / "envs" / "holon")
    assert result.returncode == 0, result.stdout
    assert "Missing: npx not found" in result.stdout
    assert "optional/advisory check(s) raised warnings" in result.stdout
    assert "All prerequisites are satisfied" not in result.stdout


def test_check_prerequisites_uv_on_path_only_warns_instead_of_failing(tmp_path):
    """A PATH uv must not green-light an env that has none, and must not fail the check."""
    result = _run_check_prerequisites(tmp_path, path_tools=("docker", "openssl", "npx", "uv"), uv_prefix=None)
    assert result.returncode == 0, result.stdout
    assert "Found on PATH only" in result.stdout
    assert "uv is NOT installed in conda env 'holon'" in result.stdout


def test_check_prerequisites_hard_failure_outweighs_advisory_warnings(tmp_path):
    """A missing openssl next to a missing npx must exit non-zero, not hide behind WARNINGS."""
    result = _run_check_prerequisites(tmp_path, path_tools=("docker",), uv_prefix=tmp_path / "envs" / "holon")
    assert result.returncode != 0
    assert "Missing: openssl not found" in result.stdout
    assert "Missing: npx not found" in result.stdout


def test_check_prerequisites_accepts_an_env_prefix_containing_whitespace(tmp_path):
    """A conda prefix with spaces must resolve, not truncate into a false 'Missing: uv'."""
    prefix = tmp_path / "envs" / "my dev env"
    result = _run_check_prerequisites(
        tmp_path,
        path_tools=("docker", "openssl", "npx"),
        uv_prefix=prefix,
        env_list_line=f"holon {prefix}\n",
    )
    assert result.returncode == 0, result.stdout
    assert "uv inside conda env holon" in result.stdout


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
