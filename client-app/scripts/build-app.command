#!/bin/bash
# Builds and compiles a runnable application from source and cleans up any past compiles.
set -euo pipefail

app_dir="$(cd "$(dirname "$0")/.." && pwd)"
repo_dir="$(cd "$app_dir/.." && pwd)"
# Outside ~/Documents, whose file-provider sync adds extended attributes that codesign rejects.
build_dir="$HOME/Library/Developer/Xcode/DerivedData/InstagramPlus-scripts"
log_path="$repo_dir/engine/logs/app-build-$(date +%Y-%m-%d-%H%M%S).log"

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
