# Overview

Dumpsta-Engine, the `dumpstagram` package, reads and writes Instagram from Python over the same
web API instagram.com calls, with a blocking client, an awaitable client and a `dumpsta` command.

## Legal and safety notice

Read this before installing. This library talks to an unofficial, undocumented Instagram API.
Using it is against Instagram's terms of use, and it can get the account you use restricted,
checkpointed or banned. The API changes without notice, so any method can stop working on any
day. Use it only with an account you own and can afford to lose.

The engine ships with conservative pacing and you should keep it. By default each request waits
1.3 s to 5.3 s after the previous one, fitted to a person browsing, every write waits at least
30 s after the previous write, and no more than 30 writes leave in any rolling hour. A write is
sent once and never retried by the engine, a checkpoint is never retried under any setting, and
an unrecognised rejection of a write stops further writes for the life of the client. Faster
presets exist and nothing has measured how Instagram treats them.

## Install

Python 3.12 or newer. The package is not on a package index. Install it from a release tag of the
repository with uv:

```bash
uv add "dumpstagram @ git+https://github.com/stafawashere/dumpsta-gram.git@v1.0.0#subdirectory=engine"
```

or from a built wheel:

```bash
uv add ./dumpstagram-1.0.0-py3-none-any.whl
```

## Quickstart

The engine does not log in. It adopts a session you are already signed into in a browser. Copy
the `sessionid`, `ds_user_id` and `csrftoken` cookies for `https://www.instagram.com` out of the
browser's developer tools into a file that only you can read, one `KEY=value` line each:

```
IG_SESSIONID=...
IG_DS_USER_ID=...
IG_CSRFTOKEN=...
```

Adopt it into a session file. This sends no request. Cookies are read from the file or the
environment and never from the command line, because a `sessionid` is a full account takeover
token:

```bash
uv run dumpsta --session session.json adopt --cookies-file cookies.env
```

Then read a profile through `SyncClient`:

```python
from dumpstagram import SyncClient

with SyncClient.from_session_file("session.json") as client:
   profile = client.profile("instagram")
   print(profile.username, profile.follower_count)
```

`uv run dumpsta --help` lists every command. [cli.md](cli.md) documents them, and
[public-api.md](public-api.md) documents the library.

## Purpose

Dumpsta-Engine is a Python library that provides high-level access to Instagram. Two
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
[../../docs/decisions/ADR-0005-engine-first-build-order.md](../../docs/decisions/ADR-0005-engine-first-build-order.md).

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

As of `1.0.0`, on the web surface: session adoption, profiles, the home feed, one post and its
comment pages, the notes tray, direct thread pages, and new direct messages through `events()`.
Writes: like and unlike, comment and delete a comment, set and delete a note, follow and
unfollow, and send and unsend a direct message. Each was verified live on one account from one
residential network. Posting is planned for `1.1.0`. Everything else on the list is
unattempted, and group threads, the mobile API and login are unmeasured.

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
