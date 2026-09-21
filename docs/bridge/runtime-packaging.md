# Packaging the Python runtime

How a relocatable CPython plus vendored dependencies gets built, bundled, and signed
inside Dumpsta-App.

Context: [ADR-0002](../decisions/ADR-0002-embedded-python-pythonkit.md),
[overview.md](overview.md).

## Why not the system interpreter

`/usr/local/bin/python3` on this machine is Python 3.11.0 (FACT, verified
2026-09-20). It is below the project's 3.12 floor, and neither it nor a Homebrew
interpreter is relocatable. Both break as soon as the `.app` is copied to another
machine, because paths compiled into the install no longer resolve.

The bundled runtime comes from python-build-standalone, which produces a relocatable
install intended exactly for embedding. uv's managed interpreters are
python-build-standalone builds, so the development interpreter and the shipped one
come from the same source. See
[../decisions/ADR-0009-uv-toolchain-python-floor.md](../decisions/ADR-0009-uv-toolchain-python-floor.md).

Development uses `uv run`, never the system interpreter. This section is about
distribution, which needs the interpreter physically inside the bundle.

## Two architectures, two runtimes, one of them last

Intel Macs are a target and the app ships as a universal binary, **but the Intel slice is built
last**, after everything else in Phase 5 is finished. Until that step, `ARCHES` below holds
`aarch64` alone and the bundle carries one runtime. See
[../decisions/ADR-0010-distribution-targets.md](../decisions/ADR-0010-distribution-targets.md).

The per-architecture directory layout and the loop exist from the first build anyway. That is
the cheap half. Retrofitting `Runtime/<arch>/` into the bootstrap, the signing phase, and the
bundle copy after they were all written for one architecture is the expensive half, and it is
what deferring Intel would otherwise cost.

python-build-standalone publishes `aarch64-apple-darwin` and `x86_64-apple-darwin` separately
and there is no universal build to download, so the bundle carries one complete runtime per
architecture under `Runtime/<arch>/`. Each one gets its dependencies installed by its own
interpreter, because a wheel holding a compiled extension is not portable across slices.

A mismatch between a wheel and the interpreter loading it surfaces as an import failure at
runtime, never as a build failure, which makes it an easy bug to ship and a hard one to notice.

Rosetta is not a fallback. Each slice loads the runtime for its own architecture.

## Build script shape

`engine/scripts/build_runtime.sh`, illustrative rather than verified. ASSUMPTION, no
bundle has been built here.

```bash
#!/usr/bin/env bash
set -euo pipefail

RUNTIME="${PROJECT_ROOT:?}/Runtime"
VERSION="3.12"

# Intel is the last step of the project. Until then this holds aarch64 alone.
ARCHES=(aarch64)

rm -rf "$RUNTIME"
mkdir -p "$RUNTIME"

uv export --project "${PROJECT_ROOT}/engine" --no-dev --no-emit-project \
   --format requirements-txt -o "$RUNTIME/requirements.txt"

for ARCH in "${ARCHES[@]}"; do
   TARGET="$RUNTIME/$ARCH"
   mkdir -p "$TARGET"

   uv python install --managed-python "cpython-${VERSION}-macos-${ARCH}-none"
   INTERPRETER="$(uv python find --managed-python "cpython-${VERSION}-macos-${ARCH}-none")"
   cp -R "$(dirname "$(dirname "$INTERPRETER")")" "$TARGET/python"

   uv pip install \
      --python "$TARGET/python/bin/python3" \
      --target "$TARGET/site-packages" \
      -r "$RUNTIME/requirements.txt"
done
```

Four properties of this script matter more than its details.

- The interpreter is a **uv-managed python-build-standalone** build, which is relocatable
  by construction. Whether a copy of one codesigns and relocates cleanly inside a signed
  `.app` is ASSUMPTION until a bundle is actually built.
- Dependencies are resolved from `engine/uv.lock`, not from a hand-maintained list. The
  exported requirements file is a build product written into `Runtime/`, and it is never
  committed. Both architectures install from that one export, which is what keeps the two
  trees in step.
- `uv pip install --python` targets the **shipped** interpreter for that architecture, so the
  wheels match it. Installing once and copying the result into the other architecture is a
  defect.
- `--target` keeps dependencies in a flat directory that the bootstrap puts on
  `PYTHONPATH`, rather than inside the interpreter's own `site-packages`. This keeps
  the interpreter tree and the dependency tree separately replaceable.

FACT, checked 2026-09-20 on this machine: `uv python list --all-versions
cpython-3.12-macos-x86_64-none` lists `cpython-3.12.13-macos-x86_64-none` as available for
download, so the request string above resolves. Nothing was downloaded and nothing was built.
Note that a plain `uv python list` hides non-native builds, which makes them look missing.

The cross-architecture install is the part most likely to misbehave in practice, since it
installs wheels for a platform the build machine is not, and uv inspects an interpreter by
running it. If uv refuses or resolves the wrong
wheels, the fallback is to build each runtime on its own hardware or to pass explicit platform
arguments. UNRESOLVED until attempted.

## Deployment target

The app's minimum macOS version is bounded by whatever the `x86_64` python-build-standalone
build targets, rather than by anything in this project. A runtime that will not load makes the
app useless on that system, so the app's deployment target follows the runtime's. ASSUMPTION
until a build is made.

## Codesigning

Every `.so` and `.dylib` under `Runtime/` must be signed individually with the team
identity before the app itself is signed. `codesign --deep` is unreliable for this
and should not be relied on.

Run-script build phase:

```bash
find "$RUNTIME" \( -name "*.so" -o -name "*.dylib" \) -print0 \
   | xargs -0 -n1 codesign --force --timestamp --options runtime --sign "$EXPANDED_CODE_SIGN_IDENTITY"
```

This phase runs before the app's own signing phase. It is slow in proportion to the
dependency count, which is a practical reason to keep the dependency list lean.

## Hardened runtime

Some packages require `com.apple.security.cs.allow-unsigned-executable-memory`, and
some require JIT-related entitlements. Add an entitlement only in response to an
observed crash, never preemptively, because each one weakens the app's security
posture.

## Distribution, outside the App Store

Ruled 2026-09-20. No App Store submission. Developer ID Application signing, hardened runtime,
notarization, and stapling on every release. See
[../decisions/ADR-0010-distribution-targets.md](../decisions/ADR-0010-distribution-targets.md).

- No sandbox entitlement is required, so arbitrary proxy configuration stays permissible and
  file access is not constrained to a container.
- Hardened runtime is still required for notarization, so the entitlement discipline above
  still applies. Add one only in response to an observed crash.
- Dependencies are still vendored at build time. Installing packages into the bundle at runtime
  was never acceptable and is not made acceptable by leaving the App Store.

## Bundle layout, release

```
Dumpstagram.app/
   Contents/
      MacOS/Dumpstagram          universal binary
      Resources/
         Runtime/
            aarch64/
               python/
               site-packages/
            x86_64/
               python/
               site-packages/
         engine/dumpstagram/
```

`PythonRuntime.bootstrap()` resolves `Runtime/<arch>` for the running slice before it touches a
PythonKit symbol. See [overview.md](overview.md).

Debug builds resolve both `Runtime/` and `engine` to their repository locations
instead, so Python edits take effect without an Xcode rebuild. See
[overview.md](overview.md).

## Gitignore expectations

`Runtime/` is a build product and is never committed. Its size makes committing it
impractical, and its contents are reproducible from the build script plus the lock.

`engine/uv.lock` is committed and is what makes the runtime reproducible. Without it,
two builds of the same commit can ship different dependency versions against an
already unstable upstream API. The exported requirements file inside `Runtime/` is
generated on every build and is not a source of truth.
