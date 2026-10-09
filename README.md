# Dumpstagram

Two projects in one repo. `engine/` is Dumpsta-Engine, a Python library and a `dumpsta` command that read and write Instagram through the same web API instagram.com uses. `client-app/` is Dumpsta-App, a native macOS client in SwiftUI that's meant to run on top of the engine.

I wanted to replace Instagram's website with a real Mac app. To do that properly, the app shouldn't know anything about Instagram's endpoints, so all of that lives in the engine and the app only talks to its public API. The app is also supposed to be the example of how to use the engine.

## Status

The engine works and is tagged `v1.1.0`. It reads the home feed, profiles and their tabs, posts and comments, stories and highlights, the DM inbox and threads, search, explore, reels and notes, and it can like, follow, comment, send DMs and publish photos. There's no login step. The engine adopts a session you're already signed into in your browser. The pacing is slow on purpose. Every write waits at least 30 seconds after the last one, there's a cap of 30 writes an hour, and if Instagram rejects a write in a way the engine doesn't recognize, it stops sending writes until you clear it by hand.

The app isn't connected to the engine yet. On `main` it runs on a stand-in engine with made-up accounts and posts, so the feed, stories, reels, profiles, messages, search and notifications screens can be built without touching a real account. Hooking it up to the real engine through an embedded Python runtime is the next step.

Using this breaks Instagram's terms of use and can get an account restricted or banned, so only use it on an account you own and can afford to lose.

## Engine setup

You need [uv](https://docs.astral.sh/uv/). It installs and pins Python 3.12 for you.

```bash
cd engine
uv sync
uv run dumpsta --help
```

Copy the `sessionid`, `ds_user_id` and `csrftoken` cookies for instagram.com from your browser into a file of `KEY=value` lines (`.env.example` shows the format), then adopt them into a session file. Adopting sends no request to Instagram.

```bash
uv run dumpsta --session ~/dumpsta/session.json adopt --cookies-file ~/dumpsta/cookies.env
uv run dumpsta --session ~/dumpsta/session.json profile instagram
```

Keep both files outside the repo and never commit them. The `sessionid` cookie is as good as your password and skips two-factor.

The full command list is in `engine/docs/cli.md`, and the Python API is in `engine/docs/overview.md` and `engine/docs/public-api.md`.

## App setup

You need macOS 14 or newer on Apple Silicon, Xcode, and [XcodeGen](https://github.com/yonaskolb/XcodeGen).

```bash
client-app/scripts/build-run.command
```

That generates the Xcode project, builds it and opens the app. `build-app.command` and `run-app.command` do the two halves on their own.

## License

MIT. See [LICENSE](LICENSE).
