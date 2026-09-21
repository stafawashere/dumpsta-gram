# Probes

Scripts that touch the live API, or that exist to answer one question about it. Anything a
session writes and runs which would be useful to a later session lives here rather than in a
scratch directory. A probe that only exists in a session transcript is a probe that gets
rewritten from scratch next month.

This is not the test suite, and since 2026-09-20 it does not live inside it either. Probes sit at
`engine/probes/` rather than under `engine/tests/`, so `testpaths = ["tests"]` cannot reach them and
`tests/` means gates and nothing else. Probes are not run by `uv run pytest`, they are not
assertions, and they are not a gate. They are reproducible evidence-gathering tools.

## Rules

- **Read only unless the user asks otherwise.** A probe that writes to an account must say so in
  its first docstring line and must not run by default.
- **Credentials come from `.env` at the repository root**, never from arguments, never inline.
- **Every probe writes a log to `../logs/`** on success and on failure, with the naming and
  sanitising rules in [../logs/README.md](../logs/README.md).
- **Pace at 2850 ms between live requests**, the measured 0.351 req/s anchor, unless the probe
  exists specifically to test pacing.
- **State the request count** in the probe's header, so the cost of running it is visible before
  it runs.

## Index

| Script | Requests | What it answers |
|---|---|---|
| `end_to_end_read.py` | 2 | Are the library's own layers wired to each other. Drives `Session`, `HttpxTransport`, `PacedSender`, `bootstrap`, the request builder and the classifier through `_core.smoke.read_one_thread_page`, rather than reimplementing the request shape. Ran 2026-09-21, 20 edges, 2956 ms for both requests. Run it with `uv run python probes/end_to_end_read.py`, no `--no-project`, because it imports the library. |
| `adopt_and_save.py` | 2 | Does an adopted session survive a process boundary, first half. Adopts from `.env`, bootstraps, reads one page to prove the credentials are alive, saves to `engine/state/session.json` and exits. Ran 2026-09-21, 2997 ms, 734-byte session file at `-rw-------`, reloaded equal in memory. Run it with `uv run python probes/adopt_and_save.py`, no `--no-project`. |
| `reload_and_call.py` | 1, or 2 if the stored tokens are stale | The Phase 1 stop condition, second half. Loads the session file in a process that never saw the first probe, and reads one page with no credential from `.env` at all. Ran 2026-09-21, 432 ms, one request, no re-bootstrap, 20 edges. Rerunning it against an old session file is the cheapest measurement available of the open token-lifetime question. Run it with `uv run python probes/reload_and_call.py`, no `--no-project`. |
| `message_node_shape.py` | 1, or 2 if the stored tokens are stale | What the message node actually carries. Loads the saved session, reads one page through the library and records the key union of all twenty nodes plus the edge, the connection and the thread, with types, counts and lengths but no values except `__typename`, `content_type` and the first four characters of an id. Ran 2026-09-21, 308 ms, one request, 28 node keys, and it closed both open field-pair questions: `id` equals `message_id` on 20 of 20, and only `reactions` carries the emoji. Run it with `uv run python probes/message_node_shape.py`, no `--no-project`. |
| `_probe_support.py` | 0 | Not a probe. The `.env` loader, the log writer and the page counter the Step 9 probes share. `end_to_end_read.py` keeps its own copies, because rewriting verified evidence costs two live requests to re-establish. |
| `live_repro_bootstrap_page.py` | 2 | Does bootstrap token extraction plus one `useIGDMessageListPaginationQuery` page still work from Python. Written up in [live-reproduction-2026-09-20.md](../../docs/knowledge/live-reproduction-2026-09-20.md) and replayed in [live-reproduction-2026-09-21.md](../../docs/knowledge/live-reproduction-2026-09-21.md). |

Run it with:

```
uv run --with httpx --no-project python probes/live_repro_bootstrap_page.py
```

`--no-project` matters. A probe is not part of the package and does not use its environment, so
without it uv tries to resolve the engine's own project first.

## A probe nothing reruns is a probe whose claims expire

Learned the hard way on 2026-09-21. `live_repro_bootstrap_page.py` resolved `.env` with
`parents[3]`, which was correct under the old `module/` directory name and pointed at
`~/Documents` after the rename to `engine/`. It failed on the first line that touched the file
system, and the break had sat there for a day because nothing had rerun it.

Two consequences worth carrying. The command that runs a probe belongs in
[../docs/engineering/project-profile.md](../docs/engineering/project-profile.md) with its last
verified result, like every other command. And a probe's evidence is only as current as its last
run, so a document citing one should say when it last ran rather than that it exists.
