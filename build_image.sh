#!/usr/bin/env bash
set -euo pipefail

# Resolve script directory and repository root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR"

show_help() {
  cat <<EOF
Usage: $(basename "$0") [options]

Builds the holon-coherence Docker image using Docker Buildx Bake.

Options:
  -h, --help      Show this help message and exit
  --no-cache      Build Docker images without using the cache
  --output-log    Print all build logs to stdout with timestamps prepended
  --push          Push the image to the remote container registry
EOF
}

NO_CACHE_FLAG=""
OUTPUT_LOG="false"
PUSH_FLAG="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      show_help
      exit 0
      ;;
    --no-cache)
      NO_CACHE_FLAG="--no-cache"
      shift
      ;;
    --output-log)
      OUTPUT_LOG="true"
      shift
      ;;
    --push)
      PUSH_FLAG="true"
      shift
      ;;
    *)
      echo "Unknown option: $1"
      show_help
      exit 1
      ;;
  esac
done

get_timestamp() {
  local -n ref=$1
  if [[ -n "${EPOCHREALTIME:-}" ]]; then
    local epoch="$EPOCHREALTIME"
    local sec="${epoch%.*}"
    local usec="${epoch#*.}"
    printf -v ref "%(%Y-%m-%d %H:%M:%S)T.%03d" "$sec" "$((10#${usec:0:3}))"
  else
    printf -v ref "%(%Y-%m-%d %H:%M:%S)T" -1
  fi
}

print_log_with_timestamps() {
  local ts
  while IFS= read -r line || [[ -n "$line" ]]; do
    get_timestamp ts
    printf "[%s] %s\n" "$ts" "$line"
  done
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  echo "Starting Docker Buildx Bake build for holon-coherence..."

  BAKE_ARGS=("-f" "$REPO_ROOT/docker-bake.hcl")

  if [[ "$PUSH_FLAG" == "true" ]]; then
    BAKE_ARGS+=("--push")
  else
    BAKE_ARGS+=("--load")
  fi

  if [[ -n "$NO_CACHE_FLAG" ]]; then
    BAKE_ARGS+=("--no-cache")
  fi

  cd "$REPO_ROOT"

  if [[ "$OUTPUT_LOG" == "true" ]]; then
    if ! docker buildx bake "${BAKE_ARGS[@]}" 2>&1 | print_log_with_timestamps; then
      echo "ERROR: Docker Buildx Bake failed!"
      exit 1
    fi
  else
    if ! docker buildx bake "${BAKE_ARGS[@]}"; then
      echo "ERROR: Docker Buildx Bake failed!"
      exit 1
    fi
  fi

  echo "holon-coherence Docker image built successfully!"
fi
