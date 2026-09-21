# Overview

## Purpose

Dumpsta-Module is a Python library that provides high-level access to Instagram. Two
goals drive it, and they are in tension, which is why the architecture looks the way
it does.

**Goal one, capability.** Reach everything the Instagram website and the Instagram
mobile app can do, and more where more is possible. Breadth is the point. A library
that covers eighty percent of the official clients is not what this is.

**Goal two, stability.** Offer a maintainable, well-architected public API that a
developer can build on. The API should be pleasant and it should not break under
them.

The tension: goal one requires depending on an undocumented API that changes without
notice, and goal two requires not exposing that churn. The resolution is the hard
layering in [architecture.md](architecture.md), a public surface with a promise and a
private layer with none.

**Goal three, engine design.** The engine reaches Instagram without browser drivers.
Direct HTTP. See
[../../docs/decisions/ADR-0003-no-browser-driver.md](../../docs/decisions/ADR-0003-no-browser-driver.md).

## Who consumes it

| Consumer | Surface used | Notes |
|---|---|---|
| Dumpsta-App, Swift | `SyncClient` | Cannot await Python coroutines. Drives the library through PythonKit. |
| The project's own CLI | `SyncClient` | First consumer, built in Phase 2. Doubles as smoke test and documentation by example. |
| Third-party Python scripts | `SyncClient` | The common case. Blocking is what a script wants. |
| Third-party async applications | `aio.AsyncClient` | Bypasses the facade entirely. |

The CLI is not throwaway. It is how the public API gets validated before the expensive
Swift work starts. See
[../../docs/decisions/ADR-0005-module-first-build-order.md](../../docs/decisions/ADR-0005-module-first-build-order.md).

## Capability scope

Intended to be exhaustive over time. The categories below set expectations, not a fixed list.

- Authentication or session adoption, including two-factor and challenge flows.
- Profiles and user graphs, followers, following, blocks, restrictions.
- Feeds, timeline, explore, hashtag, location, and user feeds.
- Media, photos, video, carousels, stories, reels, highlights.
- Publishing, uploads, edits, deletions.
- Engagement, likes, comments, saves, shares.
- Direct messaging, threads, sending, media in messages.
- Realtime events, new messages first.
- Notifications and activity.
- Insights and analytics where the private API exposes them.
- Account settings and privacy controls.

Ordering across these is set by [roadmap.md](roadmap.md), not by this list. Read capabilities
come before write capabilities in every category.

### What has actually been reached

Worth stating plainly so the gap between goal and evidence stays visible. A prior JavaScript
project reached exactly one item on that list: reading direct-message threads, including media
references, participants, and reactions. Read-only, on the web surface. FACT. See
[../../docs/knowledge/prior-art-dumpsta-js.md](../../docs/knowledge/prior-art-dumpsta-js.md).

Everything else on the list is unattempted by anyone associated with this project. In
particular, no write operation has ever been performed, and the surface that would support the
full list is still an open question.

## Out of scope

- Browser automation of any kind.
- Anything requiring a rendered page to be parsed.
- Swift-specific integration code. The bridge is the app's concern, documented at
  [../../docs/bridge/overview.md](../../docs/bridge/overview.md).
- Application-level concerns such as caching for a UI, offline storage, or account
  switching UX. Those belong to consumers.

The one deliberate exception to "application concerns belong to consumers" is rate
limiting, which lives here on purpose. See
[rate-limiting-and-safety.md](rate-limiting-and-safety.md).

## Naming

Package `dumpstagram`. Terminology is fixed in
[../../docs/knowledge/glossary.md](../../docs/knowledge/glossary.md). Note in
particular that this library is a client, not a scraper, not a bot, and not a driver.
