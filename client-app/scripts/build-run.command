#!/bin/bash
# Runs build-app.command then run-app.command.
set -euo pipefail

scripts_dir="$(cd "$(dirname "$0")" && pwd)"

"$scripts_dir/build-app.command"
"$scripts_dir/run-app.command"
