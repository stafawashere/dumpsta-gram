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

### The listener shape as landed

Added 2026-09-23 as Step 22 of [build-plan.md](build-plan.md), before its transport. The whole
surface is fixed now so the polling transport of Step 23 and a push transport later need no
snapshot change:

```python
async with aclosing(aclient.events(since=last_seen_id)) as stream:
   async for event in stream:
      ...

with client.events(since=last_seen_id) as listener:       # starts, and stops on exit
   while True:
      for event in listener.wait_for_events(1.0):
         ...

listener = client.events(on_event=handler)                # the handler gets every event
```

`AsyncClient.events(*, since=None)` is an async generator of `Event`.
`SyncClient.events(*, since=None, on_event=None)` returns an `EventListener`, from
`dumpstagram.listener`, which is not built directly and does nothing until `start()`. Its
methods are `start`, `stop`, `drain`, `wait_for_events(timeout)`, and the context manager pair.
The two `events` methods share every parameter except `on_event`, and a listener parity gate in
`tests/test_facade_parity.py` holds that, because the facade parity suite cannot: it discovers
capabilities by coroutine, and an async generator is not one.

`since` is the only parameter, a message id watermark: the id of the last message the consumer
handled, never delivered again, from which a restarted listener catches up. The poll interval
is `Behavior.poll_interval_seconds`, 60 s by default and never an `events()` parameter, per
ruling 9. The buffer bound, 1000, is not a parameter either.

The events are frozen dataclasses in `dumpstagram.models.events`, all subclasses of `Event`:
`NewMessage(message)`, the one kind from the upstream, the viewer's own messages included;
`EventsDropped(count)`, the marker a full buffer leaves where it dropped the oldest; and
`ListenerStopped(error)`, the last event a blocking listener delivers when a failure ends it,
carrying the original exception with a seam note. The async iterator raises that exception
instead. `CheckpointRequired` and `AuthenticationFailed` end a listener and are never polled
through. `TransportFailure` and `RateLimited` are retried with account-wide backoff and cost one
poll when they outlast it. Within a thread, events arrive in ascending `sent_at`, and no message
id arrives twice. With `on_event`, events go to the handler on the listener's own thread and
never to the buffer, and `drain()` raises. Every guarantee here is gated offline, see
[engineering/gates.md](engineering/gates.md).

Until Step 23 lands the poller, the first poll raises `NotImplementedError`, so the async
iterator raises it and a blocking listener delivers it in a `ListenerStopped`. No request is
sent. Full behavior in [realtime-events.md](realtime-events.md).

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
`feed_first_page`, `profile_route`, `thread_first_page`, `page_load_companions`,
`cookie_sync`, `write_spacing`, `write_budget_per_hour`,
`stop_writes_after_unrecognised_rejection` and `poll_interval_seconds`. The last, added with the
Step 22 listener, is the wait between one listener poll and the next, 60 s in every preset,
zero allowed and a negative a `ValueError`. The listener honours it today and has nothing to poll
until Step 23, see the listener shape above.
`feed_first_page` decides where `feed()` with no cursor reads from.
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

`notes()` has no setting. Added 2026-09-23 as the read half of Step 14, it returns
`tuple[Note, ...]`, the whole notes tray on the direct inbox in the tray's order, from one
`IGDInboxTrayQuery` request, since the tray is one unpaged call. A cursor appearing beside the
items raises `SchemaChanged` rather than reporting a first page as the whole tray. `Note`
carries `id`, the tray item's 17-digit id that a delete will name, `author_id`, the author's
numeric Instagram id, `text`, empty on a song note, `audience`, `created_at` in UTC,
`is_emoji_only` and `author_username`. The viewer's own note is the one whose `author_id`
equals the session's `ds_user_id`, and it is absent when the viewer has none. `NoteAudience`
is an `IntEnum` holding the web client's own numbers, `MUTUAL_FOLLOWS` 0 ("Followers you follow
back"), `CLOSE_FRIENDS` 1 and `INTERNAL` 2, read out of the client's `PolarisNotesTypes` module,
and any other number is a `SchemaChanged`. A browser reads the tray inside an inbox page load
beside nine other queries, and the engine sends the tray query alone under every behavior until
the inbox load is modelled, a departure recorded in
[web-request-contract.md](web-request-contract.md). `set_note(text, *, audience=...)` and
`delete_note(note_id)` are not implemented yet, see [build-plan.md](build-plan.md) Step 14.

`post(code)`, `like(post_pk)` and `unlike(post_pk)` have no setting either. Added 2026-09-23 as
Step 15. `post` reads one post by the shortcode in its web address, one `PolarisPostRootQuery`
request, and returns `PostDetail`, a model of its own rather than `Post`: the single post item
carries every field `Post` reads except `is_seen`, and making that field optional would have
changed a line of the contract. `PostDetail` has `Post`'s fields without `is_seen`, and its
`has_liked` and `like_count` are what a like is confirmed by. `like` and `unlike` return `None`
and each is one write through `send_write`, sent once and never retried, under the behavior's
write spacing, budget and stop. They take the media `pk`, `Post.pk` or `PostDetail.pk`, which is
what both mutations were observed taking. The `id` form, `<pk>_<author id>`, raises `ValueError`
before anything is sent, because nothing records what the upstream does with it. Both set a
state: a second like of a liked post and a second unlike of an unliked one each answered like
the first and moved `like_count` no further, observed once each on 2026-09-23, so after
`OutcomeUnknown` a caller reads the post with `post` and decides. An answer without an error
that names the opposite state raises `UpstreamRejected` with code `has_liked_did_not_follow`,
never observed. A browser sends a post read inside a post page load and a like beside whatever
page it is on. Neither burst has been recorded, because ruling 23 allowed no browser load when
these were verified, so each is sent alone, a departure recorded in
[web-request-contract.md](web-request-contract.md).

`comments(post_pk, *, after=None)`, `comment(post_pk, text)` and `delete_comment(post_pk,
comment_id)` have no setting either. Added 2026-09-23 as Step 16. `comments` reads one page of a
post's comments, one `PolarisPostCommentsPaginationQuery` request, and returns `Page[Comment]`,
whose `has_next_page` is the only terminator: a short or empty page is not the end. `comment`
returns the created `Comment`, mapped from the answer's `comment_dict`, and `delete_comment`
returns `None`. Each write is one request through `send_write`, sent once and never retried,
under the behavior's write spacing, budget and stop. All three take the media `pk` and refuse the
`<pk>_<author id>` form with `ValueError` before anything is sent, and `delete_comment` takes the
comment's id, digits only, beside it, because the two deletes that worked sent both. `Comment`
carries `id`, `text`, `created_at` in UTC, `author` as `CommentAuthor` with `id`, `username`,
`is_verified` and `profile_pic_url`, and four fields only the page read fills, `like_count`,
`reply_count`, `parent_comment_id` and `has_liked`, which are None on a comment `comment` just
created because its answer does not carry them. A comment appends, per 13.3 in
[build-plan.md](build-plan.md): after `OutcomeUnknown`, a second send may be a duplicate everyone
who can see the post sees, so the docstring names `comments` as the read that reconciles it, look
for the viewer's own comment made after the attempt began, and a gate holds that sentence in
place. A delete sets a state. A delete answered with a null root field raises `UpstreamRejected`
with code `comment_not_deleted`, because a delete naming no comment was answered that way, so a
second delete of a comment already gone is expected to raise it too, INFERENCE. What a browser
sends around each of the three is unrecorded under ruling 23, so each is sent alone, a departure
recorded in [web-request-contract.md](web-request-contract.md).

`page_load_companions` decides whether a document load also sends the queries a browser's page
load sends beside its own. It applies to the two routes that load a document, the home document
under `FeedFirstPage.DOCUMENT` and the profile page under `ProfileRoute.PAGE`. True, the parity
default, sends after the home document the badge count, the chat tabs jewel with the omni picker,
and two quick promotion calls, and after the profile page's six queries the stories tray, the
jewel with the omni picker, the badge count and the two quick promotion calls, all inside the
document's own paced action and in the recorded page's order and grouping. None of their answers
is read, a checkpoint or throttle on one is still raised, and any other failure on one is
ignored. The badge count and the jewel are keyed on a device id each document carries, and are
left out when a document carries none. What a browser also sends and these do not: the manifest,
`fxcal/ig_sso_users`, and the profile page's feed prefetch. The facebook.com cookie sync is
governed by `cookie_sync`, not by this setting. False leaves the companions out and changes
nothing else. Every preset keeps True.

`cookie_sync` decides whether a document load leaves behind the cookie sync a browser's page runs
seconds later. It applies to the same two routes, and only when the load succeeds. True, the
parity default, sends four requests 4 to 10 s after the document departed, outside the
document's action and without waiting for the caller's next one: the facebook.com
`/instagram/login_sync/` iframe document, then together the `PolarisAPIGetFrCookieQuery`
exchange of `Session.fr` and the iframe's `/instagram/sync/` fetch, then the post of the
fetched blob to `/sync/instagram/`. The two facebook.com requests carry no cookies. Nothing is
returned to the caller and no failure reaches them. The exchange updates `Session.fr` by the
page's rule. A client closed before the delay sends none of it, which is the usual case for a
single CLI command. False sends none of it and changes nothing else, and it is the setting for
a caller who wants no traffic to facebook.com. Every preset keeps True.

The three write settings govern every write the engine sends. No write capability exists yet,
so on 2026-09-23 they govern the write path in `_core/writing.py` and nothing a caller can
reach, and they are settings now so that the first write ships under all three.
`write_spacing` is the gap before a write, measured from the account's previous write,
`Spacing(floor_seconds=30.0, mean_jitter_seconds=5.0)` by default. It does not delay the reads
between two writes, and a write still keeps `spacing` from whatever went before it.
`write_budget_per_hour` defaults to 30 writes in any rolling hour, and a write past it raises
`RateLimited` with `retry_after` set and sends nothing. None removes the budget, and 0 refuses
every write. `stop_writes_after_unrecognised_rejection` defaults to True: after a write is
rejected with a code nothing recorded explains, every later write raises `UpstreamRejected`
with the code `writes_stopped` without sending, and reads carry on. The HTML application shell
is not such a rejection, since it means the page token was refused and the next call
bootstraps. All three numbers are placeholders chosen to be cautious and derived from nothing,
rulings 3 and 4 in [build-plan.md](build-plan.md) section 17.13. `PARITY` carries the
placeholder spacing too, because no human write timing has been measured, and takes the
measured timing when one exists. `FAST` sets `write_spacing` to zero and keeps the budget and
the stop. The budget, the stop and the record of what departed belong to the account's pacer,
so a client from `with_behavior` shares them with its owner. No setting makes the engine retry
a write, ruling 13.

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
async surface with the snapshot updated to match. Since Step 22, `LISTENER_METHODS` in the suite
keeps `events` out of the snapshot control, the way `SCOPING_METHODS` keeps `with_behavior` out,
and the listener parity gate plus a gate that each excluded name is in the snapshot on both
surfaces hold it instead. See
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
| Outcome unknown | `OutcomeUnknown`, added 2026-09-23 for writes. The connection failed while a write was in flight, so it may or may not have applied. `operation` names the write, and the network failure is on `__cause__`. The way forward is to read the state the write would have changed. In its first version every `TransportFailure` during a write becomes this, including a connect timeout that probably sent nothing, because that is INFERENCE about `httpx` rather than measured. | Never, structurally: absent from `RETRYABLE` and sharing no base with its members, so not a `TransportFailure` |
| Operation cancelled | The awaited work was cancelled. Exists because of the threading model rather than because of Instagram, since `asyncio.CancelledError` is a `BaseException` and would slip past a caller's `except Exception`. A write cancelled in flight has an unknown outcome too, and stays this type because ADR-0012 permits one translation. | No |

On a write, `UpstreamRejected` is an answer, read as "not applied", INFERENCE since no failed
write has been observed, and `SchemaChanged` means the upstream answered without an error and
only the mapping failed, so the write has probably applied.

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
