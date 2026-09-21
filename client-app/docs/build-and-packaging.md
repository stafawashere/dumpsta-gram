# Build and packaging

App-side build concerns. The runtime construction, signing commands, and bundle layout
are canonical in
[../../docs/bridge/runtime-packaging.md](../../docs/bridge/runtime-packaging.md) and
are not repeated here.

## Build order

The Python runtime is a prerequisite of the app, not a product of it.

1. `engine/scripts/build_runtime.sh` downloads a relocatable CPython per architecture
   into `Runtime/<arch>/` and installs the locked dependencies into each one's
   `site-packages` using that architecture's own interpreter. Until the final Intel step,
   `<arch>` is `aarch64` and nothing else.
2. Xcode builds the Swift app. Universal from the Intel step onward, `arm64` only before it.
3. A run-script phase signs every `.so` and `.dylib` under `Runtime/` individually,
   across both architectures.
4. The app's own signing phase runs, with Developer ID and the hardened runtime.
5. Release builds copy `Runtime/` and `engine/src` into `Contents/Resources`.
6. Notarization and stapling.

Step 3 must precede step 4. Step 3 is slow in proportion to the dependency count, and it now
runs over two runtimes, which is a practical reason to keep the engine's dependency list lean.

There is no App Store submission and no sandbox entitlement. See
[../../docs/decisions/ADR-0010-distribution-targets.md](../../docs/decisions/ADR-0010-distribution-targets.md).

## Debug and release path resolution

This is the app-specific piece and it is the one most likely to be gotten wrong.

| Build | `Runtime/` | Engine source |
|---|---|---|
| Debug | Repository `Runtime/<arch>` | Repository `engine/src`, on `sys.path` live |
| Release | `Contents/Resources/Runtime/<arch>` | `Contents/Resources/engine/src` |

`<arch>` is the running slice's architecture, `aarch64` or `x86_64`. Resolve it from the first
build, while `aarch64` is still the only directory that exists, because retrofitting the
architecture level into path resolution after everything assumes one runtime is the expensive
version of adding Intel. Resolving it wrongly surfaces as an import failure at first PythonKit
use, never as a build failure.

The debug repository path comes from an injected build setting or a generated
`BuildPaths.swift` holding the absolute repository path. It must not be derived from
`#filePath` heuristics, because the debug binary has to find the sources wherever Xcode
places the product.

The payoff is that editing Python in a debug build requires no Xcode rebuild, which is
the difference between a fast and a miserable development loop.

## Failure modes to expect

| Symptom | Cause |
|---|---|
| Import failure at first PythonKit use | `Runtime/` missing or paths resolved wrong. Bootstrap should fail loudly with the resolved paths in the message. |
| Import failure for one specific package | Wheel architecture does not match the interpreter. Surfaces at runtime, never at build time. |
| Crash on launch after signing | A `.so` or `.dylib` left unsigned, or signed after the app rather than before. |
| Works locally, fails on another machine | A non-relocatable interpreter crept in, or `Runtime/` was not bundled. |
| A dependency imported from the user's own environment | `PYTHONNOUSERSITE` not set during bootstrap. |
| Works on Apple Silicon, fails on Intel or the reverse | The wrong `Runtime/<arch>` resolved, or one architecture's `site-packages` populated by the other architecture's interpreter. |

## Reproducibility

`engine/uv.lock` is the pin. It is committed. Without it, two builds of the same
commit can vendor different dependency versions against an already unstable upstream
API, which turns a dependency change into an indistinguishable cause when something
breaks. The build script exports a flat requirements file from the lock rather than
reading a hand-maintained one. See
[../../docs/decisions/ADR-0009-uv-toolchain-python-floor.md](../../docs/decisions/ADR-0009-uv-toolchain-python-floor.md).

`Runtime/` is a build product. It is gitignored and never committed. It is
reproducible from the build script plus the lock.

## Settled packaging decisions

Both former open questions were ruled on 2026-09-20 in
[../../docs/decisions/ADR-0010-distribution-targets.md](../../docs/decisions/ADR-0010-distribution-targets.md).

- **No App Store.** Developer ID plus notarization, no sandbox entitlement, arbitrary proxy
  configuration permissible.
- **Intel Macs are a target, and they are the last step.** Universal binary with one bundled
  runtime per architecture, built and verified only after the rest of Phase 5 is finished.
  Every build before that is `aarch64` only.
- **macOS only.** iOS is out of scope.

What is still unverified is Intel itself. No Intel Mac is known to be available here, so the
second slice may build, sign, and notarize and still fail at first import with nobody noticing.
ASSUMPTION until an Intel machine runs it. The app's minimum macOS version is bounded by the
x86_64 runtime's own deployment target, also ASSUMPTION until a build is made.
