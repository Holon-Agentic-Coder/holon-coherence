# GitHub Actions Workflows

This directory contains the CI/CD workflows for the `holon-coherence` project.

## Workflows

- `make.yml`: Runs on pushes to `main` and pull requests across both `ubuntu-latest` and `macos-latest`. It verifies
  `uname -m`, `make help`, `make` (default target), tests that Conda is not present, installs Conda, installs the
  `holon` Conda environment from `environment.yml`, and verifies the environment and `uv` installation.
- `docker-build.yml`: Runs on pushes to `main` and pull requests on `ubuntu-latest`. It builds the Docker container via
  `make build-image` using Buildx Bake with multi-architecture caching and verifies image creation.
- `test-hygiene.yml`: Runs on pushes to `main` and pull requests on `ubuntu-latest`. It pulls out all repository hygiene
  into an isolated build: verifying dependencies with `uv sync`, ensuring `uv.lock` is up-to-date, running Ruff linting
  and formatting via `uv run task lint`, checking markdown formatting with Prettier, and validating cleanup via
  `uv run task clean`.
- `test-unit.yml`: Runs on pushes to `main` and pull requests for both `ubuntu-latest` and `macos-latest`. It executes
  unit tests (`uv run task test`) using the Conda environment.
- `test-integration.yml`: Runs on pushes to `main` and pull requests on `ubuntu-latest`. It builds the Docker image via
  `make build-image` and executes integration tests that require Docker services. For why Docker runs only on Ubuntu,
  see [macos-docker.md](../macos-docker.md).

## Key Configuration: Conda Package Resolution

During the setup of the CI, packages are resolved from the `conda-forge` channel via `environment.yml`.

### Conda Package Format (`use-only-tar-bz2: false`)

The `setup-miniconda` action includes:

```yaml
use-only-tar-bz2: false
```

This setting allows Conda to use both the `.conda` and `.tar.bz2` package formats from `conda-forge`. This ensures
modern packages like `uv` resolve quickly and reliably across both `ubuntu-latest` and `macos-latest`.
