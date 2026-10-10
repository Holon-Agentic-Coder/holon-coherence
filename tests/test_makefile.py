import os
import pathlib
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

# The `CONDA_PRUNE` guard as make expands it; the compared literal is what make-time
# variable substitution produces, so it differs per CONDA_PRUNE value.
PRUNE_GUARD_RE = re.compile(r'CONDA_PRUNE_FLAG="";\s*if \[ "([^"]*)" = "1" \] \|\| \[ "([^"]*)" = "true" \]')


def _minimal_env(**overrides):
    """Build a deterministic environment: no inherited conda activation, CI, or proxy state."""
    env = {
        "PATH": "/bin:/usr/bin:/usr/local/bin",
        "HOME": os.environ.get("HOME", "/"),
        "NO_COLOR": "1",
        # The create-conda-env prompt is skipped when CI=true, NONINTERACTIVE=1, or stdin
        # is not a tty; pin the first two so captured recipes are non-interactive text.
        "CI": "true",
        "NONINTERACTIVE": "1",
    }
    env.update({key: value for key, value in overrides.items() if value is not None})
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


def _run_recipe_against_stub_conda(tmp_path, recipe, existing_envs=(), env_extra=None):
    """Execute an emitted recipe against a stub conda confined to tmp_path.

    Returns the shell result plus the argv lines the stub recorded. Nothing here can reach
    a real conda: PATH holds only the stub dir plus system bins, HOME points at tmp_path
    (so the $HOME/miniforge3 fallbacks cannot resolve), CONDA_EXE is the stub, and stdin is
    not a tty while CI=true and NONINTERACTIVE=1 are exported.
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

    result = subprocess.run(
        ["/bin/sh", "-c", recipe],
        capture_output=True,
        text=True,
        env=run_env,
        stdin=subprocess.DEVNULL,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result, [line for line in call_log.read_text().splitlines() if line.strip()]


def _emitted_prune_guard_is_enabled(stdout):
    """Read the make-expanded CONDA_PRUNE guard: the branch make would take, not recipe text."""
    match = PRUNE_GUARD_RE.search(" ".join(_join_continuation_lines(stdout)))
    assert match is not None, "CONDA_PRUNE guard missing from the emitted recipe"
    assert match.group(1) == match.group(2)
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


@pytest.mark.parametrize(
    "env_name,expected_in_output",
    [
        ("holon", 'env create -n "$CHOSEN_ENV" -f environment.yml'),
        ("custom_dev", 'CHOSEN_ENV="custom_dev"'),
        ("base", "install -y -n base -c conda-forge uv python=3.13"),
    ],
)
def test_create_conda_env_dry_run(env_name, expected_in_output):
    env_vars = {**ENV_NO_COLOR, "CONDA_ENV": env_name}
    result = subprocess.run(
        ["make", "-n", "create-conda-env"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env_vars,
        timeout=15,
    )
    assert result.returncode == 0
    assert "$CONDA_BIN" in result.stdout
    assert expected_in_output in result.stdout


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
