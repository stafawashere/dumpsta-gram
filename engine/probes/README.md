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
