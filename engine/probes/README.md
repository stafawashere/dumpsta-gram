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
| `feed_node_shape.py` | 1, or 2 if the stored tokens are stale | What a timeline feed node actually carries. Loads the saved session, reads one page through the library and records the key union of the connection, the edge and every `media` node, plus a census of which union slot each item filled, with types, counts and lengths but no values except `__typename`, `media_type`, `product_type` and the like. Ran 2026-09-21, one request, 15 edges of which 6 were media, every edge cursor null, exactly one union slot filled per item, and it is the evidence `models/feed.py` was written from. Run it with `uv run python probes/feed_node_shape.py`, no `--no-project`. |
| `home_document_preloader.py` | 1, or 2 with `--follow` | Does the first feed page arrive inside the home document when the library loads it, rather than a browser. Drives `_core.feed.read_first_feed_page_from_document` and records item count and kinds, `has_next_page`, the `end_cursor` length and whether the page tokens changed. `--follow` then reads page two through the pagination query with the document's cursor. Ran 2026-09-23 twice: 4 items each time, and with `--follow` page two carried 6 items with `has_next_page` true. It is the replay evidence for finding `home-timeline-first-page-preloader`. Run it with `uv run python probes/home_document_preloader.py`, no `--no-project`. |
| `home_load_cookie_sync.py` | 10 at most, 2 of them to facebook.com, writes once | Does the engine's own home load send its companions and then the four-request cookie sync tail as designed in 17.2.3 of the build plan. Drives `AsyncClient.feed()` under the default parity behavior, records every request at the transport with its host, name, status, length, classification and offsets from the document, and the names of cookies each response set, and refuses an eleventh request. `fr` is recorded as presence and length only. Posts to `/sync/instagram/` and may change the saved `fr`, so it sends nothing without `--approved`. Ran 2026-09-23 with the owner's approval: ten requests, all 200, the tail departing at 4967 to 6252 ms after the document, `fr` absent before and 126 characters after, log `home-load-cookie-sync-2026-09-23-041954.json`. It is the first engine replay of the four cookie sync findings. Run it with `uv run python probes/home_load_cookie_sync.py --approved`, no `--no-project`. |
| `capture_thread_oracle.py` | one per page, 399 on 2026-09-22 | The raw material for the recorded oracle. Reads the whole thread through the library's own request builder and classifier, writes every body verbatim to gitignored `../exports/thread-oracle-<stamp>/`, stops on `has_next_page` false or at 400 pages, and resumes from its manifest with `--resume`. Each page is also offered to the mapper and the outcome logged. Ran 2026-09-22, 1177 s, 7967 messages in 19 content types, zero duplicates, zero mapper refusals. The raw pages carry message text and the echoed `dtsg_token`, which is why they never leave `exports/`. Run it with `uv run python probes/capture_thread_oracle.py`, no `--no-project`. |
| `thread_route_live.py` | 2, or 3 if the stored tokens are stale | Does the default thread route work live. Opens the thread through `IGDThreadDetailQuery` via `_core.direct.read_thread_messages`, then reads the next older page through `IGDMessageListOffMsysQuery` with the detail answer's cursor. Ran 2026-09-23, 3043 ms, both friendly names sent, 20 and 20 messages, both `has_next_page` true, no message on both pages, the older page entirely older. Run it with `uv run python probes/thread_route_live.py`, no `--no-project`. |
| `like_discovery.py` | 8, 9 with a bootstrap, 4 of them writes | Step 15's discovery, done from the engine side because ruling 23 allowed no browser load. Reads one own post off the timeline, reads it by shortcode, sends the write that moves it away from its starting like state twice, reads, sends the reversing write twice, reads, all built by `build_graphql_request` and written through `send_write`. It carries the three `doc_id` values itself, since none was verified when it ran. It answered which identifier the mutations take (the `pk`), what they echo (the `<pk>_<owner id>` form and `has_liked`), and that a repeat of either converges. Ran 2026-09-23 with the owner's advance approval: eight requests, the post read true 6, false 5, true 6, and ended liked as it started. Log `like-discovery-2026-09-23-051806.json`. Refuses to run without `--approve like-cycle`. Run it with `uv run python probes/like_discovery.py --approve like-cycle`, no `--no-project`. |
| `like_cycle.py` | 5, 6 with a bootstrap, 2 of them writes | Step 15's live acceptance through the public `AsyncClient`: `post`, the write away from the starting state, `post`, the reversing write, `post`. Refuses to write unless the post is the viewer's own, and caps itself at six requests. Ran 2026-09-23: five requests, `unlike` then `like` because the owner's post was already liked, reads true 6, false 5, true 6, ended in its starting state. Log `like-cycle-2026-09-23-052731.json`. Refuses to run without `--approve like`. Run it with `uv run python probes/like_cycle.py --approve like --code CODE`, no `--no-project`. |
| `comment_discovery.py` | 2, 1 and 7 over three stages, one more each with a bootstrap, writes in two | Step 16's discovery, done from the engine side because ruling 23 allowed no browser load. `--stage scout` reads the comment page and sends the delete mutation with an input naming no comment, `--stage coerce` sends it with `comment_id` "0" and `media_id`, and `--stage cycle` creates, reads, deletes, reads, creates, deletes and reads, falling back once to the REST delete for a comment a delete did not remove. It carries the three `doc_id` values itself, since none was verified when it ran. It answered which identifier every call takes (the media `pk`), the create's `data` shape and answer, and the delete's input field names, which the compiled artifact does not carry: the empty input was refused as `noncoercible_variable_value`, the two names coerced, and a delete naming no comment answered a null root. Ran 2026-09-23 with the owner's advance approval: 2, 1 and 7 requests, both comments listed after their create and gone after their delete, none left up. Logs `comment-discovery-scout-2026-09-23-053720.json`, `comment-discovery-coerce-2026-09-23-053739.json`, `comment-discovery-cycle-2026-09-23-054051.json`. Reads `IG_COMMENT_TEXT` from the root `.env`. Refuses to run without `--approve comment-cycle`. Run it with `uv run python probes/comment_discovery.py --approve comment-cycle --stage STAGE --pk PK`, no `--no-project`. |
| `comment_cycle.py` | 5, 6 at most, 2 of them writes | Step 16's live acceptance through the public `AsyncClient`: `comments`, `comment`, `comments`, `delete_comment`, `comments`. Deletes a stray viewer comment if `comment` raises, tries the REST delete once if `delete_comment` raises, and caps itself at six requests. Ran 2026-09-23: five requests, the created id listed with the same text and the viewer as author, `created_at` 1 s from the clock, the page back to no comment. Log `comment-cycle-2026-09-23-054958.json`. Reads `IG_COMMENT_TEXT` from the root `.env`. Refuses to run without `--approve comment`. Run it with `uv run python probes/comment_cycle.py --approve comment --pk PK`, no `--no-project`. |
| `note_write_cycle.py` | 5 planned, 2 of them writes | Not written. Step 14's acceptance run: tray read, set a close friends note, tray read, delete it, tray read. On 2026-09-23 the discovery run found the owner already had a hand-made song note up, which a set would replace and the delete would then remove, so no note write was sent and this probe waits for `set_note` and `delete_note` and for the owner's word on the existing note. When written it refuses to run without `--approve set-note`, reads the text from `IG_NOTE_TEXT` in the root `.env`, and logs lengths, counts, ids and timings only. |
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
