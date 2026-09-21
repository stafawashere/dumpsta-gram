# The Swift and Python bridge

Canonical description of how Dumpsta-App reaches Dumpsta-Engine. Owned jointly by both
products, which is why it lives at the repository root rather than inside either one.

Decision and alternatives: [ADR-0002](../decisions/ADR-0002-embedded-python-pythonkit.md).
Concurrency rules: [threading-and-gil.md](threading-and-gil.md).
Shipping the runtime: [runtime-packaging.md](runtime-packaging.md).

## Model

Dumpsta-App embeds CPython in-process and drives Dumpsta-Engine through PythonKit.
There is no subprocess and no serialization protocol. Swift gets real
`PythonObject` values with keyword arguments, attribute access, iteration, and
exceptions.

Swift talks to the engine's `SyncClient` facade, never to `aio.AsyncClient`, because
Swift cannot await a Python coroutine. The facade internally crosses into the engine's
persistent asyncio loop thread. See
[ADR-0001](../decisions/ADR-0001-async-core-sync-facade.md).

```
Swift UI (MainActor)
   calls
Swift service layer (Python serial queue)
   calls
PythonKit
   calls
dumpstagram.SyncClient
   hands the coroutine to
the engine's persistent asyncio loop thread
   which runs
dumpstagram._core.AsyncClient
   which speaks HTTP to
Instagram
```

Two thread boundaries exist in that chain, and both are managed. Swift's serial queue
to the Python interpreter is one. The engine's facade to its own loop thread is the
other. Neither is the caller's problem if the rules in
[threading-and-gil.md](threading-and-gil.md) are followed.

## Repository layout the bridge expects

```
dumpsta-gram/
   client-app/
      src/Dumpstagram/
         PythonRuntime.swift
   engine/
      pyproject.toml
      dumpstagram/
      scripts/build_runtime.sh
   Runtime/                  generated, gitignored
      aarch64/
         python/             relocatable CPython
         site-packages/      uv pip install --target output
      x86_64/                same again, for the Intel slice
```

`Runtime/` is a build product. It is never committed.

## Bootstrap sequence

Order matters. Environment variables must be set before any PythonKit symbol is
touched, because the first access initializes the interpreter and it cannot be
reconfigured afterwards.

1. Resolve the runtime root, including the architecture directory for the running slice.
   Debug uses the repository `Runtime/<arch>`. Release uses `Bundle.main.resourceURL` plus
   `Runtime/<arch>`. The app is a universal binary carrying both. See
   [../decisions/ADR-0010-distribution-targets.md](../decisions/ADR-0010-distribution-targets.md).
2. Set `PYTHONHOME`, `PYTHONNOUSERSITE`, `PYTHON_LIBRARY`, and `PYTHONPATH`.
3. Touch PythonKit for the first time, which initializes the interpreter.
4. Insert the engine source path into `sys.path` if it is not already present.

```swift
import Foundation
import PythonKit

enum PythonRuntime {
   private static var isReady = false

   static func bootstrap() {
      guard !isReady else { return }

      let runtime = resolveRuntimeRoot()          // .../Runtime/aarch64 or .../Runtime/x86_64
      let home = runtime.appendingPathComponent("python")
      let dylib = home.appendingPathComponent("lib/libpython3.12.dylib")

      setenv("PYTHONHOME", home.path, 1)
      setenv("PYTHONNOUSERSITE", "1", 1)
      setenv("PYTHON_LIBRARY", dylib.path, 1)

      let searchPaths = [
         runtime.appendingPathComponent("site-packages").path,
         resolveEngineSource().path
      ]
      setenv("PYTHONPATH", searchPaths.joined(separator: ":"), 1)

      let sys = Python.import("sys")
      for path in searchPaths where !Array(sys.path).contains(PythonObject(path)) {
         sys.path.insert(0, path)
      }

      isReady = true
   }

   private static func resolveRuntimeRoot() -> URL {
      #if DEBUG
      return repositoryRoot().appendingPathComponent("Runtime")
      #else
      return Bundle.main.resourceURL!.appendingPathComponent("Runtime")
      #endif
   }

   private static func resolveEngineSource() -> URL {
      #if DEBUG
      return repositoryRoot().appendingPathComponent("engine")
      #else
      return Bundle.main.resourceURL!.appendingPathComponent("engine")
      #endif
   }
}
```

`PYTHONNOUSERSITE` is set so the user's own `~/.local` site-packages cannot leak into
the app and shadow a vendored dependency.

`repositoryRoot()` in debug builds comes from an injected build setting or a generated
`BuildPaths.swift` holding the absolute repository path. It must not be derived from
`#filePath` heuristics, because the debug binary needs to find the sources wherever
Xcode places the product.

## Calling the engine

```swift
PythonRuntime.bootstrap()

let dumpstagram = Python.import("dumpstagram")
let result = dumpstagram.process(input: "value", retries: 3)
let decoded = String(result) ?? ""
```

Keyword arguments, iteration, attribute access, and exceptions through
`Python.attemptImport` all work. That full-fidelity access is the whole point of
choosing in-process embedding.

## Development loop

`engine` is on `sys.path` directly in debug builds, so editing Python needs no
Xcode rebuild.

```swift
let importlib = Python.import("importlib")
importlib.reload(dumpstagram)
```

Reload works for pure-Python edits. It does not work for C extensions, and it does not
refresh references already held to functions or classes, so attributes must be
re-fetched after a reload. INFERENCE from CPython's documented reload semantics.

## Invariants

- Swift contains zero Instagram knowledge. No endpoints, no headers, no signing, no
  cursor formats. A need for any of those in Swift is a gap in the engine's public API.
- Swift never imports `dumpstagram._private` or `dumpstagram._core`.
- Values crossing into Swift are decoded into Swift types promptly. A `PythonObject`
  must not be stored in a view model or passed to the main actor. See
  [threading-and-gil.md](threading-and-gil.md).
- Bootstrap is idempotent and runs once per process.

## Failure behavior

- A Python segfault or a native-wheel abort terminates the whole app. This is the
  accepted cost of in-process embedding. The remedy for a specific bad dependency is
  to isolate that one call path in a subprocess, not to change the architecture.
- A missing or mismatched `Runtime/` surfaces at first PythonKit access, not at build
  time. The bootstrap should fail loudly with the resolved paths in the message.
- An architecture mismatch between the interpreter and a wheel surfaces as an import
  error at runtime.
