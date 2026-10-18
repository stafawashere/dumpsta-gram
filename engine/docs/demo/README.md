# Demo scripts

One script per task, each using only the public `dumpstagram` names. Run them from `engine/`
with `uv run python docs/demo/<script>.py`. Every script takes `--quick`, which skips the page
loads a browser would make, and `--help`.

The session comes from `engine/state/session.json`, or from the cookie keys in the root `.env`
when that file does not exist, and harvested tokens are saved back to it. Each run writes
`engine/logs/demo-<name>-<stamp>.json` with counts and timings only. The terminal shows what
came back, which includes other people's names and text.

| Script | What it shows | Live requests under parity |
|---|---|---|
| `offline.py` | Session round trip, proxy, presets, custom `Behavior`, errors and `RETRYABLE`, `with_behavior`, the namespace aliases | 0 |
| `profiles.py` | `profiles.by_id`, and `profiles.by_username` with `friendship_status` via `--username` | 1, plus 7 with `--username` |
| `feed.py` | `feeds.home`, the next page by cursor, `feeds.iter_home` | about 8 |
| `post.py` | `media.by_code` with video, audio and carousel slides, `media.comments`, `media.iter_comments`, `media.download` via `--download` | 2 to 3, plus the feed without `--code` |
| `direct.py` | `direct.notes`, and with `--thread` `direct.messages`, the next page, `direct.iter_messages` | 1, plus 3 with `--thread` |
| `events.py` | `client.events()` as a blocking listener, or the async iterator with `--async` | 1 per poll, plus changed threads |
| `async_surface.py` | `AsyncClient`, an awaited read and `async for` over `feeds.iter_home` | about 7 |

The write scripts each undo what they did, and each checks the current state first so it never
undoes something the account already had. Writes wait out the write spacing, about 35 s each
under parity.

| Script | Cycle | Live requests |
|---|---|---|
| `like_cycle.py CODE` | `media.like`, read back, `media.unlike`. Skipped when already liked | 4 |
| `comment_cycle.py CODE` | `media.comment`, `media.delete_comment`, text from `IG_COMMENT_TEXT` | 3 |
| `note_cycle.py` | `direct.set_note`, `direct.delete_note`. Skipped when a note of the account's own is up | 3 |
| `follow_cycle.py USERNAME` | `social.follow`, relationship read, `social.unfollow`. Skipped when already followed | 7 plus 3 |
| `message_cycle.py FBID` | `direct.send`, found by `offline_threading_id`, `direct.unsend`, text from `IG_DM_TEXT` | 4 |
| `publish_cycle.py JPEG...` | `media.publish_photo` or `media.publish_carousel`, read back, `media.delete_post`. Public while up | one per image plus 3 |

`_common.py` holds what the scripts share: session loading, output helpers, the log and the
exit codes, which are the ones the `dumpsta` command uses.
