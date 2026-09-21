# Live reproduction: replay of bootstrap plus one page, 2026-09-21

Second live run from this repository, and the first replay of one against another. Run with
`uv run --with httpx --no-project python probes/live_repro_bootstrap_page.py` from `engine/`,
on CPython 3.12.13. Exactly two requests, spaced 2850 ms, read only. Nothing was written, sent,
marked read, or reacted to.

Its purpose was not discovery. Everything it observed was already recorded in
[live-reproduction-2026-09-20.md](live-reproduction-2026-09-20.md). It ran because
`engine/dumpstagram/_private/web/` needed to name a URL and a `doc_id` in code, and the
provenance gate refuses a literal that no `verified` finding in the reverse-engineer knowledge
base backs. The run is what produced those findings. See
[engine/docs/web-request-contract.md](../../engine/docs/web-request-contract.md) for what was
built on top of it.

Log: `engine/logs/live-repro-2026-09-21-013113.json`.
Run record: `skills/reverse-engineer/var/runs/run-2026-09-21-013053/notes.md`.

## What was run

| Step | Request | Purpose |
|---|---|---|
| 1 | `GET https://www.instagram.com/direct/inbox/` | Bootstrap. Harvest `fb_dtsg`, `lsd`, the `__spin_*` family, `__hsi`, the haste session, and the app id out of the HTML. |
| 2 | `POST https://www.instagram.com/api/graphql` | One page of `useIGDMessageListPaginationQuery`, `doc_id` `27502152406082940`, `first: 20`, `after: null`. |

Credentials from `.env` at the repository root, the same five keys as the first run. No login
was attempted. Same reference thread fbid `17945046917948992`.

## Results, against the first run

FACT for both columns. Read only, one account, one thread, one residential IP, two days.

| Measure | 2026-09-20 | 2026-09-21 | Reading |
|---|---|---|---|
| Bootstrap status | 200 | 200 | Unchanged |
| Bootstrap HTML size | 809815 bytes | 810080 bytes | Bundle drifts slightly day to day |
| Bootstrap elapsed | 449 ms | 724 ms | Network variance, no signal |
| `fb_dtsg` length | 84 | 84 | Stable, and the extraction pattern still matches |
| `lsd` length | 22 | 22 | Stable |
| `x-ig-app-id` | 936619743392459 | 936619743392459 | Not per session and not per day |
| `__spin_r` and `__rev` | 1047994416 | 1047996704 | Rotates. Never hard code it |
| `__spin_b` | trunk | trunk | Stable |
| `__hsi`, `haste_session` | present | present | Both scraped successfully |
| `"USER_ID"` matches | all `"0"` | `["0", "0"]` | The bundle still never carries the real viewer id |
| Page status | 200 | 200 | Unchanged |
| Page body size | 37807 bytes | 39500 bytes | Thread grew between runs |
| Page elapsed | 151 ms | 225 ms | Network variance |
| Top-level keys | `data`, `extensions` | `data`, `extensions` | Unchanged |
| `errors` array | absent | absent | No failure was triggered on either day |
| Canonical path | present | present | `data.fetch__SlideThread.as_ig_direct_thread.slide_messages` |
| Edges | 20 | 20 | The server-side cap holds |
| `has_next_page` | true | true | Unchanged |
| `end_cursor` length | 132 | 132 | Unchanged |
| Newest message id | `mid.$cAAANx1A4CESm8y_m2mgweqeUAaea` | `mid.$cAAANx1A4CESm87IV-mgwmzNQgle_` | The thread received messages between runs, which is the expected difference |

## What this run added that the first did not

**The `doc_id` survived a day.** FACT. `27502152406082940` was still served on 2026-09-21. One
day is weak evidence about a rotation interval and strong evidence that the id was not a
one-session artifact.

**The message node shape.** FACT, from this run's log. The first 20 keys of the newest node,
sorted, which is the first local evidence about what a Phase 2 message model has to cover:

```
__typename, bot_response_id, content, content_type, expiration_timestamp_ms, id,
igd_is_forwarded, igd_wearables_attribution_text, igd_wearables_attribution_type,
is_ai_generated, is_pinned, is_reported, is_tombstone_revealable, mentions, message_id,
msg_reactions, offline_threading_id, reactions, replied_to_message, replied_to_message_id
```

Note the pair `id` and `message_id`, and the pair `reactions` and `msg_reactions`. Two names
for what look like one thing each is exactly the hazard
[session-and-auth.md](../../engine/docs/session-and-auth.md) records under plausible field
names holding different numbers. Which of each pair a model should use is UNRESOLVED and needs
a run of its own.

**`__spin_r` rotates.** FACT. It changed between two runs a day apart. A cached session file
therefore carries a stale spin revision, which the upstream was measured to ignore, but which
is a difference from what a browser would send at that moment.

## The probe was broken and nobody knew

BUG, found by running it.

`engine/probes/live_repro_bootstrap_page.py` resolved `.env` with
`Path(__file__).resolve().parents[3]`, which pointed at `/Users/mahfujm/Documents` rather than
at the repository root. It failed immediately with:

```
FileNotFoundError: [Errno 2] No such file or directory: '/Users/mahfujm/Documents/.env'
```

**Root cause.** The path was correct when the probe lived under `module/`. Commit `99a4652`
renamed `module/` to `engine/` and `app/` to `client-app/`, which changed the depth by one. The
probe was not rerun after the rename, so the break sat there for a day.

**Fix.** `parents[2]`.

**Lesson.** A probe that is never rerun is a probe whose claims quietly expire. The
project-profile command table now records the working invocation, including `--no-project`,
which is needed because the probe runs outside the engine's own environment.

## What this run still did not establish

Unchanged from the first run, and worth restating rather than linking, because the temptation
to assume otherwise grows with every green run:

- **No error envelope was observed.** Both runs succeeded, so the classifier's envelope
  branches remain gated against fixtures rather than against captured failures.
- **No throttling was observed**, and two requests say nothing about pacing.
- **No write was attempted.** Every number here is read traffic.
- **One account, one thread, one residential IP.**
- **The page size cap was not re-probed.** Only `first: 20` was sent on both days.

## Safety note carried forward

Same posture as the first run. The `.env` at the repository root holds a live `sessionid`,
which is a full account takeover token with no second factor. It is gitignored. No credential,
message body, or third-party name appears in the log this run wrote, per
[engine/logs/README.md](../../engine/logs/README.md). The log records lengths, counts, sizes,
ids, and timings, and the one id it does record is a message id from the user's own thread.
