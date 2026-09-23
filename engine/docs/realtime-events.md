# Realtime events

The listener surface, the event buffer, and the transport swap.

Implements [ADR-0006](../../docs/decisions/ADR-0006-events-surface-polling-first.md).
Inherited evidence, and the absence of it:
[../../docs/knowledge/prior-art-dumpsta-js.md](../../docs/knowledge/prior-art-dumpsta-js.md).
Bridge rules: [../../docs/bridge/threading-and-gil.md](../../docs/bridge/threading-and-gil.md).

## What makes this different from a fetch

Not concurrency. Lifetime.

A fetch starts and ends. A listener runs for hours, holds a connection, reconnects
after failures, and pushes data at the caller. That is a third surface shape, not a
third concurrency model. The async core serves both. See
[ADR-0001](../../docs/decisions/ADR-0001-async-core-sync-facade.md).

## Surface

Fixed now, deliberately, so the transport underneath can change later without touching
a single consumer.

```python
async for event in aclient.events():     # async consumers
   ...

listener = client.events(on_event=handler)   # sync consumers, including Swift
listener.start()
listener.stop()
```

### As landed, Step 22, 2026-09-23

The whole surface exists and is in `tests/public_surface.txt`. Step 23 put the polling
transport behind it, described under "As landed, Step 23" below, and changed one thing here:
`EventsDropped` gained `thread_fbid` and its `count` became optional.

```python
async def AsyncClient.events(self, *, since: str | None = None) -> AsyncIterator[Event]
def SyncClient.events(self, *, since: str | None = None,
                      on_event: Callable[[Event], None] | None = None) -> EventListener

class EventListener:              # dumpstagram.listener, built only by SyncClient.events
   def start(self) -> None
   def stop(self) -> None
   def drain(self) -> list[Event]
   def wait_for_events(self, timeout: float | None) -> list[Event]
   # a context manager that starts on entry and stops on exit

class Event                       # dumpstagram.models.events, the base, never delivered itself
class NewMessage(Event):      message: Message
class EventsDropped(Event):   count: int | None; thread_fbid: str | None = None
class ListenerStopped(Event): error: Exception
```

What each part promises, rulings 9, 14 and 26 in [build-plan.md](build-plan.md) section 17.13:

- **One event kind from the upstream**, `NewMessage`, carrying the existing `Message`. The
  viewer's own messages are included, so a consumer wanting only incoming ones compares
  `message.sender` with the viewer. `Event` is a base class rather than a union so that a kind
  added later is a new snapshot line, not a changed one.
- **`since`** is the id of the last message the consumer handled. The pump counts it as
  delivered already, and the source is built with it so the transport can catch up from it.
  Step 23 settled what it means across threads: the time of that message, see below.
- **Order and duplicates.** Each poll's messages are delivered oldest first by `sent_at`, so
  every thread's messages ascend. An id already delivered is not delivered again, remembered for
  the last 10000 ids.
- **The buffer** holds 1000 events, HYPOTHESIS for the number. Past that the oldest waiting
  event is dropped, and the next take starts with one `EventsDropped` saying how many went,
  with `thread_fbid` None.
  Both surfaces use it: the async iterator yields out of it, so a slow async consumer sees the
  same marker. A take is at most once.
- **Handler or buffer.** With `on_event` the listener calls the handler on its own thread,
  `dumpstagram-events`, never the loop thread and never the caller's, and `drain()` and
  `wait_for_events()` raise `RuntimeError`. A handler that raises is logged, redacted, and the
  next event is delivered.
- **Poll interval** is `Behavior.poll_interval_seconds`, 60 s by default, not an `events()`
  parameter. It is measured from the end of one poll to the start of the next, on the pacer's
  clock, and every request a poll sends passes the account's pacer on top of it.
- **Failure.** A poll runs under `run_with_retries`, so `TransportFailure` and `RateLimited`
  get account-wide backoff, and one that outlasts its retries costs that poll only. Anything
  else ends the listener. The async iterator re-raises the original object after the events
  before it. The blocking listener puts a final `ListenerStopped` whose `error` is that object,
  with a note naming the seam per ADR-0012, and then stops polling. `CheckpointRequired` also
  drops a pending cookie sync, as every capability does.
- **Lifecycle.** A blocking listener holds a reference to the shared loop thread from `start()`
  to `stop()`. `stop()` cancels the poll task, waits for it, joins the delivery thread and
  releases the reference, and is idempotent. A listener stopped by a failure has stopped polling
  and still wants `stop()` to let go of the loop thread. A listener starts once. Events buffered
  before `stop()` stay drainable. An async iteration stops polling when it is closed, at once
  under `contextlib.aclosing`, otherwise when the iterator is collected.

Where it lives: the models in `dumpstagram/models/events.py`, the listener in
`dumpstagram/listener.py`, and underneath, in `_core/realtime/`, the buffer (`buffer.py`) and
the pump with its source protocol (`pump.py`). A source is anything with
`async def poll(self) -> Sequence[Message | EventsDropped]`, built from a `SourceContext` holding
the client's paced sender, session, behavior, user agent and `since`. It makes one attempt per
poll and sends only through that sender. Each client carries the factory as `_event_source`,
which is `inbox_poller` from Step 23 on and which the gates replace with a scripted source. The
gates are listed in [engineering/gates.md](engineering/gates.md), sections "the listener surface
and buffer" and "the polling transport".

### As landed, Step 23, 2026-09-23

The transport is `InboxPoller` in `_core/realtime/poller.py`, on the first row of the Step 21
table in [build-plan.md](build-plan.md): one inbox listing request per poll, plus the reads of
each thread that changed.

- **What a poll sends.** `PolarisDirectInboxQuery` once, with one iris device id minted for the
  listener's lifetime. For each row whose newest message id differs from the previous poll's,
  `IGDMessageListOffMsysQuery` for the thread's newest page, then older pages by cursor until
  the message the listener last knew in that thread is reached, at most three pages. Nothing
  else: no `IGDThreadDetailQuery`, which is how a browser opens a thread, and no mark-read
  mutation, which the engine has no builder for. So no thread is marked seen, and a gate holds
  the set of friendly names a poll may send. Polling is a departure from parity under ADR-0013
  whatever the preset.
- **What decides a change.** The row's newest message id, not its activity marker. A marker
  that moves while the newest id stays put reads nothing: no message arrived, whatever moved it,
  a reaction being the INFERENCE.
- **Where the messages come from.** Always the thread read. A row carries its five newest
  messages, but each carries ten keys and lacks the sender object, the reactions,
  `thread_fbid`, `igd_is_forwarded`, `is_pinned` and `is_ai_generated`, measured on 75 of 75
  nodes in the inbox captures of `run-2026-09-23-022159` and `run-2026-09-23-045256`. A
  `Message` built from one would carry defaults nobody sent. The carried messages are used to
  place a message id in time, which is what `since` needs, and they bound the read: a known id
  among them means the first page covers the gap.
- **Where a read back stops.** At the known message, or at the first message older than the
  thread's previous activity marker, which is how a known message that was deleted still closes
  the gap, or at the thread's start. A message in the same millisecond as the known one counts
  as new unless it is that message. A thread that first appears on the listing's first page is
  read back to the newest activity the previous poll saw.
- **The first poll** records every row and delivers nothing, unless `since` was given.
- **`since`, settled.** The watermark is placed in time. The first poll looks for the id among
  the messages every row carries, and failing that reads the newest page of the first three
  threads in listing order, three requests at most. Found, its `sent_at` is the point: every
  listed thread whose activity is newer is read back to it, stopping in the watermark's own
  thread at the watermark itself and in every other at the first message older than it, and the
  page the search read is reused. Not found, the poll delivers one `EventsDropped` with `count`
  None and `thread_fbid` None, and the listener carries on from where the inbox stands. It
  does not raise: a consumer that was away long enough for its watermark to leave the newest
  twenty messages of the three busiest threads would otherwise have no way back in but to drop
  the watermark, and a marker says the same thing without stopping it.
- **Every gap is reported, none skipped.** `EventsDropped(count=None, thread_fbid=...)` stands
  before a thread's messages when three pages did not reach its known message, and
  `EventsDropped(count=None)` when the listing's last row is itself newer than the point being
  caught up from and more rows exist, since a thread below it may be newer too. `count` is None
  because the poller cannot know how many it missed. The pump emits a poll's markers before its
  messages.
- **One attempt.** A stale token is re-fetched once through `with_one_token_recovery` in
  `_core/tokens.py`, which has the judgement of `with_token_recovery` and no retry policy,
  because the pump's `run_with_retries` is already around the whole poll. A poll that fails part
  of the way through commits nothing, so the retry reads the same rows against the same state.
- **Cost.** One request a minute on a quiet inbox. A thread that gained up to about twenty
  messages costs one more, and the poller never costs more than one listing plus three pages
  per changed thread, all passing the pacer.

Two bounds are HYPOTHESIS: three pages per thread and three threads searched for `since`.

The reduced live acceptance of 2026-09-23 ran `dumpsta events --duration 150 --interval 60
--json --ids-only` once per surface through `probes/events_live.py`: three polls on each, every
request holding the account's pacer slot, every answer 200. On the blocking surface the three
listings were identical in length and nothing was printed. On the async surface the third
listing changed, one thread read followed, and two new messages in one thread were printed as
ids only, sent 49 s and 4 s before that poll by two different senders. Neither was arranged, and
the run did not establish whether either sender was the owner. Logs
`engine/logs/events-live-sync-2026-09-23-065330.json` and
`engine/logs/events-live-async-2026-09-23-065605.json`.

## Transport, now and later

**Now, polling.** Originally an ASSUMPTION that a REST inbox endpoint is suitable. Superseded on
2026-09-23 by the GraphQL listing below, see What the poll reads. Partially supported: the
prior project used `/api/v1/direct_v2/inbox/` successfully as a thread-resolution fallback, so
the endpoint exists, is reachable, and returns thread rows. FACT. Whether it is a good change
feed for new messages was never tested.

One inherited property makes it more attractive than it looked. That endpoint is REST, not a
persisted GraphQL query, so it has no `doc_id` to rotate. It is structurally the most durable
thing in the inherited protocol knowledge, and the prior project kept its REST fallback for
exactly that reason even though the primary path never failed.

**Later, push.** Believed to be MQTT over Facebook's push infrastructure. ASSUMPTION, and it
gained no evidence from the prior project, which never attempted realtime work of any kind. Zero
occurrences of `mqtt`, `fbns`, `realtime`, or `skywalker` anywhere in it. Roughly doubles the
reverse-engineering effort relative to REST alone. INFERENCE.

Since the observable surface is identical either way, the expensive half is deferred without
blocking the Swift app.

### What the poll reads, as of 2026-09-23

Steps 20 and 21 of [build-plan.md](build-plan.md) replaced the REST assumption with an observed
GraphQL listing, and the poll reads that instead. The REST route was not called: the
listing lacked nothing the listener needs. Its durability argument above still holds, since the
listing has a `doc_id` that can rotate, and it stays the fallback to reach for if it does.

- **The listing.** `PolarisDirectInboxQuery`, finding `direct-inbox-thread-list`, verified five
  times. Built by `build_inbox_listing_request` and mapped by `parse_inbox_listing` into private
  `InboxThread` rows. One request returns the first 15 threads. FACT.
- **Ordering.** Newest activity first, pinned threads at their activity position. FACT, three
  reads.
- **Activity marker.** `last_activity_timestamp_ms`, epoch milliseconds, equal to the newest
  listed message's `timestamp_ms` on 45 of 45 rows. FACT.
- **Last message id.** The first of five listed messages, newest first, in the `mid.$` form
  `Message.id` carries, so it can be handed straight to `newer_than_message_id`. FACT for the
  form. Whether that top-up filters is still untested.
- **Thread id.** The row's `thread_fbid`, which is the identifier `thread_messages` takes. The
  row's `thread_key` is a different value on one-to-one threads and is what a browser sends when
  it opens one. FACT.
- **Pagination.** `page_info` with `end_cursor` and `has_next_page`, but no cursor argument on
  the query itself. The listener reads the first page only, so a thread that has fallen off it
  and then gains a message reappears at the top, INFERENCE from the ordering.
- **No change, no noise.** Two reads 60 s apart with nothing done were identical in every row,
  and `iris_inactive_subscription_uq_seq_id` did not move. FACT, one observation. So the listener
  will not emit events for nothing, as far as this shows.

Still unobserved as an arranged experiment, and blocked on the owner sending one message by
hand (ruling 10): whether a thread that gains a message moves to the top with every other row
staying put, and whether `newer_than_message_id` returns exactly the new message.
`probes/inbox_change_feed.py --stage full` runs both. Step 23 chose the first row of the Step 21
table anyway, because it holds on the evidence there is and it does not use
`newer_than_message_id` at all: it diffs ids client side, which the third row of the table
prescribes when the top-up does not filter, and works whether it does or not. The unarranged
messages of the async acceptance run are one observation that a listing moves when a thread
gains messages: the third read changed length, and the thread read of the one row whose newest
id moved returned the two new messages. The run's log keeps ids and counts only, so whether the
other rows stayed put is not recorded.

### Incremental fetch makes polling much cheaper

FACT that the capability exists, inherited. The message paging query accepts a
`newer_than_message_id` variable. The prior project passed it as null and never used it, but
noted it as directly useful given its reference thread grew by 275 messages in under a day.

For a polling listener this is the difference between re-reading history and fetching only what
is new. The Step 23 poller does not use it yet, because its filtering is unobserved. Step 18 sent it with
a value once, on 2026-09-23: after a send into a thread whose only other message had been unsent,
with that unsent message's id as the base, it returned exactly the new message, `has_next_page`
false, no error. FACT for that one read. The thread listed nothing else, so the answer cannot
tell a filter from the newest page, and it only shows that an unsent message's id is accepted as
a base. It reads the newest page and diffs ids instead, which costs the same
one request whenever fewer than twenty messages arrived between two polls, and pages back only
when more did. Switching to the top-up is a change inside `poller.py` once Step 21 line 5 or
Step 18 has observed it.

Page size is capped at 20 server side regardless of what is requested, FACT, which makes the
saving larger still.

## Why the subsystem is separate

`_core/realtime/` shares the session and the client identity with the REST client
and does not share the request pipeline.

A push transport is a persistent socket with keepalives and resubscribe-on-reconnect
behavior. Its failure model has nothing in common with a REST call's. Drawing this
boundary before the push work starts prevents the predictable failure, which is
transport logic bleeding into the HTTP layer.

The boundary is drawn now even though the current implementation is polling, because
the polling implementation is the thing that would naturally be written inside the HTTP
layer if the boundary did not already exist.

## The event buffer

Events originate on the engine's asyncio loop thread. Consumers live elsewhere. The
library never calls back into consumer code across that boundary.

```python
class EventBuffer:
   def drain(self) -> list[Event]:
      """Pop all pending events. Safe to call from any thread."""
```

The consumer drains. Data crosses as plain values.

As landed in Step 22, `EventBuffer` is private, in `_core/realtime/buffer.py`, and a consumer
calls `drain()` and `wait_for_events(timeout)` on the `EventListener` that owns one. Keeping the
class private keeps its constructor and its capacity out of the frozen surface.

### Why not a callback

For Swift, handing PythonKit a Swift closure means arbitrary Swift code executing on a
Python-owned thread while holding the GIL. Expected outcome is deadlock or crash.
INFERENCE.

The broader benefit is that this keeps the library free of Swift-specific hooks, so it
stays equally usable from a plain script, a CLI, or a web backend. The bridge
constraint improved the library's portability rather than compromising it.

Note that `on_event=handler` in the sync listener is not a contradiction. That handler
runs on the listener's own delivery thread within Python, under the consumer's
control. It is a Python callback in Python, not a foreign callback across a runtime
boundary. A Swift consumer uses `drain()` instead.

### Drain strategies

- Poll `drain()` on a timer, on the order of every 200ms.
- Expose a blocking `wait_for_events(timeout)` that parks on the Python side and
  returns a batch, trading a parked caller for lower latency.

Both are acceptable. The choice is the consumer's.

## Budget

Listener traffic passes the pacer like everything else. While polling is the
transport, it competes directly with user-initiated requests, which is why the default
interval is conservative. See
[rate-limiting-and-safety.md](rate-limiting-and-safety.md).

## Risks

- If the push transport requires modelling that polling never needed, for example
  typing indicators or presence, the surface will have to grow. Growing it is fine.
  Changing existing semantics is not.
- UNRESOLVED whether the push transport can authenticate from the same session
  material as REST. If it cannot, the session object grows a realtime credential and
  Phase 1's persistence work has to cover it.
