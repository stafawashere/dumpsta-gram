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

### Behavior

Added 2026-09-23 under
[ADR-0013](../../docs/decisions/ADR-0013-browser-parity-by-default.md). Both clients take a
keyword-only `behavior`, a frozen `Behavior` from `dumpstagram.behavior`, defaulting to
`PARITY`. It governs traffic across requests, never the shape of one request.

```python
from dataclasses import replace
from dumpstagram import EXPORT, FAST, Spacing, SyncClient

with SyncClient.from_session_file("account.json") as client:
   profile = client.profile_by_id("25025320")

   with client.with_behavior(FAST) as scraper:
      page = scraper.thread_messages("17945046917948992")

   slower = replace(EXPORT, spacing=Spacing(floor_seconds=4.0, mean_jitter_seconds=1.0))
   export = client.with_behavior(slower)
```

`with_behavior` is how a single stretch of calls departs from the client's configuration,
ruling 14 in [build-plan.md](build-plan.md) section 17.13. The client it returns shares the
session, the pool and the pacer, and differs only in behavior, so no capability grows an
override keyword and no existing snapshot line changes when a setting is added. Closing it
does not close the pool. Closing the owner stops both.

`Behavior` carries only settings the engine honours. On 2026-09-23 that is `spacing`,
`feed_first_page`, `profile_route` and `thread_first_page`. `feed_first_page` decides where `feed()` with no cursor reads from.
`FeedFirstPage.DOCUMENT`, the parity default, loads `https://www.instagram.com/` as a
navigation and reads the first page the server preloaded into that document, which is what a
browser does. It is one request of about 1.2 MB, four measured loads carried 3 or 4 items,
and it refreshes the session's page tokens. `FeedFirstPage.QUERY` asks the pagination query
instead, the route the engine used before, which no browser was observed to take. Later pages
use the pagination query under both. Every preset keeps `DOCUMENT`, because a preset departs
only in what it names.

`profile_route` decides how `profile(username)` reads. `ProfileRoute.PAGE`, the parity default,
loads the profile page as a navigation, reads the account id out of it, and sends the page's six
queries together, seven requests in one paced action. It refreshes the session's page tokens,
finds an account with no visible posts, and raises `NotFound` when no account has the username.
`ProfileRoute.QUERIES` is the route the engine used before: the account's timeline for its id,
then the profile query, two requests in series. `profile_by_id` sends the profile query alone
under both, since no browser page is keyed on an id.

`thread_first_page` decides how `thread_messages` with no cursor and no `newer_than_message_id`
reads. `ThreadFirstPage.DETAIL`, the parity default, sends `IGDThreadDetailQuery`, the query a
browser sends when it opens a thread, about 42 kB for 20 messages. `ThreadFirstPage.QUERY`
sends the scrolling query instead, which no browser was observed to do for the newest page.
Every older page and every top-up goes through `IGDMessageListOffMsysQuery` under both, which
replaced `useIGDMessageListPaginationQuery` in the browser by 2026-09-23. One request either
way. Neither sends the inbox burst or the fifteen prefetches a browser's thread load carries,
and neither marks the thread seen.

Other companion requests and side effects such as marking a thread read become fields with
parity defaults when the requests behind them are implemented, which is an additive snapshot
change.
The presets are `PARITY`, `EXPORT` and `FAST`, and what each one costs is in
[rate-limiting-and-safety.md](rate-limiting-and-safety.md).

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

Written 2026-09-21. `user_info` above is the shape every capability takes, and the first real
one is `thread_messages`, which landed the same day:

```python
page = client.thread_messages("17945046917948992")        # sync, returns Page[Message]
page = await aclient.thread_messages(thread_fbid)          # async, same result

while page.has_next_page:
   page = client.thread_messages(thread_fbid, after=page.end_cursor)
```

`Page.has_next_page` is the only terminator. A short page is not the end of a connection, and
neither is an empty one.

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
| `1.0.0` | Cut when no line of the snapshot at the Phase 3 baseline has been removed or changed by the close of Phase 4, which is also when Swift work starts. Additive reading since 2026-09-23, see the amendment in ADR-0011. |
| After `1.0.0` | Removing or changing a snapshot entry is a major bump. Adding one is minor. Everything else, including every `_private` change and every upstream endpoint repair, is a patch. |

Upstream churn does not inflate the version. Instagram breaking an endpoint and the library
repairing it is invisible to callers, so it is a patch. See
[../../docs/decisions/ADR-0011-api-surface-snapshot-and-versioning.md](../../docs/decisions/ADR-0011-api-surface-snapshot-and-versioning.md).

## Keeping the two surfaces in step

Every public capability exists in both a sync and an async form. Without a mechanism,
they drift. This is the main long-term maintenance risk in the design.

**Ruled 2026-09-22: one shared parity suite.** The other two candidates were generating the
facade mechanically from the async surface, and manual discipline plus review. Generation was
rejected because each facade method is five lines of forwarding, and a generator, a
do-not-edit file and a freshness gate cost more than they save at this size. Review alone was
rejected because it is the thing that already missed nothing only by luck.

`tests/test_facade_parity.py` names no capability. It discovers every public coroutine on
`AsyncClient` and, for each one, demands a `SyncClient` method that:

- exists, under the same name, and is not itself a coroutine
- takes the same parameters, in the same order, with the same kinds, defaults and annotations,
  and returns the same type
- forwards every argument to the async method unchanged, proven with one distinct object per
  parameter so a dropped or swapped argument cannot compare equal
- runs the coroutine on the shared loop thread and returns the object it returned
- re-raises the object the async side raised, carrying the seam note under its own name

The two public name sets must also match, with `aclose` answering to `close`, and every shared
name must be the same kind of member on both classes. The discovery itself has a positive
control: the capability list read off the class must equal the one read off
`tests/public_surface.txt`, so a discovery rule that finds nothing fails instead of leaving
every parametrised gate green by running none of them.

What it prevents is a drift reaching a commit, since adding a coroutine to `AsyncClient` fails
the suite until the facade method exists and forwards correctly. It does not write the facade
method, and a facade method still has to be written by hand. `scripts/verify_parity_gates.py`
breaks the facades ten ways and watches each gate go red, including a capability added to the
async surface with the snapshot updated to match. See
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
