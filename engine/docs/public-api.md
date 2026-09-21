# Public API and stability contract

What consumers may depend on, in what shapes, and what the library promises about it.

Implements [ADR-0001](../../docs/decisions/ADR-0001-async-core-sync-facade.md) and
[ADR-0006](../../docs/decisions/ADR-0006-events-surface-polling-first.md).

## Three surface shapes

Sync and async are not chosen per capability. They are two doors into one engine. The
third shape exists because live monitoring differs in lifetime, not in concurrency
model. A fetch starts and ends. A listener runs for hours, holds a connection,
reconnects, and pushes events.

```python
client.user_info("x")                    # sync, returns User
await aclient.user_info("x")             # async, returns User
async for event in aclient.events():     # stream, yields until stopped
```

Plus the sync-callable listener, because Swift cannot `async for`:

```python
listener = client.events(on_event=handler)
listener.start()
listener.stop()
```

## Construction

The caller builds a session and passes it in. The client never creates its own.

```python
client = SyncClient.from_session_file("account.json")
```

This is the single rule that makes multi-account a later addition rather than a
rewrite. See
[ADR-0004](../../docs/decisions/ADR-0004-instance-scoped-sessions.md).

There is deliberately no one-line global login. Convenience was traded for the
stability goal.

This shape survives the credential model changing underneath it. Phase 1 builds a `Session`
by adopting credentials out of an existing browser session, and the deferred login work will
build one by logging in. The constructor takes a finished `Session` either way, which is
exactly why login can be added later without touching the public surface. See
[session-and-auth.md](session-and-auth.md) and
[../../docs/decisions/ADR-0008-adopt-existing-browser-session.md](../../docs/decisions/ADR-0008-adopt-existing-browser-session.md).

## The facade

```python
class SyncClient:
   def __init__(self, session: Session, *, user_agent: str | None = None) -> None:
      self._loop = _LoopThread.acquire()
      self._impl = AsyncClient(session, user_agent=user_agent)

   def user_info(self, username: str) -> User:
      return self._loop.run(self._impl.user_info(username), operation="SyncClient.user_info")
```

Written 2026-09-21, minus the capability. `user_info` above is the shape every capability
takes, and the first real one arrives with the first typed model.

Two properties of this shape are load-bearing.

`_LoopThread.acquire()` returns the shared refcounted loop thread, not a new one.

`self._loop.run(...)` wraps `asyncio.run_coroutine_threadsafe`. It never calls
`asyncio.run()`, which would create and destroy the loop per call, tearing down the
connection pool and discarding loop-bound session state.

The reference is held from construction until `close`, so both surfaces carry a lifecycle:
`SyncClient` supports `with` and `close()`, `AsyncClient` supports `async with` and
`aclose()`, and both are idempotent. A client that is never closed keeps the shared thread
alive for the lifetime of the process.

## Stability contract

**Covered by the promise.** Everything importable from `dumpstagram` without a leading
underscore. Function and method signatures, model field names and types, the public
exception hierarchy, and documented behavior.

**Not covered.** `dumpstagram._private` and `dumpstagram._core` in their entirety.
These may be reorganized in any release.

**Consequences for implementers.**

- Public functions return typed models, never raw dicts.
- Public functions raise from the library's own exception hierarchy, never `httpx`
  exceptions and never transport-layer errors.
- Adding a field to a model is compatible. Renaming or removing one is not.
- Adding a capability is compatible. Changing an existing capability's semantics is
  not, even if the signature is unchanged.

### The snapshot is the contract

Ruled 2026-09-20. `tests/public_surface.txt` holds a generated, sorted description of the whole
public surface: module-level names, signatures with annotations, model fields and types, and
the exception hierarchy. A test regenerates it and fails on any diff. Docstrings are excluded,
because a wording fix is not an API change.

Changing the public API therefore means regenerating the snapshot in the same change, which
puts the change in a diff a human reads. The snapshot is a gate, so it may be regenerated
deliberately and may never be regenerated to make a failing test pass.

Landed 2026-09-21, as the first thing Phase 2 built. `scripts/snapshot_surface.py` renders it,
`tests/test_public_surface.py` diffs it, and the committed file is 79 lines. The declared
surface is `__all__`, a name re-exported from another module renders as one alias line rather
than a second copy of the definition, and the renderer sorts by dotted path so a diff groups by
name. Stability is gated in two subprocesses under different `PYTHONHASHSEED` values, because
set iteration order is what usually makes a generated artifact unstable and it is invisible
inside one process.

### Versioning

Semantic versioning, with the snapshot defining a breaking change.

| Range | Promise |
|---|---|
| `0.y.z` | None. Breaking changes land freely, which is the point of making them before the app exists. |
| `1.0.0` | Cut when the snapshot has been unchanged across the whole of Phase 3 and Phase 4, which is also when Swift work starts. |
| After `1.0.0` | Removing or changing a snapshot entry is a major bump. Adding one is minor. Everything else, including every `_private` change and every upstream endpoint repair, is a patch. |

Upstream churn does not inflate the version. Instagram breaking an endpoint and the library
repairing it is invisible to callers, so it is a patch. See
[../../docs/decisions/ADR-0011-api-surface-snapshot-and-versioning.md](../../docs/decisions/ADR-0011-api-surface-snapshot-and-versioning.md).

## Keeping the two surfaces in step

Every public capability exists in both a sync and an async form. Without a mechanism,
they drift. This is the main long-term maintenance risk in the design.

Three candidate mechanisms, none chosen yet:

- Generate the facade mechanically from the async surface.
- Drive both through one shared test suite, so a missing facade method fails a test.
- Manual discipline plus review.

UNRESOLVED as a mechanism. What is no longer missing is detection: both surfaces appear in
`tests/public_surface.txt`, so a method added to one and not the other shows up as an
asymmetric diff. That catches drift, it does not prevent it, and whoever implements the facade
should still choose a mechanism before the method count grows. See
[../../docs/decisions/ADR-0011-api-surface-snapshot-and-versioning.md](../../docs/decisions/ADR-0011-api-surface-snapshot-and-versioning.md).

## Errors as part of the API

The exception hierarchy is public, so it gets designed rather than grown. The categories below
are anchored to failure modes actually observed by the prior project where marked FACT, and
assumed otherwise. See
[../../docs/knowledge/prior-art-dumpsta-js.md](../../docs/knowledge/prior-art-dumpsta-js.md).

| Category | Meaning for the caller | Retryable |
|---|---|---|
| Authentication failure | Credentials or session are not usable. FACT: includes a server-initiated logout, signalled by an empty cookie value. | No |
| Challenge or checkpoint required | Not an error to retry. A state requiring user action. | Never, structurally |
| Upstream rejected the request | FACT: arrives as HTTP 200 with an error envelope, not as a 4xx. Missing or stale request tokens land here. | Depends on cause |
| Rate limited | The pacer or upstream says wait. | Yes, with account-wide backoff |
| Not found or not permitted | The target does not exist or is not visible to this account. | No |
| Upstream schema change | The library could not map a response. Loud, because silent degradation is worse. FACT-adjacent: the prior project rated a field rename inside a response node its worst case, because it degrades records silently and is caught only by comparison against a recorded oracle. | No |
| Transport failure | Network-level. | Yes |
| Operation cancelled | The awaited work was cancelled. Exists because of the threading model rather than because of Instagram, since `asyncio.CancelledError` is a `BaseException` and would slip past a caller's `except Exception`. | No |

Four rules follow, and the first two are inherited from measured behavior.

**Never classify by status code alone.** HTTP 200 is not a success signal on this API. The
classification has to read the payload.

**Checkpoints are non-retryable in code, not by convention.** The prior project marked its
checkpoint error fatal and excluded it from the retry path structurally, reasoning that a
comment saying "do not retry challenges" would not survive a refactor. Retrying around a
challenge escalates a soft block into a locked account.

**A false positive in the checkpoint classifier is itself a serious bug.** Because checkpoints
are never retried, a classifier that fires on innocent message content does not produce a
warning, it makes the operation permanently unfinishable, with every resume aborting at the same
point. See [session-and-auth.md](session-and-auth.md) for the specific inherited defect and the
rule that prevents it.

## Exceptions crossing the loop thread

**The sync facade re-raises the original exception object.** It does not wrap it and does not
re-type it, so `except dumpstagram.RateLimited` catches the same thing whether the caller used
the sync facade or awaited the async surface. Before re-raising, the facade attaches a note
naming the facade method and the operation, which gives the printed traceback a visible seam
where the loop-thread frames meet the caller's frames.

`asyncio.CancelledError` becoming `OperationCancelled` is the only translation. Unhandled
errors inside the loop are routed to the library's logger through `loop.set_exception_handler`
rather than disappearing, and formatted tracebacks are redacted the same way log output is,
because a traceback is the one place a credential reaches a log with nobody writing a log
statement.

Full reasoning, including what was rejected, in
[../../docs/decisions/ADR-0012-exceptions-across-the-loop-thread.md](../../docs/decisions/ADR-0012-exceptions-across-the-loop-thread.md).
