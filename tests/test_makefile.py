import os
import pathlib
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.skipif(shutil.which("make") is None, reason="make is not installed on host")

REPO_ROOT = pathlib.Path(__file__).parent.parent
ENV_NO_COLOR = {**os.environ, "NO_COLOR": "1"}


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
    result = subprocess.run(
        ["make", "-n", "create-conda-env"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=ENV_NO_COLOR,
        timeout=15,
    )
    assert result.returncode == 0
    assert "$CONDA_BIN" in result.stdout
    assert "$CONDA_PATH" not in result.stdout
    assert "env create -n holon -f environment.yml" in result.stdout


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
