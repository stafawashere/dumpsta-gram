# Python integration, app side

The app-specific half of the bridge. The general mechanism, bootstrap sequence, and
threading rules are canonical in
[../../docs/bridge/overview.md](../../docs/bridge/overview.md) and
[../../docs/bridge/threading-and-gil.md](../../docs/bridge/threading-and-gil.md), and
are not repeated here.

This document covers what the app builds on top of that.

## The wrapper layer

`Bridge/` exposes a typed Swift API over `dumpstagram.SyncClient`. The rest of the app
sees Swift types and Swift errors, never PythonKit.

```swift
// on the Python queue
let user = try client.userInfo(username: "x")     // returns a Swift struct

// anywhere
await MainActor.run { store.apply(user) }
```

Three obligations for every wrapper method.

**Decode before returning.** Convert to Swift value types on the Python queue. A
`PythonObject` must never escape. See the threading rules for why releasing one off
the queue can crash the process.

**Map errors on the queue.** Engine exceptions become cases of a Swift error enum
there, not later. Raw Python exception objects do not travel outward, for exactly the
same reason raw `PythonObject` values do not.

**Stay thin.** The wrapper translates. It does not orchestrate, retry, cache, or pace.
Orchestration is `Services/`. Retry and pacing are the engine's.

## Error mapping

The engine's public exception hierarchy is part of its API and maps onto a Swift enum.
The categories the engine anticipates are listed in
[../../engine/docs/public-api.md](../../engine/docs/public-api.md).

One mapping decision is not mechanical and deserves stating. Challenge and checkpoint
states are not errors in the engine, and they must not become error cases in Swift
either. Modelling them as errors invites `catch` blocks that retry, and retrying
through a checkpoint escalates account restrictions.

They belong in the result type, as states the UI presents and the person resolves.

## Event delivery

The engine hands out a listener with a drainable buffer. Swift drains it. Swift never
gives Python a closure.

```swift
// on the Python serial queue
let events = listener.drain()
let decoded = events.map(Event.init)
await MainActor.run { store.apply(decoded) }
```

Two drain strategies, both acceptable:

- Poll `drain()` on a timer, on the order of every 200ms.
- Call the engine's blocking `wait_for_events(timeout)`, which parks on the Python side
  and returns a batch. Lower latency, at the cost of occupying the queue.

The second option interacts with Rule 1. A blocking wait occupies the single Python
serial queue for its duration, which stalls every other Python call behind it. If the
blocking strategy is chosen, the listener needs its own dedicated queue and its own
GIL discipline, which is a meaningful increase in complexity. Start with polling.

## Development loop

In debug builds `engine/src` is on `sys.path` directly, so editing Python needs no
Xcode rebuild.

```swift
let importlib = Python.import("importlib")
importlib.reload(dumpstagram)
```

Reload works for pure-Python edits. It does not refresh references already held, so
anything cached from the engine must be re-fetched afterwards. It does not work for C
extensions. INFERENCE from CPython's documented reload semantics, not tested here.

A reload while a listener is running is a hazard. The listener holds engine state that
the reload replaces. Stop listeners before reloading.

## What the app must never do

- Import `dumpstagram._private` or `dumpstagram._core`.
- Construct a request, a header, or a cursor.
- Implement a retry policy for upstream failures.
- Implement rate limiting.
- Pass a Swift closure into Python.
- Hold a `PythonObject` in a view model or a store.
