from __future__ import annotations

import importlib.resources
import os
import subprocess
import sys
from pathlib import Path

DOCKER_BUILD_TIMEOUT_SECONDS = 600
DOCKER_TAG_TIMEOUT_SECONDS = 30
GHCR_IMAGE_PREFIX = "ghcr.io/holon-agentic-coder"


def resolve_build_context(start_path: str | os.PathLike[str] | None = None) -> tuple[str, str]:
    if start_path is not None:
        anchor = Path(start_path).resolve()
    else:
        try:
            pkg_root = importlib.resources.files("holon_coherence")
            anchor = Path(str(pkg_root)).resolve()
        except (ModuleNotFoundError, TypeError, OSError):
            anchor = Path(__file__).resolve()
    base = anchor if anchor.is_dir() else anchor.parent
    for candidate in (base, *base.parents):
        candidate_str = str(candidate)
        pyproject_path = os.path.join(candidate_str, "pyproject.toml")
        dockerfile_path = os.path.join(candidate_str, "Dockerfile")
        if os.path.exists(pyproject_path) and os.path.exists(dockerfile_path):
            return candidate_str, dockerfile_path
    raise FileNotFoundError(
        f"Could not locate repository root containing pyproject.toml and Dockerfile starting from {base}"
    )


def ensure_docker_image(image: str, rebuild: bool = False) -> None:  # noqa: C901, PLR0912
    if not rebuild:
        img_check = subprocess.run(
            ["docker", "image", "inspect", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if img_check.returncode == 0:
            return

    try:
        repo_root, dockerfile = resolve_build_context()
    except FileNotFoundError:
        repo_root, dockerfile = None, None
    if repo_root is not None and dockerfile is not None:
        print(f"🔨 Building Docker image '{image}' from {dockerfile}...")
        try:
            build_res = subprocess.run(
                ["docker", "build", "-t", image, repo_root],
                timeout=DOCKER_BUILD_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            print(
                f"Error: Docker build timed out after {DOCKER_BUILD_TIMEOUT_SECONDS}s. "
                "Check your Docker daemon or network connection.",
                file=sys.stderr,
            )
            sys.exit(1)
        if build_res.returncode != 0:
            print(f"Error: Failed to build Docker image '{image}'.", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"📥 Pulling Docker image '{image}'...")
        try:
            pull_res = subprocess.run(
                ["docker", "pull", image],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=DOCKER_BUILD_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            print(
                f"Error: Docker pull timed out after {DOCKER_BUILD_TIMEOUT_SECONDS}s.",
                file=sys.stderr,
            )
            sys.exit(1)
        if pull_res.returncode != 0:
            if "/" not in image:
                ghcr_img = f"{GHCR_IMAGE_PREFIX}/{image}"
                print(f"📥 Attempting pull from {ghcr_img}...")
                try:
                    ghcr_res = subprocess.run(
                        ["docker", "pull", ghcr_img],
                        timeout=DOCKER_BUILD_TIMEOUT_SECONDS,
                    )
                except subprocess.TimeoutExpired:
                    print(
                        f"Error: Docker pull from GHCR timed out after {DOCKER_BUILD_TIMEOUT_SECONDS}s.",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                if ghcr_res.returncode != 0:
                    print(
                        f"Error: Could not find or pull Docker image '{image}' or '{ghcr_img}'.\n"
                        "Please verify your network connection or build the image locally.",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                try:
                    tag_res = subprocess.run(
                        ["docker", "tag", ghcr_img, image],
                        timeout=DOCKER_TAG_TIMEOUT_SECONDS,
                    )
                except subprocess.TimeoutExpired:
                    print(
                        f"Error: Docker tag timed out after {DOCKER_TAG_TIMEOUT_SECONDS}s.",
                        file=sys.stderr,
                    )
                    sys.exit(1)
                if tag_res.returncode != 0:
                    print(f"Error: Failed to tag Docker image '{ghcr_img}' as '{image}'.", file=sys.stderr)
                    sys.exit(1)
            else:
                print(
                    f"Error: Could not find or pull Docker image '{image}'.\n"
                    "Please verify your network connection or build the image locally.",
                    file=sys.stderr,
                )
                sys.exit(1)
