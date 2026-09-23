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
GraphQL listing, and the poll will read that instead. The REST route was not called: the
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

Still unobserved, and blocked on the owner sending one message by hand (ruling 10): whether a
thread that gains a message moves to the top with its marker and last message id advanced while
every other row stays put, and whether `newer_than_message_id` returns exactly the new message.
`probes/inbox_change_feed.py --stage full` runs both. Until it does, the polling design is not
chosen from the Step 21 table, only the "changes with nothing done" row is ruled out.

### Incremental fetch makes polling much cheaper

FACT that the capability exists, inherited. The message paging query accepts a
`newer_than_message_id` variable. The prior project passed it as null and never used it, but
noted it as directly useful given its reference thread grew by 275 messages in under a day.

For a polling listener this is the difference between re-reading history and fetching only what
is new. Any polling implementation should use it from the start rather than filtering
client-side, because the cost difference is a full pagination walk versus one request.

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
