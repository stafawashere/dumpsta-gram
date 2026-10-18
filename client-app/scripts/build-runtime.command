#!/bin/bash
# Installs the embedded Python runtime the app loads, at <repository>/Runtime/<arch>, following
# docs/bridge/runtime-packaging.md. The interpreter is a uv-managed python-build-standalone build
# and the dependencies come from engine/uv.lock, installed by that same interpreter. The engine
# itself is not installed here, because debug builds put engine/ on sys.path directly.
set -euo pipefail

app_dir="$(cd "$(dirname "$0")/.." && pwd)"
repo_dir="$(cd "$app_dir/.." && pwd)"
runtime_dir="$repo_dir/Runtime"
python_version="$(tr -d '[:space:]' < "$repo_dir/engine/.python-version")"
log_path="$repo_dir/engine/logs/runtime-build-$(date +%Y-%m-%d-%H%M%S).log"

# Intel is the last step of the project (ADR-0010). Until then this holds aarch64 alone.
arches=(aarch64)

mkdir -p "$repo_dir/engine/logs"

{
   echo "runtime build started $(date -u +%Y-%m-%dT%H:%M:%SZ)"
   echo "python request cpython-$python_version"

   rm -rf "$runtime_dir"
   mkdir -p "$runtime_dir"

   uv export \
      --project "$repo_dir/engine" \
      --frozen \
      --no-dev \
      --no-emit-project \
      --no-hashes \
      --format requirements-txt \
      -o "$runtime_dir/requirements.txt"

   for arch in "${arches[@]}"; do
      interpreter_request="cpython-$python_version-macos-$arch-none"
      target_dir="$runtime_dir/$arch"
      mkdir -p "$target_dir"

      uv python install --managed-python "$interpreter_request"
      interpreter_path="$(uv python find --managed-python "$interpreter_request")"
      # uv keeps a minor-version symlink beside each install. Copying the link instead of the
      # tree would leave the runtime pointing back into ~/.local.
      interpreter_home="$(cd -P "$(dirname "$interpreter_path")/.." && pwd)"
      echo "$arch interpreter $interpreter_home"

      ditto "$interpreter_home" "$target_dir/python"

      uv pip install \
         --python "$target_dir/python/bin/python3" \
         --target "$target_dir/site-packages" \
         -r "$runtime_dir/requirements.txt"

      "$target_dir/python/bin/python3" -c "import sys; print('$arch runtime', sys.version.split()[0], sys.platform)"
   done

   echo "runtime build finished $(date -u +%Y-%m-%dT%H:%M:%SZ)"
} 2>&1 | tee "$log_path"

echo "log at $log_path"
