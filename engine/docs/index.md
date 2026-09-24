# Dumpsta-Engine

!!! danger "Legal and safety notice"

    Dumpsta-Engine talks to an unofficial, undocumented Instagram API. Using it is against
    Instagram's terms of use, and the account you use with it can be restricted, checkpointed or
    banned. The API changes without notice, so any method can stop working on any day. Use it
    only with an account you own and can afford to lose.

    The default pacing exists to protect that account, and you should keep it. Requests are
    spaced like a person browsing, writes are spaced further apart and capped per hour, a write
    is never retried, and a checkpoint is never retried under any setting. Read
    [Legal and safety](legal-and-safety.md) before you install.

Dumpsta-Engine, the `dumpstagram` package, reads and writes Instagram from Python over the same
web API instagram.com calls. It has a blocking client, an awaitable client and a `dumpsta`
command, all over one implementation. It speaks HTTP directly and drives no browser.

## Install

Python 3.12 or newer. The package is not on a package index, so install it from a release tag of
the repository with uv:

```bash
uv add "dumpstagram @ git+https://github.com/stafawashere/dumpsta-gram.git@v1.1.0#subdirectory=engine"
```

## Quickstart

The engine does not log in. It adopts a session you are already signed into in a browser. Copy
the `sessionid`, `ds_user_id` and `csrftoken` cookies for `https://www.instagram.com` from the
browser's developer tools into a file only you can read, one `KEY=value` line each:

```
IG_SESSIONID=...
IG_DS_USER_ID=...
IG_CSRFTOKEN=...
```

Adopt it into a session file. This sends no request. Cookies are read from a file or the
environment and never from the command line, because a `sessionid` is enough to take over the
account:

```bash
uv run dumpsta --session session.json adopt --cookies-file cookies.env
```

Then read through `SyncClient`:

```python
from dumpstagram import SyncClient

with SyncClient.from_session_file("session.json") as client:
   profile = client.profiles.by_username("instagram")
   print(profile.username, profile.follower_count)

   page = client.feeds.home()
   print(len(page.items), page.has_next_page)
```

An async application uses `AsyncClient` the same way, with `async with` and `await`.

## Where to go next

- [Overview](overview.md) covers what the engine reaches today and what it does not.
- [Public API](public-api.md) is the stability contract, and the
  [API reference](reference/clients.md) is generated from the code.
- [Command line](cli.md) documents every `dumpsta` command.
- [Rate limiting and safety](rate-limiting-and-safety.md) explains the pacer and the write budget.
- [Session and authentication](session-and-auth.md) covers the session file and what to protect.
