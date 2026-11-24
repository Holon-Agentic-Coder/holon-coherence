from __future__ import annotations

import os
import subprocess
import sys

DOCKER_BUILD_TIMEOUT_SECONDS = 600
DOCKER_TAG_TIMEOUT_SECONDS = 30
GHCR_IMAGE_PREFIX = "ghcr.io/holon-agentic-coder"


def ensure_docker_image(image: str, rebuild: bool = False) -> None:  # noqa: C901, PLR0912
    if not rebuild:
        img_check = subprocess.run(
            ["docker", "image", "inspect", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if img_check.returncode == 0:
            return

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    dockerfile = os.path.join(repo_root, "Dockerfile")
    if os.path.exists(dockerfile):
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
