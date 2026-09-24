# Rate limiting and account safety

The pacer, the backoff policy, and why all of it lives in the library rather than in the
application.

Revised 2026-09-20 with measured numbers inherited from
[../../docs/knowledge/prior-art-dumpsta-js.md](../../docs/knowledge/prior-art-dumpsta-js.md).
This document previously said the numbers were UNRESOLVED and could not be chosen honestly.
They are now anchored to real measurements.

Related: [architecture.md](architecture.md),
[../../docs/knowledge/risks-and-constraints.md](../../docs/knowledge/risks-and-constraints.md).

## Why this is a library concern

Dumpsta-App is open source and is meant to be copied from. An open-source client that ships
fast defaults teaches every downstream consumer to get its users banned.

Putting pacing in the application makes it optional. Putting it in the library makes it
structural. Every consumer, including a script someone writes in ten minutes, inherits safe
behavior without opting in.

This is a deliberate exception to the usual principle that application policy belongs to
applications.

## The pacer

One pacer per account, owned by the client instance, never global and never shared between
accounts. Limits are enforced per account upstream, so the control must be per account too. See
[ADR-0004](../../docs/decisions/ADR-0004-instance-scoped-sessions.md).

The pacer decides when a request is allowed to leave. Every outbound request passes it. There is
no bypass, including for the realtime listener's polling.

## Measured numbers

This section is the canonical home for the project's pacing numbers. Other documents cite them
and link here rather than restating the reasoning.

FACT unless noted. Source: roughly 650 live requests on 2026-09-21 by the prior project, plus
the in-browser script it was derived from.

| Client | Requests per second | Basis |
|---|---|---|
| Real web app, driven by an in-page script | 4.46 | Measured, 292 pages in 65467 ms |
| Prior request-only client, default | 0.351 | 2500 ms floor plus 350 ms mean jitter |
| Ratio | 12.7x slower than the browser | |

**No rate limit was ever observed.** Zero 429s and zero 5xx responses across the whole session,
covering a 33-request ablation probe at 3500 ms spacing, a 306-page export, a 60-plus-246-page
kill and resume, and assorted smoke tests.

That bounds the ceiling from below and says nothing else. Absence of a 429 across 650 requests
is weak evidence about where the limit actually sits, and finding it would mean deliberately
approaching it, which is not worth an account.

### The reasoning that produced the default, and why to keep it

This is the most transferable idea in the inherited material. **Pace against traffic the account
has already produced.** The browser script's 4.46 req/s is a far better reference point than a
guessed safe number, because that traffic already went through the real product from that
account without incident. Running an order of magnitude below a rate the account has already
sustained is a defensible argument. Guessing is not.

This project should derive its own defaults the same way: measure what the real client does for
a given operation, then run well under it.

### Page size is capped server side

FACT. Requesting 20, 50, and 200 edges each returned exactly 20. Raising the page size is wasted
effort, and a full thread costs one request per 20 messages. 6115 messages took 306 requests.

This matters for pacing because it makes request count a direct function of data volume, with no
tuning available. An operation's cost is predictable in advance, which is what makes a dry-run
cost estimate feasible.

## What is implemented, 2026-09-21

`dumpstagram/_core/pacer.py`. Build plan Step 6.

| Name | Shape | Notes |
|---|---|---|
| `PacingPolicy` | `floor_seconds=2.5`, `mean_jitter_seconds=0.35` | The measured pair above. Jitter is drawn uniformly over `[0, 2 * mean)`, so the mean gap is 2.85 s and the mean rate is 0.351 req/s |
| `BackoffPolicy` | `initial_seconds=4.0`, `multiplier=2.0`, `ceiling_seconds=120.0`, `max_attempts=5` | The inherited parameters. Still never observed to fire |
| `Pacer.slot()` | Async context manager | Waits for the account's next departure instant and holds one `asyncio.Lock` across both the wait and the caller's body |
| `Pacer.hold(seconds)` | Records an account-wide stop, does not sleep | This is what makes a backoff account-wide: every other task inherits it at its next slot |
| `Pacer.hold_for(seconds)` | Records and sleeps | Used by the retry helper, so an operation that never reaches a slot still pays its backoff |
| `backoff_delay(attempt, policy, retry_after)` | `4, 8, 16, 32, 64, 120, ...` | A larger upstream `retry-after` wins and is **not** clipped by the ceiling. The ceiling bounds what this library invents, not what the upstream explicitly asks for |
| `run_with_retries(operation, pacer, deadline)` | Retry loop | Catches `RETRYABLE` and nothing else, so `CheckpointRequired` cannot reach the backoff path. A backoff that would cross the caller's deadline is not taken and the last failure is raised instead |

The clock, the sleep, and the jitter source are injected. A pacer whose spacing can only be
observed by waiting several real seconds per assertion does not get tested, and the gate suite
would grow a lowered floor instead.

**Why `hold` and `hold_for` are separate.** They were one method that recorded and slept. On a
fake clock where sleeping advances shared time, the hold duration passes whether or not the
record was ever written, so no gate could distinguish an account-wide hold from a hold living in
one task's stack. Splitting them made the record independently observable. The full account is in
[../../docs/knowledge/session-archive-2026-09-21.md](../../docs/knowledge/session-archive-2026-09-21.md).

**Sharing contract.** A `Pacer` is sequentially reusable and task safe. It is not thread safe,
and it is bound to the loop its lock was first awaited on, which is the engine's loop thread.

**True since 2026-09-21.** Every request leaves through `PacedSender` in
`_core/requesting.py`, which is a `Sender` wrapping the real sender and the pacer. Code above it
receives the paced object and has no unpaced one to reach for, which is what closes the bypass:
the pacer being correct and the pacer being used are two claims, and only the second one decides
what departs. Both are gated, the second by a counting transport behind a `PacedSender` whose
spacing is asserted at the transport rather than at the pacer. See
[engineering/gates.md](engineering/gates.md).

## Backoff

Inherited parameters, exercised only in tests and never observed to fire against the live API:
exponential from 4000 ms, ceiling 120000 ms, honouring `retry-after` when it is larger, maximum
5 attempts.

Backoff applies account-wide rather than per-request. When the upstream says slow down, every
in-flight and queued request for that account waits.

A checkpoint or challenge triggers a full stop for the account, not a backoff, and it is never
retried. See [session-and-auth.md](session-and-auth.md).

## Probing is paced more conservatively than normal traffic

ASSUMPTION, inherited and untested. The prior project used 3500 ms spacing for deliberately
malformed ablation requests rather than its normal 2500 ms, on the reasoning that malformed
requests are more likely to be scored as abuse than well-formed ones.

Plausible and cheap. Worth keeping as a default posture for any diagnostic tooling this project
builds, while remembering it has no evidence behind it.

## Listener traffic is first-class traffic

While the realtime surface is backed by polling, the listener spends the same per-account budget
as user-initiated work. The pacer treats it identically. It is not free background activity.

Two consequences:

- The default poll interval is conservative, because it competes with the user's own actions.
- Replacing polling with a push transport returns budget to the application, which is a second
  reason to do it beyond latency.

An inherited idea makes this much cheaper in the interim. The paging query accepts a
`newer_than_message_id` variable, so a thread that has already been read can be topped up by
fetching only what is newer rather than walking history. The prior project never implemented it
and passed the variable as null. For a polling listener it is the difference between a constant
drip and a full re-read. See [realtime-events.md](realtime-events.md).

## Behavior configuration, 2026-09-23

ADR-0013 moved the default from a safe machine rate to browser parity, and made spacing a
per-client setting. `dumpstagram/behavior.py` holds `Behavior`, `Spacing` and three presets.
The pacer stays one per account. What changed is that each departure now names its own gap,
measured from the account's previous departure whichever client sent it, so a scoped client from
`with_behavior` shares the account's history rather than starting a second one.

| Preset | Spacing | Mean rate | What it costs |
|---|---|---|---|
| `PARITY`, the default | uniform 1.3 s to 5.3 s, mean 3.3 s | 0.30 req/s | Shortest gap is below the old 2.5 s floor, because a person paging a thread goes that fast. Mean rate is below the old default. Fitted to one minute of hand browsing, so provisional |
| `EXPORT` | uniform 2.5 s to 3.2 s, mean 2.85 s | 0.351 req/s | The rate a real account sustained over about 650 requests. Regular spacing no person produces |
| `FAST` | none | whatever the transport allows | No human reaches it and nothing has measured how the upstream treats it. Every request is still browser-shaped and still passes the pacer, and a throttle still holds the whole account |

The parity fit, FACT from `run-2026-09-23-005544`: 19 gaps between user actions over 60 s,
median 2.98 s, mean 3.37 s, shortest 1.33 s outside stories, longest 8.69 s. By action: older
thread page to next 1.33, 2.65 and 4.37 s; feed page to next 3.75, 4.95 and 5.01 s; profile to
profile 2.44, 2.98 and 8.69 s. One person on one day, ASSUMPTION beyond that. A uniform draw
cannot produce the long tail, so the 8.7 s gaps are missing from the model. Pooling more samples
and fitting a distribution per action kind is the next step.

Parity spacing is per action since 2026-09-23. `PacedSender.action()` takes one pacer slot for
a whole user action, so the requests inside it depart milliseconds apart as a page's do, and the
human gap falls between actions. The profile page is the first action built this way: one
document, then six queries sent together, seven requests in one slot. The pacer's lock is held
for the action, so nothing else on the account departs inside it, and a throttle still holds the
whole account. Every other capability is still one request per action. The concurrency inside
the slot is the carve-out in the 2026-09-23 amendment to ADR-0001.

A thread read stays one request per page. `ThreadFirstPage.DETAIL` and `ThreadFirstPage.QUERY`
cost the same request count, and the detail answer is about 42 kB against about 39 kB for the
same 20 messages from the scrolling query.

What the profile page costs, FACT from `probes/profile_page_route.py` on 2026-09-23 against the
viewer's own account: about 0.78 MB of document and 0.51 MB of answers, 474 kB of which is the
timeline query the page sends and the engine does not read. Another account measured in a
browser capture cost 1.51 MB of answers. `ProfileRoute.QUERIES` costs two requests and about
32 kB.

The page-load cookie sync is the one traffic that departs outside any slot, ruling 17 in
[build-plan.md](build-plan.md). After a document action succeeds, `_core/cookie_sync.py`
schedules four requests on the client's loop, two to www.facebook.com through the cookieless
transport and two to www.instagram.com, 4 to 10 s after the document departed, as twelve
captured loads sent them. They go through `BackgroundSender`, which waits while the account is
held for a throttle but takes no slot and records no departure, so the tail neither stalls the
user's next action nor sets the gap before it. A tail departs nothing once
`Session.checkpoint_active` is set, a checkpoint on any later call drops it, and a newer
document load or closing the client cancels it. `Behavior.cookie_sync` set to False sends none
of it.

## Write pacing, 2026-09-23

Step 13 of [build-plan.md](build-plan.md), before any write capability. Nothing about writes is
measured: no write rate, no human write timing, no failed write, no action block. So every
number below is a placeholder chosen to be cautious and derived from nothing, accepted as the
default in rulings 3 and 4, and each is a `Behavior` setting a caller may change.

| Setting | Default | What it does |
|---|---|---|
| `write_spacing` | 30 s floor plus 5 s mean jitter, uniform 30 s to 40 s | The gap before a write, measured from the account's previous write. About ten times the read spacing. A read between two writes leaves at the read spacing, and a write still keeps the read spacing from whatever went before it |
| `write_budget_per_hour` | 30 | Writes allowed to depart in any rolling hour. The next one raises `RateLimited` with `retry_after` set to when the oldest leaves the window, and sends nothing. None removes the budget, 0 refuses every write |
| `stop_writes_after_unrecognised_rejection` | True | After a write is rejected with a code nothing recorded explains, every later write raises `UpstreamRejected(code="writes_stopped")` without sending, for the life of the client. Reads carry on |

`PARITY` carries the placeholder spacing because no human write timing exists yet. When Step 12a
or a later sample measures one, the parity spacing becomes it and the budget stays either way.
`EXPORT` keeps all three defaults. `FAST` sets the write spacing to zero and keeps the budget and
the stop, because spacing is what it names.

Writes pass the same pacer and take the same slot as every request, through
`PacedSender.send_once` and `Pacer.write_slot`. The budget, the stop and the set of departed
write tokens are the pacer's, so they are per account: a client from `with_behavior` inherits
what its owner has spent and seen, and a zero spacing or a different budget on it changes only
how its own writes are judged. A refused write never departed, so it neither holds the account
nor counts against the budget.

A throttle on a write records an account-wide hold with `Pacer.hold` and raises. It does not
sleep and resend. The engine never retries a write on its own and no setting makes it, ruling
13, and `OutcomeUnknown` in [public-api.md](public-api.md) is what a caller sees when the
connection fails with a write in flight.

The stop's reasoning, ASSUMPTION: an unrecognised rejection of a write is the likeliest form an
action block takes, and repeating a blocked write makes it worse in other clients. What it costs
when wrong is one new client. The HTML application shell is excluded, because it means the page
token was refused, and the write path clears `fb_dtsg` so the caller's next call bootstraps.
Each write capability passes the codes its own verified finding explains.

## Media downloads are not API traffic, 2026-09-23

`client.media.download` fetches a rendition from `cdninstagram.com`, not from Instagram's API, and
takes no pacer slot, under the media and CDN exception of
[ADR-0001](../../docs/decisions/ADR-0001-async-core-sync-facade.md) (ruling W26 of
[web-parity-plan.md](web-parity-plan.md)). The pacer's anchors, 0.351 requests per second against
4.46 for a browser, were measured on the API gateway, and a browser fetches a page's images and
video segments from the CDN in parallel with its API calls. So a download neither waits for the
account's slot nor delays the next read, and several may run at once. What bounds them is the CDN
pool, four connections per client, the concurrency the prior project's browser script used. A
download sends no cookie and nothing identifying the account beyond the user agent and the
instagram.com referer, both as measured. Unmeasured: whether a burst of CDN fetches far beyond a
browser's is scored against the account at all. Five fetches in one evening say nothing about it.

## Defaults

Conservative. Consumers who know what they are doing can widen them, and the widening is
explicit and documented as a risk.

Anchor the first defaults to the measured pair above, roughly an order of magnitude below
observed real-client traffic for the same operation. Tighten from observed throttling, never
from experimentation designed to find the ceiling.

## What the library does not do

It does not promise safety. No pacing policy can, because the upstream rules are undocumented
and change. The library reduces obvious risk and documents the rest honestly.

Two things in particular are unmeasured and should not be assumed safe by analogy.

**Writes.** The prior project was read-only by hard constraint. Nothing sent, deleted, marked
read, or reacted. Every number on this page describes read traffic only, and write operations
are plausibly scored differently.

**Non-residential IPs.** Every measurement came from one residential connection on one day. A
datacentre or VPS address may be treated differently, including the finding that a plain HTTP
client is not blocked at all.
