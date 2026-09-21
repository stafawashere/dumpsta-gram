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
