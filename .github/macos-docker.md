`macos-latest` runners do not support nested virtualization; therefore, Docker cannot be executed directly in macOS
runners (Docker Desktop, Colima, and Podman all require hypervisor VM virtualization). While GitHub Actions does not yet
support nested virtualization on macOS runners, refer to the following tracking discussions:

- https://github.com/orgs/community/discussions/160591
- https://github.com/actions/runner-images/blob/main/images/macos/macos-15-arm64-Readme.md
- https://github.com/actions/runner-images/issues/12933
