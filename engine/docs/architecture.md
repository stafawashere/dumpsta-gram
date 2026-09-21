# Architecture

How the library is layered, why the layers exist, and what each one is allowed to
know.

Decisions this implements:
[ADR-0001](../../docs/decisions/ADR-0001-async-core-sync-facade.md),
[ADR-0004](../../docs/decisions/ADR-0004-instance-scoped-sessions.md),
[ADR-0006](../../docs/decisions/ADR-0006-events-surface-polling-first.md).

## Layers

```
dumpstagram/
   __init__.py            public exports
   client.py              SyncClient, blocking facade
   aio.py                 AsyncClient, awaitable surface
   models/                typed boundary models
   errors.py              public exception hierarchy
   _core/                 async implementation, the real logic
      realtime/           event transport
   _private/              endpoints, signing, device, transport
```

What exists as of 2026-09-21, which is the target shape above minus everything Phase 2 brings:

```
dumpstagram/
   __init__.py            empty package marker
   py.typed
   errors.py              the full public exception hierarchy
   session.py             Session, SpinParameters, ProxyConfig, SCHEMA_VERSION
   _core/
      pacer.py            Pacer, PacingPolicy, BackoffPolicy, run_with_retries
      requesting.py       PacedSender, the one path a request leaves by
      smoke.py            read_one_thread_page, internal, no model and no public name
      loop_thread.py      _LoopThread, refcounted and shared, the seam and its note
      redaction.py        redact, RedactingFormatter
   _private/
      transport.py        Sender, Request, Response, HttpxTransport, cookies_for
      web/
         classify.py      classify, classify_checkpoint_only
         bootstrap.py     token harvest from one authenticated page
         documents.py     the persisted GraphQL query registry
         requests.py      the body and header set
```

No `client.py`, no `aio.py`, no `models/`, no `_core/realtime/`, and no capability. See
[web-request-contract.md](web-request-contract.md) for the `_private/web/` layer and
[build-plan.md](build-plan.md) for what comes next.

Each layer has a single job and a rule about what it may know.

**`client.py` and `aio.py`, the public surfaces.** Thin. They contain no logic beyond
argument validation and, for the sync facade, crossing into the loop thread. They know
about `_core` and `models`. They must never know an endpoint or a header.

**`models/`, the boundary.** Typed representations of everything that crosses the
public boundary. This is where upstream schema churn stops. A field that Instagram
renames is remapped here, and no consumer notices.

**`errors.py`, the error contract.** A public exception hierarchy. Callers catch these,
not transport exceptions and not `httpx` exceptions. Errors are part of the stability
promise.

**`_core/`, the implementation.** Every capability, written once, asynchronously.
Knows `_private`, `models`, and `errors`. This is where retries, pagination,
hydration fan-out, and the pacer live.

**`_private/`, the protocol layer.** Endpoints, request signing where a surface needs it,
client identity construction,
the HTTP transport, and response parsing into raw structures. Free to change in any
release. Nothing outside `_core` may import it.

## The public and private split is the stability mechanism

This split is not organizational tidiness. It is the answer to the central tension in
[overview.md](overview.md). Instagram's private API changes without notice, and the
library promises a stable surface. The only way both hold is if there is a layer whose
explicit job is to absorb change.

Consequences that follow from taking the split seriously:

- A caller can never receive a raw JSON dict, because that would leak upstream schema
  into the public surface. Typed models are mandatory from the first endpoint, not
  retrofitted later.
- A caller can never receive an `httpx` exception, because that would leak the HTTP
  library choice into the public surface.
- `_private` may be reorganized freely between releases. If a rename in `_private`
  forces a public change, the boundary was drawn in the wrong place.

## Request flow

A single public read call, end to end.

```
SyncClient.user_info("x")
   validates arguments
   run_coroutine_threadsafe onto the shared loop thread
AsyncClient.user_info("x")
   _core delegates to the capability implementation
   pacer decides when the request may leave
   _private builds the client-shaped request from the session's credential material
   transport sends it
   response parsed into a raw structure
   models maps it into a typed User
   returns back across the loop boundary
SyncClient returns a User
```

**`_core` is serial by default.** Revised 2026-09-20. An earlier version of this document
described one public call producing thirty concurrent requests and called that the point of
the async core. Measurement disproved it: the pacer spaces departures further apart than any
single request takes, so concurrency over paced API calls buys nothing and only makes the
traffic pattern harder to reason about. The async core stands on a different argument, which
is that only an async implementation can serve a blocking surface and an awaitable surface
honestly.

`asyncio.gather` is therefore reserved for work the pacer does not serialize: media and CDN
fetches, traffic belonging to different accounts, and work overlapping a long-lived
connection. A concurrent fan-out over paced API calls is a defect, not an optimization. See
[ADR-0001](../../docs/decisions/ADR-0001-async-core-sync-facade.md) and
[engineering/05-io-concurrency-and-pacing.md](engineering/05-io-concurrency-and-pacing.md).

## Ownership of state

All account state is instance state. Nothing is global. See
[ADR-0004](../../docs/decisions/ADR-0004-instance-scoped-sessions.md) and
[session-and-auth.md](session-and-auth.md).

| State | Owner |
|---|---|
| Credential material, device fingerprint where needed, cookies, tokens, proxy, checkpoint flag | `Session`, passed into the client |
| Pacer | Client instance, per account |
| Connection pool | Client instance, bound to the loop thread |
| Event loop thread | Shared refcounted singleton, holds no account identity |

The loop thread is the single piece of shared machinery, and it is shared precisely
because it carries no identity.

## The realtime subsystem is separate

`_core/realtime/` shares the session and the client identity with the REST client
and deliberately does not share the request pipeline. A persistent push connection has
keepalives, resubscribe-on-reconnect behavior, and a failure model unlike any REST
call's.

Drawing that boundary now prevents the predictable failure, which is transport logic
leaking into the HTTP layer and making both harder to reason about. See
[realtime-events.md](realtime-events.md).

## Invariants

- No module-level mutable state anywhere in the package.
- Nothing outside `_core` imports `_private`.
- Nothing public returns an untyped structure.
- Every outbound request passes the pacer. There is no bypass, including for the realtime
  listener's polling.
- The sync facade never creates or destroys an event loop.
- **Success is determined by the response body, never by the status code.** FACT-driven. Every
  failure mode observed on Instagram's GraphQL gateway arrived as HTTP 200 with an error
  envelope. A transport that branches on status alone reports success while returning nothing.
  See [session-and-auth.md](session-and-auth.md).
- A terminating condition comes from the server's own signal, never from a heuristic. The prior
  project's rule was that pagination ends on the server's explicit "no more pages" flag and on
  nothing else, because stopping on an empty or short page silently truncates, and a silent
  truncation is indistinguishable from a complete result once the process exits. Its reference
  thread's final page was short but not terminal, so the plausible heuristic would have been
  wrong.

## Evidence that this layering works

The prior JavaScript project used the same split, a generic session layer that knows HTTP, auth,
pacing, and retry, with resource classes above it that know endpoints, and pure record-mapping
functions off to the side with no network access.

Its load-bearing property is the one this design copies: the session layer contained no
domain-specific logic, so adding a capability was a resource method that inherited pacing,
retry, the checkpoint guard, and credential handling for free. It confirmed this empirically by
adding a REST inbox capability later with no transport changes at all.

The same project also demonstrated the cost of a shared data contract across tools. Three
separate programs wrote and read one export shape, which is what let a capture from one
implementation serve as the test oracle for a rewrite of another. The analogue here is the typed
model layer: it is not only a churn barrier, it is what makes cross-implementation comparison
possible at all. See
[../../docs/knowledge/prior-art-dumpsta-js.md](../../docs/knowledge/prior-art-dumpsta-js.md).
