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
surface was fixed then so the polling transport of Step 23 and a push transport later need no
snapshot change. Step 23 changed one pair of lines, `EventsDropped`, see below:

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
handled, never delivered again, from which a restarted listener catches up. The polling
transport places it in time and delivers what is newer in every listed thread, and says so with
an `EventsDropped` when it cannot find it. The poll interval
is `Behavior.poll_interval_seconds`, 60 s by default and never an `events()` parameter, per
ruling 9. The buffer bound, 1000, is not a parameter either.

The events are frozen dataclasses in `dumpstagram.models.events`, all subclasses of `Event`:
`NewMessage(message)`, the one kind from the upstream, the viewer's own messages included;
`EventsDropped(count, thread_fbid=None)`, the marker a full buffer leaves where it dropped the
oldest, with the count, and the marker the transport leaves for a gap it could not read back,
with `count` None and the thread when the gap is in one; and
`ListenerStopped(error)`, the last event a blocking listener delivers when a failure ends it,
carrying the original exception with a seam note. The async iterator raises that exception
instead. `CheckpointRequired` and `AuthenticationFailed` end a listener and are never polled
through. `TransportFailure` and `RateLimited` are retried with account-wide backoff and cost one
poll when they outlast it. Within a thread, events arrive in ascending `sent_at`, and no message
id arrives twice. With `on_event`, events go to the handler on the listener's own thread and
never to the buffer, and `drain()` raises. Every guarantee here is gated offline, see
[engineering/gates.md](engineering/gates.md).

The transport landed in Step 23: each poll reads the inbox listing, one request, and reads back
each thread whose newest message moved, one request per page. It never opens a thread or marks
one seen. `EventsDropped.count` became `int | None` and `thread_fbid` was added in that step,
because a gap the transport finds has a thread and no knowable count. Neither line is in the
Phase 3 baseline, so the additive freeze is untouched. Full behavior in
[realtime-events.md](realtime-events.md).

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
`stop_writes_after_unrecognised_rejection` and `poll_interval_seconds`, since E2 batch 3
`follow_list_statuses`, described with the followers below, since E2 batch 9 `inbox_route`,
described with `notes()` below, and since E2 batch 12 `mark_stories_seen`, described with the
stories below, whose default makes a story read visible to the story's owner, and since E2 batch
11b `typeahead_route`, described with the search below, whose default changed the accounts
`search.accounts` returns, and since E2 batch 11d `post_route`, described with `post` below. `poll_interval_seconds`, added with the
Step 22 listener, is the wait between one listener poll and the next, 60 s in every preset,
zero allowed and a negative a `ValueError`. The listener honours it, see the listener shape
above.
`feed_first_page` decides where `feed()` with no cursor reads from.
`FeedFirstPage.DOCUMENT`, the parity default, loads `https://www.instagram.com/` as a
navigation and reads the first page the server preloaded into that document, which is what a
browser does. It is one request of about 1.2 MB, four measured loads carried 3 or 4 items,
and it refreshes the session's page tokens. `FeedFirstPage.QUERY` asks the pagination query
instead, the route the engine used before, which no browser was observed to take. Later pages
use the pagination query under both. Every preset keeps `DOCUMENT`, because a preset departs
only in what it names.

`post_route` decides how `post(code)` and `media.by_code(code)` read, since E2 batch 11d (W111,
W112). `PostRoute.PAGE`, the parity default, loads `https://www.instagram.com/p/<code>/` as a
navigation and reads the post out of the document, which preloads it, and with
`page_load_companions` sends the page's five companions after it, six requests in one paced action
of about 1.1 MB. It refreshes the session's page tokens. `PostRoute.QUERY` is the route the engine
used before, the post query alone. Every preset keeps `PAGE`.

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

`inbox_route` decides how `notes()`, `direct.inbox()` with no cursor and `direct.unread_counts()`
read, since E2 batch 9 (W87). `InboxRoute.PAGE`, the parity default, loads
`https://www.instagram.com/direct/inbox/` as a navigation and sends the ten queries of the page's
direct block together, of which the tray, the inbox's first page and the two folders' unread rows
are four, eleven requests in one paced action, and with `page_load_companions` the inbox load's
companions after them. Whichever of the three is called, the whole block goes out and only that
read's answers are read; the document preloads none of them. It refreshes the session's page
tokens. `InboxRoute.QUERIES` is the route the engine used before: each read's own queries alone,
one request for the tray or the first page and two for the unread counts. Later inbox pages and
the message requests are sent alone under both. Every preset keeps `PAGE`.

`notes()` was added 2026-09-23 as the read half of Step 14. It returns `tuple[Note, ...]`, the
whole notes tray on the direct inbox in the tray's order, from the one `IGDInboxTrayQuery` answer,
since the tray is one unpaged call. The tray also holds items of other kinds, one `ambient_data` item
so far, whose meaning is unresolved; an item of another kind that carries no note is skipped, and
any other item that is not a note raises `SchemaChanged` (W91). A cursor appearing beside the
items raises `SchemaChanged` rather than reporting a first page as the whole tray. `Note`
carries `id`, the tray item's 17-digit id that a delete will name, `author_id`, the author's
numeric Instagram id, `text`, empty on a song note, `audience`, `created_at` in UTC,
`is_emoji_only` and `author_username`. The viewer's own note is the one whose `author_id`
equals the session's `ds_user_id`, and it is absent when the viewer has none. `NoteAudience`
is an `IntEnum` holding the web client's own numbers, `MUTUAL_FOLLOWS` 0 ("Followers you follow
back"), `CLOSE_FRIENDS` 1 and `INTERNAL` 2, read out of the client's `PolarisNotesTypes` module,
and any other number is a `SchemaChanged`. Under `InboxRoute.PAGE` the tray is read inside the
inbox page load as a browser reads it, which closes the departure `1.0.0` recorded;
`InboxRoute.QUERIES` sends it alone.

`set_note(text, *, audience=NoteAudience.CLOSE_FRIENDS) -> Note` and `delete_note(note_id) ->
None` have no setting either. Added 2026-09-23 as the write half of Step 14. `set_note` sends
`usePolarisCreateInboxTrayItemSubmitMutation` once through `send_write` and returns the created
`Note`, mapped from the answer's `inbox_tray_item`, which has the tray's own shape. It replaces
any note the viewer already has up, a song note included, which the library cannot make again,
so the docstring says to read `notes()` first when the old note matters. The `audience` keyword
exists from the first version, per ruling 7, so its line never changes. Its default is
`CLOSE_FRIENDS`, the narrower of the two audiences the composer offers, so a caller who does
not choose publishes to the fewest people. That departs from the composer, whose own default is
`MUTUAL_FOLLOWS`, and it is a choice about content rather than about traffic, so ADR-0013's
parity rule does not decide it; the CLI makes the audience a required argument instead. If the
answer carries another audience than the one asked for, which has not been observed,
`set_note` raises `UpstreamRejected` with code `note_audience_did_not_follow` and the note it made
is up. The create names the account by its Facebook-side id, `Session.actor_id`, read from the
bootstrap page and never substituted with `ds_user_id`; a session without it bootstraps once
first. `delete_note` sends `usePolarisDeleteInboxTrayItemSubmitMutation` once with the tray item
id, digits only, and its success is an answer whose root field is null. Both set a state rather
than append one, so after `OutcomeUnknown` the reconciling read is `notes()`. The browser burst
around each write is unrecorded under ruling 23, so each is sent alone, a departure recorded in
[web-request-contract.md](web-request-contract.md).

`post(code)`, `like(post_pk)` and `unlike(post_pk)` were added 2026-09-23 as Step 15, and since E2
batch 11d `post` reads through `post_route`. `post` reads one post by the shortcode in its web
address, under the default behavior out of the post page's document and under `PostRoute.QUERY`
from one `PolarisPostRootQuery` request, and returns `PostDetail`, a model of its own rather than `Post`: the single post item
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
never observed. A browser reads a post inside a post page load, which `post` now sends under the
default behavior and which closes the post departure of `1.0.0` (W111). A browser likes from
whatever page it has loaded, and no capture pairs a page load with a like, so a like and an unlike
are each sent alone and load no page, a departure recorded in
[web-request-contract.md](web-request-contract.md) (W113). Reading the post with `post` first gives
the browser's sequence.

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
second delete of a comment already gone is expected to raise it too, INFERENCE. Each of the three
is sent alone, departures recorded in [web-request-contract.md](web-request-contract.md). A
browser reads the first comments out of the post page's document, but `comments` is keyed on the
pk, which gives the page's address only for a public post, so it sends the pagination query for
every page (W111); `media.page(code)` reads the first comments out of the page. A comment and a
delete load no page, since no capture pairs a page load with either (W113).

`follow(user_id)` and `unfollow(user_id)` have no setting either, and both return `None`. Added
2026-09-23 as Step 17. Each sends one write through `send_write`, sent once and never retried,
under the behavior's write spacing, budget and stop: `usePolarisFollowUserFollowMutation` or
`usePolarisFollowUserUnfollowMutation`, whose one variable is `target_user_id`, the account's
numeric id, `Profile.id`. A username raises `ValueError` before anything is sent, and an answer
echoing another account's id raises `SchemaChanged`. The relationship read is not a new method.
`profile_by_id` already reads it: `Profile` gained `friendship_status: FriendshipStatus | None =
None`, None on the viewer's own profile, and `FriendshipStatus` carries ten booleans, among them
`following`, `followed_by` and `outgoing_request`. That was additive, one field line and a new
class, per 17.7 in [build-plan.md](build-plan.md). `follow` returns no state because its answer
selects `following` alone, and a follow of a private account becomes a request that leaves it
false, so a follow answered false is not raised and the docstring names `profile_by_id` and
`friendship_status.outgoing_request` as the read that says which it was. That read also
reconciles `OutcomeUnknown` for both. An unfollow always ends with `following` false, so one
answered true raises `UpstreamRejected` with code `following_did_not_end`. On a public account the
follow, the unfollow and each read after them were observed; the private account's request, and
whether an unfollow withdraws it, were not. The same step made `profile_by_id` read accounts other
than the viewer's: another account's profile carries `is_professional_account`,
`has_profile_pic` and `has_story_archive` as null, which the mapper had refused, and a null on
those three is now read as the field's own default. Since W92, another account with no reels
carries `total_clips_count` as a non-integer, INFERENCE null, which reads as 0 on that frozen
`int` field and as `None` on `Profile.reported_clips_count: int | None = None`, the count as
sent; an absent key or any other type still raises. What a browser sends around a follow is
unrecorded under ruling 23, so each write is sent alone, a departure recorded in
[web-request-contract.md](web-request-contract.md).

`send_message(thread_fbid, text) -> SentMessage` and `unsend_message(thread_fbid, message_id) ->
None` have no setting either. Added 2026-09-23 as Step 18. `send_message` sends
`IGDirectTextSendMutation` once through `send_write` with the fourteen variables the browser's
composer sent, keyed on the thread's `thread_fbid` as `ig_thread_igid`, the value
`thread_messages` takes, and carrying an `offline_threading_id` the client generates fresh per
call exactly as the browser does. It returns `SentMessage`, a new model with `id`,
`thread_fbid`, `sent_at` and `offline_threading_id`, rather than the `Message` the plan proposed,
because the answer carries the message id and its timestamp and nothing else: the sender's
`fbid` on a thread read is the viewer's Facebook-side messaging id, which is neither `ds_user_id`
nor `Session.actor_id`, so a `Message` built from the answer would have to guess it. `Message`
gained `offline_threading_id: str | None = None`, which the thread read echoes, so the message a
returned send created is found exactly. After `OutcomeUnknown` the identifier is not known to the
caller, and the docstring names the newest page of `thread_messages`, matched on the viewer's
own message with the same text after the attempt began, ambiguous when the same text went twice.
Empty text, and a thread id that is not digits or is the 39-digit `thread_id`, raise
`ValueError` before anything is sent. A send into a thread that does not exist takes
`recipient_igids` instead and is not built. `unsend_message` sends
`IGDMessageUnsendDialogOffMsysMutation`, which names the thread by its 39-digit `thread_id`, an
identifier no message carries. So it opens the thread first with `IGDThreadDetailQuery`, a read
that may recover a stale token, and then sends the write once: two requests. An answer of false
raises `UpstreamRejected` with code `message_not_unsent`, and a message id that is not a `mid.`
string raises `ValueError` before anything is sent. The unsent message was absent from the next
thread read, with no placeholder. All of it is additive: four method lines, two aliases, one class
of four fields and one `Message` field line, per 17.7 in [build-plan.md](build-plan.md). What a
browser sends around a send, a mark read, its validation and a thread refetch, is a recorded
departure in [web-request-contract.md](web-request-contract.md).

`page_load_companions` decides whether a document load also sends the queries a browser's page
load sends beside its own. It applies to the three routes that load a document, the home document
under `FeedFirstPage.DOCUMENT`, the profile page under `ProfileRoute.PAGE` and the direct inbox
under `InboxRoute.PAGE`. After the inbox's direct block it sends the badge count, the stories tray,
the login interstitial quick promotion call, one `IGDThreadDetailQuery` for each row of the first
page, pinned threads first, and the pending follow requests with the activity feed, up to
nineteen; the inbox load sends no chat tabs jewel or omni picker, and `news/inbox_seen` is never
sent (W88, W89). True, the parity
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
so a client from `with_behavior` shares them with its owner. A client from `from_session_file`
keeps the budget and the stop in a pacing ledger beside the file, `<path>.ledger`, so every
client and every process built from that file shares them, and the stop stays until a person
lifts it. A client built over a bare `Session` keeps them in memory, as before.
`dumpstagram.session.clear_write_stop(path)` is how a person lifts that stop: it clears the
stop in the ledger beside the session file at `path`, keeps the hour's departures, returns
whether a stop was set, and raises `SchemaChanged` without changing anything when the ledger
cannot be read. It is for a person who has looked at the account, never for a program that
wants its writes back. See [rate-limiting-and-safety.md](rate-limiting-and-safety.md). No setting makes the engine retry
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

## Domain namespaces

Landed 2026-09-23, E1 item 4 of [web-parity-plan.md](web-parity-plan.md), rulings W1, W19, W20
and W21. Both clients carry five namespace properties, and every capability from here on is
added to one of them rather than to the client:

```python
page = client.direct.messages(thread_fbid)                 # sync, returns Page[Message]
page = await aclient.direct.messages(thread_fbid)          # async, same result
profile = client.profiles.by_username("someone")
client.media.like(post.pk)
```

| Property | Awaitable class | Blocking class | Covers |
|---|---|---|---|
| `account` | `AsyncAccount` | `SyncAccount` | The viewer's own pending follow requests, activity feed, saved posts and collections, and close friends list, read without marking or changing anything |
| `direct` | `AsyncDirect` | `SyncDirect` | Threads, sending and unsending, the inbox, the message requests, the unread counts, and the notes tray on the inbox |
| `feeds` | `AsyncFeeds` | `SyncFeeds` | The timelines, the explore grid, a place's header and posts, whether the home feed has new posts, the reels feed, and an audio's page |
| `media` | `AsyncMedia` | `SyncMedia` | One post by shortcode or pk, its likes and likers, its comments and their replies, the more posts from its author, downloading its renditions, and publishing and deleting the viewer's own |
| `profiles` | `AsyncProfiles` | `SyncProfiles` | Profiles, a profile's posts grid, reels and tagged tabs, highlights tray, followers, following and the followers it shares with the viewer, and the suggested accounts |
| `search` | `AsyncSearch` | `SyncSearch` | The viewer's recent searches, what the search box offers for a query, the accounts a query matches, a hashtag's header, and the keyword grid, which is also a hashtag's posts |
| `social` | `AsyncSocial` | `SyncSocial` | Follows |
| `stories` | `AsyncStories` | `SyncStories` | The stories tray, an account's live stories and one highlight, read without marking anything seen |

The classes are defined in `dumpstagram.namespaces.direct` and its siblings, one module per
namespace holding both twins, and are not re-exported. A namespace is reached through its
client and is not built directly: its `__init__` raises `TypeError`. A namespace appears with its
first capability, not before (W20), as `stories` did in E2 batch 5, `account` in E2 batch 6 and
`search` in E2 batch 8.
`events` stays on the client.

The seventeen flat methods of `1.0.0` stay for good. Each answers through its alias, with the
same parameters, the same defaults and the same return type:

| Flat method | Alias |
|---|---|
| `thread_messages` | `direct.messages` |
| `send_message` | `direct.send` |
| `unsend_message` | `direct.unsend` |
| `notes` | `direct.notes` |
| `set_note` | `direct.set_note` |
| `delete_note` | `direct.delete_note` |
| `feed` | `feeds.home` |
| `post` | `media.by_code` |
| `like` | `media.like` |
| `unlike` | `media.unlike` |
| `comments` | `media.comments` |
| `comment` | `media.comment` |
| `delete_comment` | `media.delete_comment` |
| `profile` | `profiles.by_username` |
| `profile_by_id` | `profiles.by_id` |
| `follow` | `social.follow` |
| `unfollow` | `social.unfollow` |

W1 named the timelines `feed` and the notes `notes`. Both were already flat methods whose lines
the additive freeze holds, so the timelines became `feeds` and the notes joined `direct` (W19).
A blocking namespace method names itself in the seam note, for example
`SyncClient.direct.messages`, so an exception says which of the two routes the caller took.

### Pagination iterators

Landed 2026-09-23, E1 item 5, rulings W23 to W25 of [web-parity-plan.md](web-parity-plan.md).
Every namespace read that returns a `Page` has an `iter_` companion on the same namespace, and
only there, with no flat twin:

| Page read | Iterator | Yields |
|---|---|---|
| `direct.messages(thread_fbid, *, after, newer_than_message_id)` | `direct.iter_messages(thread_fbid, *, limit, after=None, newer_than_message_id=None)` | `Message`, newest first |
| `direct.inbox(*, after)` | `direct.iter_inbox(*, limit, after=None)` | `DirectThread`, newest activity first |
| `feeds.home(*, after)` | `feeds.iter_home(*, limit, after=None)` | `FeedItem` |
| `feeds.reels(*, after)` | `feeds.iter_reels(*, limit, after=None)` | `Post`, a reel, in the feed's order |
| `feeds.explore_posts(*, after)` | `feeds.iter_explore(*, limit, after=None)` | `Post`, section by section, each section's featured posts first |
| `feeds.audio_clips(audio_id, *, after)` | `feeds.iter_audio(audio_id, *, limit, after=None)` | `Post`, a reel using the audio, in the page's order |
| `media.comments(post_pk, *, after)` | `media.iter_comments(post_pk, *, limit, after=None)` | `Comment` |
| `media.replies(post_pk, comment_id, *, after)` | `media.iter_replies(post_pk, comment_id, *, limit, after=None)` | `Comment`, oldest first |
| `profiles.posts(username, *, after)` | `profiles.iter_posts(username, *, limit, after=None)` | `Post`, newest first, pinned posts first |
| `profiles.followers(user_id, *, after)` | `profiles.iter_followers(user_id, *, limit, after=None)` | `ProfileSummary`, in the upstream's order |
| `profiles.following(user_id, *, after)` | `profiles.iter_following(user_id, *, limit, after=None)` | `ProfileSummary`, in the upstream's order |

```python
for message in client.direct.iter_messages(thread_fbid, limit=200):
   ...

async for item in aclient.feeds.iter_home(limit=50):      # no await on the call
   ...
```

`limit` is keyword-only and required, and counts items. The walk ends when that many have been
yielded or when a page says `has_next_page` is false, whichever comes first, and it never reads a
page it would not use, so `limit=0` sends nothing. `limit=None` reads to the end, which on the
home timeline may be never. A negative `limit` raises `ValueError` and a non-integer one
`TypeError`, at the call. An empty or short page that says more exist is followed, and one that
says more exist with no cursor raises `SchemaChanged`.

Each page is read by the namespace's own page method, so it is paced and sent exactly as a single
read, and one page at a time: nothing is read ahead of the caller and nothing runs concurrently.
`after` starts the walk from a cursor, and `iter_messages` sends `newer_than_message_id` on every
page. The awaitable iterator is a plain method returning an `AsyncIterator`, so `async for` takes
it directly. The blocking one reads each page on the shared loop thread, raises what the read
raised with a seam note naming the iterator, such as `SyncClient.feeds.iter_home`, and can be
closed or abandoned at any point without leaving a request in flight, because no page is read
until the caller asks for an item from it.

### The media model and downloads

Landed 2026-09-23, E1 item 6 of [web-parity-plan.md](web-parity-plan.md), rulings W26 to W29.
`Post` and `PostDetail` gained five fields, each with a default, so nothing that existed changed:

| Field | Type | Empty or `None` when |
|---|---|---|
| `videos` | `tuple[VideoRendition, ...]` | the post is not a video |
| `video_duration` | `float \| None`, seconds | the post is not a video |
| `has_audio` | `bool \| None` | the upstream sends null, on a photo and a carousel |
| `audio` | `MediaAudio \| None` | the post is not a reel |
| `carousel_children` | `tuple[CarouselChild, ...]` | the post is not a carousel |

`VideoRendition` carries `url`, `width`, `height` and `version_type`, the upstream's own
enumeration (101, 102 and 103 were seen, three per reel, all at one size). The duration comes from
the `mediaPresentationDuration` of the DASH manifest the payload carries, because the web payload
has no duration field. `MediaAudio` carries `kind` (`AudioKind.MUSIC` or
`AudioKind.ORIGINAL_SOUND`, named for the upstream slot that held it), `audio_id`, `title`,
`artist`, `is_explicit`, `should_mute`, and `artist_id` on an original sound only. A
`CarouselChild` is one slide with its own `media_type`, `product_type`, dimensions, `images`,
`videos` and `video_duration`, and no shortcode. No video slide has been seen live, so that case
is mapped by the reel's rules and gated only on a fixture built from a live reel.

```python
post = client.media.by_code(code)
smallest = min(post.videos, key=lambda rendition: rendition.width * rendition.height)
path = client.media.download(smallest, "reel.mp4")                 # returns the Path written
path = await aclient.media.download(post.images[0], "cover.jpg", overwrite=True)
```

`media.download(rendition, path, *, overwrite=False) -> Path` takes a `MediaImage` or a
`VideoRendition`, on the namespace only, with no flat twin. It is one fetch from Instagram's CDN
and no API request, so it takes no turn from the account's pacer, and downloads may run at once,
at most four connections per client. It sends no cookie. The body streams to a temporary file
beside `path` and is renamed onto it when complete, so a failure leaves nothing. A file already
at `path` raises `FileExistsError` before anything is sent unless `overwrite` is true, and one
that appears while the body arrives is not replaced either. A body that differs from the length
the CDN declared raises `TransportFailure`, and one with no declared length, which the CDN sent
once, is written as it arrives. A 4xx raises `NotFound`, since a rendition URL is signed and
expires (INFERENCE, no expired URL has been fetched), and reading the post again gives a fresh
one. A URL outside the `cdninstagram.com` hosts or not over `https` is refused before it is sent.

### Posting

Landed 2026-09-23, E1 item 9 of [web-parity-plan.md](web-parity-plan.md) and build plan Step 19,
rulings W37 to W40. Three methods on `media`, on both clients, with no flat twin:

| Method | Returns | Live requests |
|---|---|---|
| `media.publish_photo(image, *, caption="")` | `PublishedPost` | two writes, the upload and the publish |
| `media.publish_carousel(images, *, caption="")` | `PublishedPost` | one write per image and one publish |
| `media.delete_post(post_pk, code)` | `None` | one write |

```python
published = client.media.publish_photo("square.jpg")
detail = client.media.by_code(published.code)              # the read that confirms it
client.media.delete_post(published.pk, published.code)

published = await aclient.media.publish_carousel([first_bytes, "second.jpg"])
```

An image is a JPEG, as `bytes` or as a path. Anything else raises `ValueError` before anything
is sent, because only a JPEG upload has been observed, and converting is the caller's to do. The
width and height the upload declares are read from the file's own frame header. A carousel
needs at least two images, and its upper limit is the upstream's and unobserved. Nothing is sent
about a location, a tag, a collaborator or sharing elsewhere, and the caption defaults to empty.

`PublishedPost` carries `pk`, `id` (the `<pk>_<owner id>` form), `code`, `taken_at`,
`media_type` (1 for a photo, 8 for a carousel) and `upload_ids` in slide order. It is not a
`PostDetail`, because the publish answers with the private API's media object, a different shape
from the post read's. Read the post back with `media.by_code(published.code)`, which is the read
that confirms it is up.

Every upload and every publish goes through `send_write`: sent once, never retried, spaced by the
behavior's write spacing and counted against its write budget, so under `PARITY` a photo takes
about half a minute and a two slide carousel about a minute. When an upload applies and a later
write fails, the uploads that applied are orphaned. The exception raised is the one the failing
write raised, unwrapped, with a note beginning `posting:` that names the half that failed and
every upload id that applied. After `OutcomeUnknown` on the publish the post may be up, so read
the profile's `media_count` before publishing again. What an orphaned upload costs, and when it
expires, is UNRESOLVED.

`delete_post` takes the `pk` and the shortcode, because the delete names the post by its
`<pk>_<viewer id>` form and is sent from the post's page. Only the viewer's own post can be
deleted. A delete answered without `did_delete` raises `UpstreamRejected` with code
`post_not_deleted`. To confirm, read the post with `media.by_code`: on all five deletes the engine read back
the read of a deleted post was refused with `UpstreamRejected` code `1675030`, a generic query
error, and the profile's `media_count` fell back. That code carries no meaning of its own, so it
confirms a delete only after the delete answered `did_delete` true.

### The inbox, the message requests and the unread counts

Landed 2026-09-24, E2 batch 1 of [web-parity-plan.md](web-parity-plan.md), rulings W45 to W48.
Four methods on `direct`, on both clients, with no flat twin:

| Method | Returns | Live requests |
|---|---|---|
| `direct.inbox(*, after=None)` | `Page[DirectThread]` | one |
| `direct.iter_inbox(*, limit, after=None)` | iterator of `DirectThread` | one per page read |
| `direct.message_requests()` | `MessageRequests` | one |
| `direct.unread_counts()` | `UnreadCounts` | two |

```python
page = client.direct.inbox()
for thread in client.direct.iter_inbox(limit=50):
   if thread.is_unread:
      messages = client.direct.messages(thread.thread_fbid)

counts = await aclient.direct.unread_counts()              # UnreadCounts(inbox=1, pending=0, ...)
requests = client.direct.message_requests()                # MessageRequests(pending=(), spam=(), ...)
```

`DirectThread` carries `thread_fbid`, which `direct.messages` takes, `title`, `is_group`,
`participants`, `last_activity_at`, `last_message_id` and `snippet` from the newest message the
row carries, and the flags `is_unread`, `is_marked_unread`, `is_muted` and `is_pinned`. The rows
keep the upstream's order, newest activity first with pinned threads in place.
`ThreadParticipant` carries `user_id`, the numeric account id `profiles.by_id` takes, and
`username`, `full_name` and `is_verified`, and the viewer is never among them.

The cursor an inbox page hands out carries the mailbox id the next page is keyed on beside the
upstream's own cursor, so `after` takes only an `end_cursor` from `direct.inbox`, and anything
else raises `ValueError` before anything is sent (W46). `has_next_page` is the only terminator.

`is_unread` and the counts are the engine's reading of the rows, an INFERENCE: the upstream sends
each row's read receipts and no number, and a row counts as unread when it is marked unread or
the viewer's receipt is older than its last activity or absent. `UnreadCounts` holds `inbox` and
`pending`, each counted over the first page of its folder that an inbox load reads, and
`inbox_has_more` and `pending_has_more` say the folder has rows past that page. Muted threads
count (W47).

`MessageRequests` holds the pending and the spam folder as tuples, one page each, with the
upstream's `has_next_page` for each, since no query that reads a request folder further has been
observed. No request row has been seen, because the account had none; one is mapped as an inbox
row, and a row that differs raises `SchemaChanged`.

Nothing here opens a thread, so nothing is marked read to anyone, and no request thread is
opened, which would mark it seen to its sender (W43). Under the default behavior the inbox's first
page and the unread counts are read inside the inbox page load `inbox_route` describes, and the
thread details it prefetches mark nothing seen. Later pages and the message requests are each sent
alone, as a browser sends them when its thread list scrolls and its requests view opens.

### The profile tabs and the suggested accounts

Landed 2026-09-27, E2 batch 2 of [web-parity-plan.md](web-parity-plan.md), rulings W52 to W56.
Five methods on `profiles`, on both clients, with no flat twin:

| Method | Returns | Live requests |
|---|---|---|
| `profiles.posts(username, *, after=None)` | `Page[Post]` | one |
| `profiles.iter_posts(username, *, limit, after=None)` | iterator of `Post` | one per page read |
| `profiles.highlights(user_id)` | `HighlightTray` | one |
| `profiles.suggested(user_id)` | `tuple[ProfileSummary, ...]` | one |
| `profiles.suggested_for_you()` | `tuple[SuggestedAccount, ...]` | one |

```python
profile = client.profiles.by_username("an.account")
for post in client.profiles.iter_posts(profile.username, limit=36):
   print(post.code, post.like_count)

tray = client.profiles.highlights(profile.id)             # HighlightTray(highlights=(...), has_more=False)
beside = await aclient.profiles.suggested(profile.id)     # (ProfileSummary(...), ...)
for suggestion in client.profiles.suggested_for_you():
   print(suggestion.account.username, suggestion.reason)
```

The grid is keyed on the username and pages twelve posts at a time on `has_next_page` alone.
Its items are the home timeline's `Post`; on a grid `is_seen` is always False, because the
upstream sends null for it there (W53). An impossible username raises `NotFound` before anything
is sent.

`HighlightTray` holds the tray's first page as `highlights` and the upstream's
`has_next_page` as `has_more`, because the query that reads further has never answered (W54).
`Highlight` carries `id` (`highlight:<number>`), `title`, `cover_url`, `owner_id` and
`owner_username`. Reading the stories inside a highlight is `stories.highlight(highlight.id)`,
which under the default behavior marks its first item seen (W94).

`ProfileSummary` is one account as a list row shows it: `id`, the numeric account id
`profiles.by_id` takes, `username`, `full_name`, `is_verified`, `profile_pic_url`, and
`is_private`, `hd_profile_pic_url` and `friendship_status`, each `None` where the row does not
carry it. Rows of the suggested accounts list carry no `is_private`. `friendship_status` is a
`ListFriendshipStatus`, not a `FriendshipStatus`, because a list row carries eight of the
profile's ten flags: `following`, `outgoing_request`, `incoming_request`, `is_bestie`,
`is_feed_favorite` and `is_restricted` always, and `followed_by` and `blocking` where the list
sends them (W55). `SuggestedAccount` pairs a row with `reason`, the line the website shows under
it. Neither suggested list carries a cursor, so each tuple is the list as the upstream sent it.

`highlights` and `suggested` take the numeric account id and raise `ValueError` for a username
before anything is sent. A browser reads the first grid page and the tray inside the profile page
load and the suggested list inside the page that lists it; each method here sends its one query
alone, and the tray and the suggestions beside a profile carry the site root as their referer,
departures recorded in [web-request-contract.md](web-request-contract.md).

The same batch changed one thing every read shares: an answer whose `errors` array only names
fields inside data that answered is now returned, those fields null, rather than refused (W52).
A mapper that requires an errored field still raises `SchemaChanged`.

### Followers

Landed 2026-09-27, E2 batch 3 of [web-parity-plan.md](web-parity-plan.md), rulings W58 to W60.
Two methods on `profiles`, on both clients, with no flat twin:

| Method | Returns | Live requests |
|---|---|---|
| `profiles.followers(user_id, *, after=None)` | `Page[ProfileSummary]` | two, one with `follow_list_statuses` off |
| `profiles.iter_followers(user_id, *, limit, after=None)` | iterator of `ProfileSummary` | two per page read |

```python
from dataclasses import replace
from dumpstagram import PARITY

me = client.profiles.by_id(client.session.ds_user_id)
for account in client.profiles.iter_followers(me.id, limit=50):
   status = account.friendship_status
   print(account.username, status.following if status else None)

lean = client.with_behavior(replace(PARITY, follow_list_statuses=False))
page = lean.profiles.followers(me.id)                      # one request, every status None
```

The read is keyed on the numeric account id and raises `ValueError` for a username before
anything is sent. A page holds the accounts the upstream sent, twelve asked for, and its length
is the upstream's: a second page of seven still said more existed. `has_next_page` is the
upstream's `has_more` and `end_cursor` its `next_max_id`, which `after` sends back (W58). No last
page has been read, so `has_more` false ending the walk is an INFERENCE.

Each row is the batch 2 `ProfileSummary`, with `is_private` carried and no high resolution
picture. Its `friendship_status` comes from a second request the browser's follow list sends
beside each page, the viewer's relationship to every account on it, matched by account id. Those
statuses carry six flags and never `followed_by` or `blocking`, which read `None` (W59).
`Behavior.follow_list_statuses`, True in every preset, sends that request; False leaves it out,
halves the requests, and leaves every `friendship_status` `None`.

Only the viewer's own followers have been read. The list's referer is the site root rather than
the profile page, a departure recorded in [web-request-contract.md](web-request-contract.md).
Following landed with E2 batch 11a, below. Mutual followers have no method: no request for them
has been observed.

### Reels tab, tagged tab and following

Landed 2026-09-27, E2 batch 11a of [web-parity-plan.md](web-parity-plan.md), rulings W97 to
W100, from the capture night's findings. Four methods on `profiles`, on both clients, with no
flat twin, and three new models:

| Method | Returns | Live requests |
|---|---|---|
| `profiles.reels(user_id)` | `ProfileReels` | one |
| `profiles.tagged(user_id)` | `TaggedPosts` | one |
| `profiles.following(user_id, *, after=None)` | `Page[ProfileSummary]` | two, one with `follow_list_statuses` off |
| `profiles.iter_following(user_id, *, limit, after=None)` | iterator of `ProfileSummary` | two per page read |

```python
me = client.session.ds_user_id
tab = client.profiles.reels(me)
for reel in tab.reels:
   print(reel.code, reel.play_count, reel.like_count)

for post in client.profiles.tagged(me).posts:
   print(post.code, post.author_username)                # the account that posted it

for account in client.profiles.iter_following(me, limit=30):
   print(account.username)
```

Each takes the numeric account id and raises `ValueError` for a username before anything is
sent. `reels` and `tagged` read the tab's first page only, because no query that reads either
further has been observed; `has_more` on `ProfileReels` and `TaggedPosts` is the upstream's own
`has_next_page` and says when the tuple is not the whole tab, the `HighlightTray` pattern (W97,
W98). A reel is a `ReelThumbnail`, its own model: the tab's item carries the author's id and no
username, no caption, and a `play_count` that a `PostThumbnail` has no field for. A tagged post is
the strip's `PostThumbnail`, whose author is the account that posted it, not the one tagged.

`following` is `followers`' twin in every step: the list's REST page, twelve asked for, then the
relationship statuses of the accounts on it inside the same action, filling each row's
`friendship_status`. Its cursor is `next_max_id`, on this list a numeric offset as a string, `12`
then `24`, sent back as `max_id`. `Behavior.follow_list_statuses` governs both lists: False
leaves the statuses out of each (W99). The list is ranked by the upstream, and two first pages
read seconds apart held 11 of the same 12 accounts in a different order, so an offset walk may
meet an account twice or miss one; nothing here deduplicates, since dropping a repeat would hide
what the upstream sent.

**Mutual followers.** Landed 2026-09-27, E2 batch 11e, ruling W117.
`profiles.mutual_followers(user_id) -> MutualFollowers`, two requests, one with
`follow_list_statuses` off, reads the list a profile's "Followed by" line opens: its REST page,
`page_size` 12, then the relationship statuses of the accounts on it inside the same action, as
the browser's list sent them. `MutualFollowers` carries `accounts`, `ProfileSummary` rows read
from their string `id`, and `has_more`, true when the answer carries a `next_max_id`. Both
answers read, of 4 accounts and of 1, carried it null, so no later page has been read and there
is no cursor and no iterator, the `FollowRequests` pattern.

A browser reads each tab when it is clicked on the profile page, beside the suggested accounts
query, and opens the following and mutual followers lists from the profile page. Each method here sends its read alone
with the site root as its referer, departures recorded in
[web-request-contract.md](web-request-contract.md).

### Post depth

Landed 2026-09-27, E2 batch 4 of [web-parity-plan.md](web-parity-plan.md), rulings W61 to W67,
and `media.page` with E2 batch 11d, W111 and W112. Six methods on `media`, on both clients, with
no flat twin:

| Method | Returns | Live requests |
|---|---|---|
| `media.replies(post_pk, comment_id, *, after=None)` | `Page[Comment]` | one |
| `media.iter_replies(post_pk, comment_id, *, limit, after=None)` | iterator of `Comment` | one per page read |
| `media.likers(post_pk)` | `tuple[ProfileSummary, ...]` | one |
| `media.by_id(post_pk)` | `PostDetail` | one |
| `media.more_from_author(author_id)` | `tuple[PostThumbnail, ...]` | one |
| `media.page(code)` | `PostPage` | the post page load, six with its companions |

```python
page = client.media.comments(post.pk)
threaded = next(comment for comment in page.items if comment.reply_count)
for reply in client.media.iter_replies(post.pk, threaded.id, limit=None):
   print(reply.author.username, reply.text)

likers = client.media.likers(post.pk)          # a sample on a popular post, not every like
strip = client.media.more_from_author(post.author.id)
detail = client.media.by_id(strip[0].pk)
```

**Replies.** The first page and every later one are two different queries, as the website sends
them, and `has_next_page` is the only terminator: the upstream decides a page's length, 9 and
then 11 replies came back for the same request. A reply is a `Comment` whose `parent_comment_id`
is the comment it answers and whose `reply_count` is `None`, because a reply carries no count of
its own (W61). The post pk and the comment id are digits, and anything else raises `ValueError`
before anything is sent.

**Likers.** Each account is a `ProfileSummary` with the viewer's relationship and all eight of its
flags. The answer has no cursor and no count, and on a popular post it is a sample: 98 accounts
for 193647 likes. Compare its length with `like_count` rather than read it as every liker (W62).

**A post by its pk.** `by_id` returns the `PostDetail` that `by_code` does, from an item that
carries less, and what it lacks is left empty rather than guessed: `carousel_children` is empty
while `carousel_media_count` still counts the slides, `accessibility_caption`, the author's
`hd_profile_pic_url` and `collaborators` are `None`, tags carry no position, and a reel's original sound, sent without its explicit flag, leaves `audio` `None`. `by_code` with the
returned `code` reads the rest (W63).

**More posts from the author.** The strip under a post is keyed on the author alone, so the method
takes the author's id and no post. Each item is a `PostThumbnail`: identifiers, kind, counts,
caption, slide count and renditions, and the author's id and username, because the upstream
sends nothing more, and `by_id` reads one in full. Six are asked for (W64).

**A post page.** `page(code)` loads the post page as a browser does and returns `PostPage`, every
part read out of the one document: `post`, the `PostDetail` `by_code` returns; `comments`, the
first page of comments with the upstream's terminator and cursor, whose next page `comments(pk,
after=...)` reads; and `author_grid`, the 7 posts of the author the page shows under it, which
held the post itself on both loads read, so it is not `more_from_author`'s strip. It loads the
page under every behavior, since loading the page is the read, and a document missing any part
raises `SchemaChanged` (W111). It is the parity way to read a post's first comments, because
`comments` is keyed on a pk and sends a query.

```python
page = client.media.page(code)
print(page.post.like_count, len(page.comments.items), len(page.author_grid))
```

**Location, tags and collaborators.** Every post read now carries three fields more, on `Post`
and `PostDetail`, and `user_tags` on each `CarouselChild` too:

| Field | Type | Meaning |
|---|---|---|
| `location` | `Location \| None` | `id`, `name`, `lat` and `lng`, or `None` when the post has none |
| `user_tags` | `tuple[UserTag, ...] \| None` | each tag's `account`, a `ProfileSummary` read by id, and its `position` as two fractions of the picture, or `None` where the read does not carry it |
| `collaborators` | `tuple[ProfileSummary, ...] \| None` | the accounts sharing the post with its author, each with the viewer's relationship |

A tuple is empty when the post has none, and `None` only when the read that produced the post
does not carry the field, which today means `by_id`'s collaborators (W65). The post modal's
context query backs no method (W66).

### Stories

Landed 2026-09-27, E2 batch 5 of [web-parity-plan.md](web-parity-plan.md), rulings W68 to W72,
and marking seen in E2 batch 12 the same day, rulings W93 to W95. The `stories` namespace, on
both clients, with no flat twin:

| Method | Returns | Live requests |
|---|---|---|
| `stories.tray()` | `tuple[TrayReel, ...]` | one, nothing marked seen |
| `stories.reel(user_id)` | `StoryReel \| None` | one, and one write marking the first item under the default |
| `stories.highlight(highlight_id)` | `StoryReel` | one, and one write marking the first item under the default |
| `stories.mark_seen(item, *, reel)` | `None` | one write |

```python
for row in client.stories.tray():
   print(row.ranked_position, row.owner.username, row.seen_at)

tray = client.profiles.highlights(profile.id)
highlight = client.stories.highlight(tray.highlights[0].id)
for item in highlight.items:
   print(item.taken_at, item.media_type, len(item.videos), [m.username for m in item.mentions])

live = client.stories.reel(profile.id)   # None when the account has no live story

client.stories.mark_seen(highlight.items[3], reel=highlight)
quiet = client.with_behavior(replace(client.behavior, mark_stories_seen=False))
unmarked = quiet.stories.reel(profile.id)   # read, nothing marked
```

**Reading a story through the engine marks it seen, and the story's owner sees you.** Since E2
batch 12, under the default behavior, `stories.reel()` and `stories.highlight()` follow the read
with `PolarisStoriesV3SeenMutation` for the reel's first item, the item a browser's story viewer
shows and marks when it opens, so reading another account's live story or highlight puts you in
that item's seen list exactly as opening it on the website does (W6, W94). Only the first item
is marked, because a read returns every item at once and a person has seen only the first;
`stories.mark_seen(item, reel=reel)` marks any other. The mark is a write: it waits out the write
spacing, counts against the write budget, is sent once and never retried, and when it fails its
error is raised and the reel is not returned. `Behavior.mark_stories_seen=False` reads without
marking and changes nothing else. `stories.tray()` never marks anything, as a browser's tray does
not.

**Marking one item.** `stories.mark_seen(item, *, reel)` takes a `StoryItem` and the `StoryReel`
it was read in: the reel's id and the item's owner, pk and time posted are what the mutation
carries, so an item that is not in `reel.items` raises `ValueError` before anything is sent. A
connection failure in flight raises `OutcomeUnknown`, and an answer with no seen response raises
`UpstreamRejected` with code `story_not_marked_seen`. The answer is its only confirmation, since a
highlight read carries no seen state; a live reel's is the tray row's `seen_at` (W93). Verified on
the owner's own highlight; a live reel's mutation is INFERENCE from the same finding.

**The tray.** One `TrayReel` per account with live stories, in the tray's order: the `owner` (a
`StoryOwner` with a high resolution picture and no verified or private flag), `latest_item_at`,
`expiring_at`, `seen_at` (`None` when nothing has been seen), `ranked_position`, `muted` and
`has_close_friends_items`. It carries no items; `stories.reel(row.owner.id)` reads them (W69).

**A reel and a highlight.** One query serves both. `reel` takes the numeric account id and
returns `None` when the account has no live story; `highlight` takes `Highlight.id`, the
`highlight:<number>` form, and raises `NotFound` on an answer with no reel. Anything else raises
`ValueError` before anything is sent. A `StoryReel` carries `id`, `reel_type`, the `owner` (with
its verified and private flags and no high resolution picture), `latest_item_at`, `can_reshare`,
its `items`, and a highlight's `title` and `cover_url`. A `StoryItem` carries its identifiers and
shortcode, `owner_id`, `media_type` and `product_type`, `taken_at` and `expiring_at`, its size,
`images` (`MediaImage`), `videos` (`StoryVideo`: `url` and `version_type` only, since a story
rendition carries no dimensions), `video_duration`, `has_audio`, `audience` (`besties` for close
friends), four flags, its `mentions` (`StoryMention`) and `music` (`StoryMusic`) stickers, and
`shared_media` (`StorySharedMedia`: `id`, `code`, `product_type`), the post or reel the item
shows, which `media.by_code` reads. One live reel of another account has been read: its `title`
and `cover_url` are `None`, and its one item carried the highlight items' keys (W121).
`media.download` is typed for `MediaImage` and `VideoRendition`, so a story's image downloads
through it and a `StoryVideo` has no typed download yet.
The stories gallery query backs no method (W71).

### The viewer's own account

Landed 2026-09-27, E2 batch 6 of [web-parity-plan.md](web-parity-plan.md), rulings W73 to W76,
E2 batch 11c, rulings W105 to W109, and E2 batch 11d, ruling W110. The `account` namespace, on
both clients, with no flat twin:

| Method | Returns | Live requests |
|---|---|---|
| `account.follow_requests()` | `FollowRequests` | one |
| `account.activity()` | `ActivityFeed` | one, plus a bootstrap when the session holds no token |
| `account.saved()` | `SavedPosts` | one |
| `account.collections()` | `SavedCollections` | one, plus a bootstrap when the session holds no token |
| `account.close_friends()` | `tuple[ProfileSummary, ...]` | one, plus a bootstrap when the session holds no token or no Bloks version id |
| `account.blocked()` | `tuple[BlockedAccount, ...]` | two in one action, plus a bootstrap when the session holds no token or no Bloks version id |

```python
waiting = client.account.follow_requests()
for account in waiting.accounts:
   print(account.id, account.username)

feed = client.account.activity()
for item in feed.items:
   print(item.created_at, item.kind, item.text, [link.username for link in item.links])
```

**The follow requests.** `FollowRequests` holds the first page as `accounts`, `ProfileSummary`
rows with no relationship, and `has_more`, true when the answer carries a `next_max_id`. Only a
private account receives requests. No next page has been observed, so nothing reads one, the
`MessageRequests` pattern of W45 (W73).

**Reading the activity feed through the engine does not mark it seen.** A browser opening the
notifications page follows the read with a second request that clears the viewer's own
notifications badge, which nobody else sees. That request has never been sent or observed
answering, so the engine sends none, a named departure from browser parity with no `Behavior`
setting yet (W74). The read itself may move `last_checked_at` (INFERENCE).

**The feed.** `ActivityFeed` holds `new_items`, `earlier_items` and `priority_items`, each newest
first, and `items` joining them; the fifteen `counts` (`ActivityCounts`); the `sections` the
page heads parts of the feed with (`ActivitySection`: `title`, `first_index`);
`last_checked_at`; and `is_last_page`, the upstream's flag. No next page is read. An
`ActivityItem` carries `id`, `kind` (the upstream's name, such as `story_like`, `post_like`,
`user_followed` or `comment_like`), `story_type`, `created_at`, the line as `text` with the
accounts it names as `links` (`ActivityLink`: `start`, `end`, `kind`, `id`, `username`, where
`text[start:end]` is the username), the thumbnails it shows as `media` (`ActivityMedia`: `id`,
`shortcode`, `image_url`), and where the item carries them the main and second account, the
account a follow button acts on with the viewer's relationship to it (`follow_account`), a
`comment_id` and the upstream's app route as `destination`. Only earlier items have been read;
new and priority items are ASSUMED to share their shape. The archive and the notifications badge
are not read yet.

**Saved posts.** `saved()` reads the first page of the saved "All posts" view, `SavedPosts` with
`posts` in the upstream's order and `has_more`, the upstream's `more_available`. No next page has
been observed, so there is no cursor and no `iter_saved` (W105). A `SavedPost` is the explore
grid's REST post without `comment_count`, which the view never sends, and without `is_seen`;
`media.by_code` with its `code` reads the whole post. A saved advertisement carries no
`like_and_view_counts_disabled`, so it is `None` there. Every post read was a video.

```python
saved = client.account.saved()
for post in saved.posts:
   print(post.code, post.author.username, post.product_type)
```

**Saved collections.** `collections()` reads the saved tab, `SavedCollections` with
`collections` and `has_more`, the page's `has_next_page`. A `SavedCollection` carries `id`, the
upstream's `collection_id`, `name`, `kind` (`SavedCollectionKind.ALL_POSTS`, `AUDIO` or `OTHER`),
`media_count`, `None` on the audio collection, and its `covers` (`CollectionCover`: `media_id`
and every rendition's URL, or an audio thumbnail with no `media_id`). The account read had only
the two automatic collections, so a collection the viewer named reads as `OTHER` until its type
is observed (W106).

**Close friends.** `close_friends()` returns the accounts on the viewer's close friends list, in
the order its settings screen lists them, as `ProfileSummary` rows with no privacy flag and no
relationship. The screen answers as a Bloks UI tree rather than a list, and the rows are found in
it by structure; a tree laid out differently raises `SchemaChanged` rather than returning a
partial or wrong list. Nothing is changed: the page's own count update action, whose effect is
unknown, is not sent (W107).

```python
for account in client.account.close_friends():
   print(account.id, account.username)
```

**Blocked accounts.** `blocked()` returns the accounts the viewer has blocked, in the order the
blocked accounts settings screen lists them. It sends what that page sends on load: the screen's
Bloks fetch, then the action the screen's answer names for the list, with the two container ids
that answer carries, in one action. A `BlockedAccount` carries `id`, `username`, `is_verified`,
`profile_pic_url`, `is_auto_blocked` and `secondary_text`, the line the screen shows under the
username. That line is the account's full name on a row blocked by hand, and on a row with
`is_auto_blocked` it is the screen's own line saying the block includes the person's other
accounts, so it is not read as a name (W110). A screen or list laid out otherwise raises
`SchemaChanged`. Nothing is blocked or unblocked.

```python
for entry in client.account.blocked():
   print(entry.id, entry.username, entry.is_auto_blocked)
```

### Discovery

Landed 2026-09-27, E2 batch 7 of [web-parity-plan.md](web-parity-plan.md), rulings W77 to W81.
Four methods on the `feeds` namespace, on both clients, with no flat twin:

| Method | Returns | Live requests |
|---|---|---|
| `feeds.explore(*, after=None)` | `ExploreGrid` | one |
| `feeds.place(location_id)` | `Place` | one, plus a bootstrap when the session holds no token |
| `feeds.location(location_id, *, tab=LocationTab.RANKED)` | `LocationPosts` | one, plus a bootstrap when the session holds no token |
| `feeds.has_new_posts()` | `bool` | one, plus a bootstrap when the session holds no token |

```python
grid = client.feeds.explore()
for post in grid.posts:
   print(post.code, post.author.username, post.video_duration)

tagged = next(post.location for post in grid.posts if post.location is not None)
place = client.feeds.place(tagged.id)
page = client.feeds.location(tagged.id)
print(place.name, place.media_count, len(page.posts), page.has_more)
```

**The explore grid.** `ExploreGrid` holds `sections` and `more_available`, the upstream's flag
that the grid goes on, and `posts` joins every section's posts. An `ExploreSection` carries
`feed_type`, the `featured` posts of its large tile and the smaller tiles' `posts`. Every post is
a `Post`, read from the grid's REST media shape: keys that shape leaves out where the timeline
sends null read as null, and `is_seen` is always False, since the grid never sends it (W77).
Since E2 batch 11e the grid pages (W115): `end_cursor` is the answer's root `max_id`, passed back
as `explore(after=...)`, and `more_available` is the only thing that ends a walk; it was true on
every page read. A later page lays each section out as one list of tiles rather than two blocks,
read into the same `featured` and `posts`. `feeds.explore_posts(*, after=None) -> Page[Post]` is
the same read as a plain page of posts, the page `feeds.iter_explore(*, limit, after=None)` walks,
because every iterator walks a read returning `Page` (W23); the two methods take each other's
cursors.

**A place.** `location_id` is the place's numeric `pk`, the `Location.id` a tagged post carries,
and anything but digits raises `ValueError` before anything is sent. `Place` carries `id`,
`name`, `category`, `lat`, `lng`, `media_count`, `slug`, `address`, `city`, `zip_code`, `phone`
and `price_range`, the strings as the upstream sends them, empty where the place has none (W78).
`LocationPosts` is the first page of the place's grid as `posts` and the upstream's `has_more`.
Its posts are `PostThumbnail`, because the grid sends no author's full name; `media.by_code`
reads a whole post. The query that pages the grid answered the cursor it was sent, so no later
page is read and there is no `iter_location` (W79). `LocationTab` has one member, `RANKED`, the
only tab observed.

**New posts.** `has_new_posts()` returns the upstream's flag for whether the home feed has posts
newer than the viewer last loaded; only `False` has been observed (W80).

**The reels feed.** Landed 2026-09-27, E2 batch 11b, ruling W101. `feeds.reels(*, after=None) ->
Page[Post]` reads one page of the `/reels/` tab, one request, plus a bootstrap when the session
holds no token, and `feeds.iter_reels(*, limit, after=None)` walks it reel by reel.

```python
page = client.feeds.reels()
for reel in page:
   print(reel.code, reel.author.username, reel.video_duration)

for reel in client.feeds.iter_reels(limit=30):
   ...
```

The first page asks for 2 reels and a later one for 10; measured pages carried 1, 2 and 4, and
the walk stops only on `has_next_page`. The next page names the reels already shown, as a
browser's does, so a page's `end_cursor` carries the upstream's cursor and the pks of that page's
reels; it is opaque, and a cursor from anywhere else raises `ValueError` before anything is sent.
The feed is ranked, so two walks do not see the same reels. Each reel is a `Post`: `is_seen` and
`is_paid_partnership` read False and carry no information, since the feed sends neither; the
author's `hd_profile_pic_url` and the post's `collaborators` are `None`, not carried; and a reel
whose original sound comes without the mute flag, which every one read did, has `audio` `None`,
while a song is read. A reel tagged at a place the feed sends without coordinates, only its
name and pk, has `location` `None` and names the place in `tagged_place`, a `TaggedPlace(id,
name)` every post read now carries wherever the node names a place (W120). A browser plays each reel, reports each view and asks for advertisements to
place between them; the engine plays nothing and sends neither, so nobody sees the viewer as
having watched a reel.

**An audio's page.** Landed 2026-09-27, E2 batch 11e, rulings W116 and W118.
`feeds.audio(audio_id, *, after=None) -> AudioPage` reads one page of the `/reels/audio/<id>/`
page, one request, plus a bootstrap when the session holds no token;
`feeds.audio_clips(audio_id, *, after=None) -> Page[Post]` is the same read as a plain page of its
reels, and `feeds.iter_audio(audio_id, *, limit, after=None)` walks them.

```python
reel = client.feeds.reels().items[0]
page = client.feeds.audio(reel.audio_id)
print(page.audio.title if page.audio else None, page.clips_count)

for clip in client.feeds.iter_audio(reel.audio_id, limit=36):
   print(clip.code, clip.author.username)
```

`audio_id` is the track's numeric id and anything but digits raises `ValueError` before anything
is sent. Every `Post` read from a payload that names its track now carries it as
`Post.audio_id`, a song's `audio_cluster_id` or an original sound's `audio_asset_id`, including a
reels feed reel whose `audio` is `None` (W118); `MediaAudio.audio_id` is the same value where
`audio` is read. `AudioPage` carries `audio`, the track as a `MediaAudio`, `clips_count`,
`is_restricted`, the page's `clips` as `Post`, `more_available` and `end_cursor`. A song's later
pages send no track and a count of 0, so `audio` is `None` there and only a first page's
`clips_count` is a count. A song's page carried 12 reels a page. `more_available` is the only
thing that ends a walk, and it can say true when nothing follows: a one-reel original sound said
true and its next page was empty and said false, in the browser and on both replays, so reading
such a page to its end costs one read that returns nothing (W116). A reel on this page carries
no `hd_profile_pic_url` for its author, `is_seen` False, and `collaborators` `None`, since the
page's collaborator rows carry a relationship without the two request flags. A browser loads the
audio page's document first; this sends the page's own read alone, with that page as referer, a
departure recorded in [web-request-contract.md](web-request-contract.md). Nothing is played.

### Search

Landed 2026-09-27, E2 batch 8 of [web-parity-plan.md](web-parity-plan.md), rulings W82 to W85,
and E2 batch 11b, rulings W102 to W104. Five methods on the `search` namespace, on both clients,
with no flat twin:

| Method | Returns | Live requests |
|---|---|---|
| `search.recent()` | `tuple[RecentSearch, ...]` | one, plus a bootstrap when the session holds no token |
| `search.top(query)` | `SearchResults` | one, plus a bootstrap when the session holds no token |
| `search.accounts(query)` | `tuple[ProfileSummary, ...]` | one, plus a bootstrap when the session holds no token |
| `search.hashtag(tag)` | `Hashtag` | one, plus a bootstrap when the session holds no token |
| `search.keyword(query)` | `KeywordResults` | one, plus a bootstrap when the session holds no token |

```python
for entry in client.search.recent():
   if entry.kind is RecentSearchKind.ACCOUNT:
      print("account", entry.account.username)
   elif entry.kind is RecentSearchKind.KEYWORD:
      print("keyword", entry.keyword)

for account in client.search.accounts("cats"):
   print(account.id, account.username, account.is_verified)

tag = client.search.hashtag("cats")
print(tag.name, tag.id)
```

**Recent searches.** Each `RecentSearch` carries its `kind` and, for an account, `account`, a
`ProfileSummary`, or, for a keyword, `keyword`, the text searched. `RecentSearchKind` names the
four slots the upstream declares, `ACCOUNT`, `KEYWORD`, `HASHTAG` and `PLACE`; a hashtag or a place
entry carries its kind and nothing else, because neither shape has been read (W82). The list is
whole as sent.

**Top results.** `top(query)` reads what the search box offers, as a signed-in browser's box
sends it, the first query of a search session of its own. `SearchResults.results` holds
`SearchResult` rows in the order the box shows them, by the upstream's `position`: each with its
`kind` (`SearchResultKind.ACCOUNT`, `KEYWORD`, `HASHTAG` or `PLACE`), an `account` or a `keyword`,
the suggested search text. One measured query answered a keyword at position 0 and five accounts
after it; hashtags and places were empty, so such a row carries its kind alone (W102).

```python
for result in client.search.top("cats").results:
   if result.kind is SearchResultKind.KEYWORD:
      grid = client.search.keyword(result.keyword)
   elif result.account is not None:
      print(result.position, result.account.username)
```

**Accounts.** `accounts(query)` returns the accounts of those rows, in the box's order, whole as
sent. Since E2 batch 11b it sends the personalised typeahead by default; before, it sent the
non-profiled one, which ranks without the viewer's profile and answered 18 accounts where the
personalised query answered 5. `Behavior.typeahead_route` set to
`TypeaheadRoute.NON_PERSONALISED` sends that query again, for `accounts` and for `top`, whose rows
are then accounts with no position (W102). A blank query raises `ValueError` before anything is
sent, on every search. A row carries no `is_private` and no relationship.

```python
plain = client.with_behavior(
   replace(client.behavior, typeahead_route=TypeaheadRoute.NON_PERSONALISED)
)
accounts = plain.search.accounts("cats")
```

**The keyword grid.** `keyword(query)` reads the first page of the grid the keyword page shows,
`KeywordResults` with `posts` and `has_more`, the upstream's flag that it goes on. No later page
has been observed, so there is no cursor and no `iter_keyword` (W103). Each post is a
`SearchPost`, the grid's own lighter shape: no `product_type`, no viewer state, no audio,
location or tags; `media.by_code` reads the whole post. A hashtag's page is this grid for the tag
with its `#`, so `keyword("#cats")` reads the posts under `#cats` and `hashtag("cats")` its
header; the `#` form was sent by the browser and has not yet been replayed by the engine.

**A hashtag.** `hashtag(tag)` takes the tag without its `#`, letters, digits and underscores; a
`#` or anything else raises `ValueError` before anything is sent. `Hashtag` carries `id`, the one
field the header answers, and `name`, the tag asked for (W84). The posts under a tag are
`keyword("#" + tag)`.

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
surfaces hold it instead.

Since E1 item 4 the suite walks the domain namespaces too. It discovers them as the public
properties whose type is a class in `dumpstagram.namespaces`, controls the discovery against
the snapshot, and holds each blocking namespace method to the same rules as a blocking
capability: same parameters and return type, not a coroutine, every argument forwarded on the
loop thread, and the seam note under its own dotted name. Each surface must hand out its own
namespace class. Two gates name capabilities, through tables that are the oracle rather than
anything read off the code: every flat method and its alias, each on a fresh client over a
recording transport, send the same requests and end the same way on both surfaces, and every
namespace method reaches the `_core` function its table row names, which the first gate cannot
see because a flat method answers through its alias. `verify_parity_gates.py` now breaks the
facades 26 ways. Since E1 item 5 the coroutine rules hold the namespace methods whose names do
not start with `iter_`, and five iterator gates hold the rest against `PAGE_METHOD_FOR_ITERATOR`:
the table matches what is discovered, every paged read has an iterator, both iterators take the
read's parameters plus a required `limit` and yield the read's item type, both forward every
argument and yield the same items from the same pages, and the blocking one raises under its own
name. `scripts/verify_iterator_gates.py` breaks them. See
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

A download's own file system failures are the builtin `OSError` family, `FileExistsError` for a
refused overwrite among them, because they are about the caller's disk rather than the upstream
(W29). Everything the CDN answers wrongly is one of the categories above.

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
