# Threading, the GIL, and event delivery

The rules that keep an in-process Python embedding from deadlocking or crashing.
These are correctness rules, not performance advice.

Context: [overview.md](overview.md),
[ADR-0002](../decisions/ADR-0002-embedded-python-pythonkit.md),
[ADR-0006](../decisions/ADR-0006-events-surface-polling-first.md).

## The constraint

CPython has one global interpreter lock. PythonKit does not manage the GIL for you
across threads. `PythonObject` is not `Sendable`, so Swift 6 strict concurrency will
reject casual sharing, correctly.

## Rule 1, one serial queue owns Python

Every touch of a `PythonObject`, including reading an attribute and including
releasing one, happens on a single serial `DispatchQueue` or a single actor dedicated
to Python. No exceptions.

The alternative, wrapping individual calls in `PyGILState_Ensure` and
`PyGILState_Release`, is workable but leaves you managing the GIL by hand at every
call site. A dedicated serial queue or actor makes the constraint structural instead
of remembered.

Note that this serialization is not a throughput problem for this app. Fan-out
concurrency happens inside the module's asyncio loop, below the bridge. One Swift call
can trigger thirty concurrent HTTP requests. See
[ADR-0001](../decisions/ADR-0001-async-core-sync-facade.md).

## Rule 2, decode at the boundary

Convert `PythonObject` values into Swift types on the Python queue, then send only
Swift values onward.

```swift
// on the Python queue
let user = try client.userInfo(username: "x")     // wrapper returns a Swift struct

// anywhere
await MainActor.run { store.apply(user) }
```

Storing a `PythonObject` in a view model, or handing one to the main actor, moves a
GIL-protected reference onto a thread that does not hold the GIL. Deallocation alone
can then crash the process.

## Rule 3, never hand Python a Swift callback

Events originate on the module's asyncio loop thread. The tempting design is to pass a
Swift closure into the module so it can push events directly.

Do not. That means arbitrary Swift code executing on a Python-owned thread while
holding the GIL. Expected outcome is deadlock or crash. INFERENCE, based on the
threading model, not observed here.

## The event delivery pattern

Python owns a thread-safe buffer. The consumer drains it. Data crosses as plain
values, never as callbacks, and no Python thread ever touches Swift memory.

Python side:

```python
class EventBuffer:
   def drain(self) -> list[Event]:
      """Pop all pending events. Safe to call from any thread."""
```

Swift side:

```swift
// on the Python serial queue
let events = listener.drain()
let decoded = events.map(Event.init)
await MainActor.run { store.apply(decoded) }
```

Two drain strategies, both acceptable:

- Swift polls `drain()` on a timer, on the order of every 200ms.
- The module exposes a blocking `wait_for_events(timeout)` that parks on the Python
  side and returns a batch. This trades a parked queue slot for lower latency.

Whichever is chosen, the drain call itself must obey Rule 1 and run on the Python
queue.

A consequence worth stating: this design also keeps the module free of Swift-specific
hooks, so it stays usable from a plain script, a CLI, or a web backend. The bridge
constraint improved the library's portability rather than compromising it.

## Rule 4, bootstrap once, before anything else

Interpreter initialization is not reconfigurable. `PythonRuntime.bootstrap()` runs
once per process, before the first PythonKit symbol is touched, and is idempotent. See
[overview.md](overview.md).

## Rule 5, exceptions cross deliberately

A Python exception surfaces through PythonKit as a Swift error only where the wrapper
converts it. Wrapper methods map module exception types onto a Swift error enum on the
Python queue. Raw Python exception objects do not travel outward, for the same reason
raw `PythonObject` values do not.

The wrapper formats the traceback into a Swift `String` on the Python queue and carries it as
a payload on the error case. That string is already redacted by the module, and the app shows
it in debug builds only, since it names internal paths.

On the Python side the exception has already crossed one thread boundary before it reaches the
bridge, from the asyncio loop thread to the facade. It arrives as the original exception object
with a note marking that seam, which means the type a wrapper matches on is the type the
library raised. See
[../decisions/ADR-0012-exceptions-across-the-loop-thread.md](../decisions/ADR-0012-exceptions-across-the-loop-thread.md).

## Known failure modes

| Symptom | Likely cause |
|---|---|
| Hang with no CPU use | Swift code invoked from a Python thread, or a GIL acquired and not released. |
| Crash on deallocation, often far from the call site | A `PythonObject` released off the Python queue. |
| Swift 6 compile error about `Sendable` | A `PythonObject` crossing an isolation boundary. The compiler is right. Decode first. |
| Events arrive late in bursts | Drain interval too long, or the drain call queued behind a long-running Python call on the same serial queue. |
| An error reaches Swift with no useful detail | The wrapper mapped the exception type but dropped the formatted traceback payload. |
