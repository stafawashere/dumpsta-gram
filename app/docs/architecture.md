# Architecture

How the Swift side is layered and who owns what, particularly concurrency.

Canonical bridge documentation:
[../../docs/bridge/overview.md](../../docs/bridge/overview.md) and
[../../docs/bridge/threading-and-gil.md](../../docs/bridge/threading-and-gil.md).

## Layers

```
app/src/DumpstaGram/
   PythonRuntime.swift        bootstrap, once per process
   Bridge/                    the Python queue and the typed wrapper
   Services/                  orchestration over the wrapper
   Models/                    Swift value types, decoded at the bridge
   Stores/                    observable application state, main actor
   Views/                     SwiftUI
```

The shape that matters is the two concurrency domains and the single seam between
them.

## Two concurrency domains

**The Python domain.** One serial `DispatchQueue` or one actor. Owns every
`PythonObject`, including creating, reading, and releasing them. Nothing else touches
Python.

**The main actor.** Owns stores and views.

Between them, only Swift value types travel. This is not a style preference. A
`PythonObject` released on a thread that does not hold the GIL can crash the process,
and Swift 6 will reject the crossing anyway because `PythonObject` is not `Sendable`.

Serializing all Python access is not a throughput problem. Fan-out concurrency happens
inside the module's asyncio loop, below the bridge. One Swift call can trigger thirty
concurrent HTTP requests. See
[ADR-0001](../../docs/decisions/ADR-0001-async-core-sync-facade.md).

## The seam

`Bridge/` holds a typed Swift wrapper over the module's `SyncClient`. Every method:

1. Runs on the Python queue.
2. Calls the module.
3. Converts the result into a Swift value type.
4. Maps module exceptions onto a Swift error enum.
5. Returns Swift values only.

Nothing above `Bridge/` imports PythonKit. That is checkable mechanically and worth
checking, because a single PythonKit import in a view model is how the rules erode.

## State flow

```
View
   calls
Store (main actor)
   awaits
Service
   hops to the Python queue
Bridge wrapper
   calls
dumpstagram.SyncClient
   which crosses into the module's loop thread
```

Results travel back as Swift values, and the store applies them on the main actor.

## Event flow

Events come from a drainable buffer, never a callback. See
[python-integration.md](python-integration.md) for the mechanism and
[ADR-0006](../../docs/decisions/ADR-0006-events-surface-polling-first.md) for why.

```
module listener writes into the event buffer
Swift drains on the Python queue, on a timer or a blocking wait
decoded into Swift values
applied to the store on the main actor
```

The drain call obeys the same rule as everything else. It runs on the Python queue.

## Challenge and checkpoint states

These are first-class module states, not errors. The app surfaces them as something a
person can act on, and it does not retry.

This is the single most important thing for the reference-implementation job to get
right. An example that retries through a checkpoint teaches every reader to escalate
their users' account restrictions. See
[../../module/docs/session-and-auth.md](../../module/docs/session-and-auth.md).

## Account state

One module client instance per account, held explicitly. There is no global client,
because the module refuses to have one. See
[ADR-0004](../../docs/decisions/ADR-0004-instance-scoped-sessions.md).

An account switcher is therefore a UI concern over a collection of instances, not a
module feature. That is the payoff of the instance-scoped rule.

## Invariants

- Nothing above `Bridge/` imports PythonKit.
- No `PythonObject` outside the Python queue.
- No Instagram knowledge anywhere in Swift.
- Bootstrap runs once, before any other Python use.
- No retry loops around challenge states.
