#!/bin/bash
# Runs the most recent build of the app.
set -euo pipefail

app_path="$HOME/Library/Developer/Xcode/DerivedData/InstagramPlus-scripts/Build/Products/Debug/Instagram+.app"

if [ ! -d "$app_path" ]; then
   echo "no build at $app_path, run build-app.command first"
   exit 1
fi

open "$app_path"
