# Glossary

Project terminology. One term, one meaning. Use these names exactly, in code, in
documentation, and in commit messages, so that future sessions do not have to guess
whether two words mean the same thing.

## Products

**Dumpstagram**
The repository containing both products.

**Dumpsta-Engine**
The Python library in `engine/`. Package name `dumpstagram`. Holds all Instagram
capability. Every feature the system has lives here.

**Dumpsta-App**
The Swift macOS client in `client-app/`. Open source. Embeds Dumpsta-Engine and serves as its
flagship reference implementation.

## Engine architecture

**Engine**
Short form of Dumpsta-Engine. Used for the Python library as a whole, and most often for
the HTTP-level implementation under `_core` and `_private` that talks to Instagram
without a browser.

**Public surface**
Everything importable from `dumpstagram` that is not underscore-prefixed. Versioned and
stability-guaranteed.

**Private layer**
`dumpstagram._private`. Endpoints, signing, device construction, transport. Free to
change in any release without notice.

**Core**
`dumpstagram._core`. The async implementation of every capability. Not public, but
distinct from `_private` in that it holds logic rather than protocol details.

**Sync facade**
`dumpstagram.client.SyncClient`. Blocking wrapper over the async core. What Swift and
most Python callers use.

**Async surface**
`dumpstagram.aio.AsyncClient`. The awaitable public surface, for Python callers who
want concurrency.

**Loop thread**
The background thread hosting the engine's persistent asyncio event loop. Shared and
refcounted across client instances, never per instance. See
[ADR-0004](../decisions/ADR-0004-instance-scoped-sessions.md).

**Session**
The per-account state object. Credential material, device fingerprint where one is needed,
cookies, tokens, proxy, and
checkpoint state. Constructed by the caller and passed into a client, never created
implicitly by one.

**Device fingerprint**
The coherent pretend-device identity a session presents. Stable per account. Measured to be
unnecessary on the web surface, which is the chosen one, so a session legitimately has none and
no generator exists. It becomes relevant only if a mobile adapter is ever built. See
[prior-art-dumpsta-js.md](prior-art-dumpsta-js.md) and
[../decisions/ADR-0007-web-graphql-surface-first.md](../decisions/ADR-0007-web-graphql-surface-first.md).

**Pacer**
The per-account rate limiter and backoff controller. Owns the decision of when a
request is allowed to leave. Lives in the engine, never in the app.

**Listener**
A long-lived object produced by `events()` that delivers events until stopped.
Distinct from a fetch, which starts and ends.

**Event buffer**
The thread-safe queue a listener writes into and a consumer drains. The mechanism that
avoids callbacks across the Swift and Python boundary.

**Realtime subsystem**
`_core/realtime/`. Owns the event transport. Shares the session and client identity
with the REST client, deliberately does not share the request pipeline.

## Bridge

**Bridge**
The Swift and Python boundary. Documented in [../bridge/](../bridge/overview.md).

**Runtime**
The `Runtime/` directory, holding a relocatable CPython and the vendored
`site-packages`. A build product, never committed.

**Python queue**
The single serial dispatch queue or actor in Swift that owns all `PythonObject`
access.

**Bootstrap**
`PythonRuntime.bootstrap()`. Sets interpreter environment variables and initializes
the interpreter. Runs once per process, before any other PythonKit use.

## Process

**Phase**
One of the six ordered build stages in
[ADR-0005](../decisions/ADR-0005-engine-first-build-order.md). Each has an explicit
stop condition.

**Stop condition**
The observable result that must hold before the next phase starts.

**Locked decision**
One of the six decisions listed in [../../CLAUDE.md](../../CLAUDE.md). Not reopened
without the user asking.

## Terms from the prior art

Used in protocol discussion, and defined here so they are not confused with this project's own
concepts. Full context in [prior-art-dumpsta-js.md](prior-art-dumpsta-js.md).

**Prior art**
The JavaScript project at `/Users/mahfujm/Documents/dumpsta-js`. Conceptual reference only. No
code transfers.

**Oracle**
A recorded real capture used as ground truth for testing a reimplementation. The prior project
used an export from one implementation to verify a rewrite of another, offline and without
credentials.

**Ablation**
Sending a baseline request repeatedly with one field or header removed each time, to establish
which of them the server actually validates. How the prior project proved that only one body
field and two headers are checked.

**Positive control**
A deliberate check that a search would have found something if it were there. Required before an
empty result counts as evidence.

**Persisted query identifier**
The hash that addresses a server-side stored GraphQL query. Perishable: it changes when the
query is redeployed, with no notice.

**Alias, canonical id, and internal id**
Three different identifiers Instagram uses for one direct thread. Confusing them returns empty
results rather than errors. See
[../../engine/docs/session-and-auth.md](../../engine/docs/session-and-auth.md).

## Terms deliberately not used

**Scraper.** The engine is a client, not a scraper. Scraping implies parsing rendered
pages, which [ADR-0003](../decisions/ADR-0003-no-browser-driver.md) rules out.

**Bot.** Carries assumptions about automation volume that conflict with the project's
conservative pacing posture.

**Driver.** Reserved for browser automation, which this project does not use. Do not
call the engine a driver.

**Adopted session**
Credential material copied out of a browser where the user is already logged in, rather than
obtained by logging in from the library. The Phase 1 credential model. See
[../decisions/ADR-0008-adopt-existing-browser-session.md](../decisions/ADR-0008-adopt-existing-browser-session.md).

**uv**
The only Python toolchain used in this repository. Manages interpreters, the project
environment, dependency resolution, and `engine/uv.lock`. See
[../decisions/ADR-0009-uv-toolchain-python-floor.md](../decisions/ADR-0009-uv-toolchain-python-floor.md).
