#!/bin/bash
# Builds and compiles a runnable application from source and cleans up any past compiles.
set -euo pipefail

app_dir="$(cd "$(dirname "$0")/.." && pwd)"
repo_dir="$(cd "$app_dir/.." && pwd)"
# Outside ~/Documents, whose file-provider sync adds extended attributes that codesign rejects.
build_dir="$HOME/Library/Developer/Xcode/DerivedData/InstagramPlus-scripts"
log_path="$repo_dir/engine/logs/app-build-$(date +%Y-%m-%d-%H%M%S).log"

runtime_interpreter="$repo_dir/Runtime/aarch64/python/bin/python3"
runtime_requirements="$repo_dir/Runtime/requirements.txt"
runtime_is_missing=false
lock_is_newer=false
[ -x "$runtime_interpreter" ] || runtime_is_missing=true
[ "$repo_dir/engine/uv.lock" -nt "$runtime_requirements" ] && lock_is_newer=true

if $runtime_is_missing || $lock_is_newer; then
   "$app_dir/scripts/build-runtime.command"
fi

rm -rf "$build_dir"
cd "$app_dir"

xcodegen generate --quiet

xcodebuild \
   -project InstagramPlus.xcodeproj \
   -scheme InstagramPlus \
   -configuration Debug \
   -destination "platform=macOS,arch=arm64" \
   -derivedDataPath "$build_dir" \
   build > "$log_path" 2>&1 || {
      grep -E "error:|BUILD FAILED" "$log_path" || tail -20 "$log_path"
      echo "build failed, log at $log_path"
      exit 1
   }

echo "built $build_dir/Build/Products/Debug/Instagram+.app"
echo "log at $log_path"
