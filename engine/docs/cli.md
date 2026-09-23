# The `dumpsta` command

The engine's first consumer, and the acceptance harness for the Phase 2 stop condition.
[ADR-0005](../../docs/decisions/ADR-0005-engine-first-build-order.md) makes it a real
consumer rather than a demo: every capability it reaches, it reaches through `SyncClient`, so
anything awkward to do from the command line is a gap in the public API rather than something
the command works around. `events --surface async` is the one exception, and it goes through
the other public surface, `AsyncClient`, never past it.

It lives at `dumpstagram/_cli/`. The installed console script is the contract and the module
layout behind it is not, which is why `_cli` is private and why nothing about the command
appears in `tests/public_surface.txt`.

The command is stdlib only. The `cli` extra in `pyproject.toml` stays empty and reserves the
name for a dependency that earns its place later.

## Invoking it

From the checkout:

```bash
uv run dumpsta --help
```

From an installed wheel, which is how a consumer gets it:

```bash
uv run --no-project --with dist/dumpstagram-0.0.0-py3-none-any.whl -- dumpsta --help
```

Every command needs a session file. There is no default path, because a session file holds a
`sessionid`, and guessing a location for one is how a tool writes an account token somewhere
its owner did not choose. Pass `--session PATH`, or set `DUMPSTAGRAM_SESSION`.

## Commands

| Command | Live requests | What it does |
|---|---|---|
| `adopt` | 0 | Builds a session from cookie material and saves it |
| `session` | 0 | Prints what the saved session holds, redacted |
| `thread FBID` | 1 per page, plus 1 if the session has no token yet | Reads pages of one direct thread |
| `profile USERNAME` | 2, or 1 with `--by-id`, plus 1 if the session has no token yet | Reads one account's profile |
| `feed` | 1 per page, plus 1 if the session has no token yet | Reads pages of the home timeline |
| `note list` | 1, plus 1 if the session has no token yet | Reads the notes tray and marks the viewer's own note |
| `note set TEXT --audience AUDIENCE`, `note delete NOTE_ID` | 1 write, plus 1 read if the session has no token yet, or for `set` no Facebook-side id | Sets the viewer's note, replacing any note up, or deletes it. Writes to the account |
| `post CODE` | 1, plus 1 if the session has no token yet | Reads one post by its shortcode, with its `pk` and the viewer's like state |
| `like PK`, `unlike PK` | 1 write, plus 1 read if the session has no token yet | Likes or unlikes one post. Writes to the account |
| `comments PK` | 1, plus 1 if the session has no token yet | Reads one page of a post's comments, with each comment's id |
| `comment PK TEXT`, `delete-comment PK COMMENT_ID` | 1 write, plus 1 read if the session has no token yet | Comments on one post, or deletes one comment. Writes to the account |
| `events --duration SECONDS` | 1 per poll, plus 1 per page of a thread that gained messages, plus 1 if the session has no token yet | Prints new direct messages as they arrive, for a fixed time. Marks nothing seen |

`--json` on any command emits the machine-readable form instead of text. That form is a
contract: a key that moves breaks whatever scripts the command.

### `adopt`

Cookie material is read from the process environment, or from `--cookies-file PATH`, which is
a file of `KEY=value` lines. It is never read from the command line. `argv` is readable by
every process on the machine through `ps` and it lands in shell history, and a `sessionid` is
a full account takeover token with no second factor. A gate asserts the parser defines no
option that takes one.

Required keys are `IG_SESSIONID`, `IG_DS_USER_ID` and `IG_CSRFTOKEN`. `IG_MID` is sent as a
cookie when it is present, because the request builders reproduce a full browser request and a
minimal request is a fingerprint. All missing keys are named at once, so pasting three cookies
is one run rather than three.

`IG_FR` is optional and is not a cookie. It is the `fr` value the browser keeps in
`localStorage` for `https://www.instagram.com`, read from the developer tools storage panel.
It becomes `Session.fr`, which the page-load cookie sync sends, and it is treated as a
credential: never in `argv`, never in a log. Without it the session starts with none.

Adoption spends no live request. That is deliberate: a check that costs a request cannot be
used to check credentials.

```bash
IG_SESSIONID=... IG_DS_USER_ID=... IG_CSRFTOKEN=... \
  uv run dumpsta --session state/session.json adopt
```

### `session`

Prints the account id, whether the session carries tokens, the checkpoint flag and whether a
proxy is configured. It prints no credential, and a gate holds that with the file itself as
the positive control.

### `thread`

```bash
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta --json thread 17945046917948992 --pages 2
```

`FBID` is the thread's `fbid`, which is one of the three identifiers the same thread has. The
other two answer with nothing rather than with an error.

- `--pages N` reads at most `N` pages, default 1. There is no `--all`: an unbounded read is an
  unbounded number of live requests, and the pacer spaces them 2.5 s apart.
- `--after CURSOR` continues from an `end_cursor` an earlier run printed.
- `--since MESSAGE_ID` reads only what arrived after a message already seen, and it is applied
  to the first page only. Sending a cursor and a marker together is a combination nobody has
  measured.
- `--user-agent STRING` changes what every request claims to be, which is a fingerprint
  decision rather than a cosmetic one.
- `--no-session-writeback` keeps tokens harvested during the run out of the session file.

Pagination stops on the page's own `has_next_page` and never on how many messages arrived.
`more_available` in the JSON form is that boolean, so a caller can continue without guessing.

Tokens harvested during a read are written back to the session file by default. Without it
every invocation pays a bootstrap request the previous one already paid for.

### `profile`

```bash
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta --json profile some-account
```

Reads one account's profile. By default the argument is a username and the command loads the
profile page and sends its six queries together, seven live requests in one paced action, as a
browser does. The upstream's profile query takes a numeric account id and no username, and the
page is where the id comes from.

- `--by-id` treats the argument as the numeric account id and spends one request. That id is what the `id` key of the output carries, and it is not the `fbid` the same
  account carries as a message sender.
- `--user-agent STRING` and `--no-session-writeback` behave as they do on `thread`.

`requests_spent` in the JSON form says which of the two routes ran, so a harness does not have
to infer the cost from the flags it passed.

The resolution route reads the id off the first post of the account's timeline, which is the
only call on this surface observed to accept a username. An account with nothing visible to
the session therefore resolves to nothing and the command exits 7, `NotFound`, whether the
account does not exist, is private to this viewer, or genuinely has no posts. The upstream
does not distinguish the three on this route. Such an account is still readable with
`--by-id`.

### `feed`

```bash
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta --json feed --pages 2
```

Reads pages of the signed-in account's home timeline, one live request per page. The first
page and every later one are the same upstream query with one variable changed, so there is
no separate first-page call and `--after` is the only difference between them.

- `--pages N` reads at most N pages, stopping early on the page's own `has_next_page`. It
  never stops because a page looked short.
- `--after CURSOR` resumes from an `end_cursor` an earlier run printed.
- `--posts-only` prints only the items carrying a post. The trailer still counts everything
  that arrived, so a filtered listing says how much it hid.
- `--user-agent STRING` and `--no-session-writeback` behave as they do on `thread`.

**Most of a timeline is not posts.** Every item is reported with its kind, and only items of
kind `media` carry a post. The measured split on 2026-09-21 was 7 posts out of 19 items across
two pages, the rest being `ad` and `explore_story`. `item_count`, `post_count` and `kinds` in
the JSON form are all reported for that reason: a harness that had only one of them would be
guessing the others.

**A page's length is the upstream's decision.** Three measured requests with the same
parameters returned 14, 12 and 5 items. Nothing in this command asks for a page size and
nothing infers anything from one.

Two identifiers come back on every post and they are different values, which is unusual on
this surface. `pk` is the media's own number and `id` is `"<pk>_<author id>"`. Both are in the
JSON form because guessing which one a later capability wants is the mistake this avoids.

### `note`

```bash
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta --json note list
```

`note list` reads the whole notes tray on the direct inbox, one live request, since the tray is
one unpaged call. The text form prints one line per note, the viewer's own marked `*`, with the
item id, the author, the audience and the text, then a count. The JSON form carries
`note_count`, `own_note_id`, null when the viewer has no note, and a `notes` list whose keys are
`id`, `author_id`, `author_username`, `is_own`, `text`, `audience` (`mutual_follows`,
`close_friends` or `internal`), `created_at` and `is_emoji_only`. The own note is the one whose
`author_id` equals the session's `ds_user_id`, never the first item and never an item id.

- `--user-agent STRING` and `--no-session-writeback` behave as they do on `thread`.

```bash
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta note set "TEXT" --audience close-friends
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta note delete NOTE_ID
```

`note set` and `note delete` write to the account, and take the text, the audience and the item
id as explicit arguments, with no default and no prompt, per 13.6 in
[build-plan.md](build-plan.md). `--audience` is required and is `close-friends` or
`mutual-follows`, the two the web composer offers, so a note set without naming one is refused
by the parser with exit code 2 before a client is opened, even though the library's `set_note`
defaults to close friends. A set replaces any note already up, a song note included. The note id
is the tray item id, digits only, and anything else is refused the same way. Each sends one write
and never sends it again. On exit code 11 read `dumpsta note list`: a set replaces rather than
appends, so the viewer has at most one note to find. The JSON form of `note set` is `command` and
`note`, the created note in the `note list` form, and of `note delete` it is `command`,
`note_id` and `deleted`. A set the upstream answers with another audience than the one named
ends with exit code 6, `UpstreamRejected`, code `note_audience_did_not_follow`, and that note is
up. A session saved before 2026-09-23 has no Facebook-side id, so its first `note set` loads the
inbox page once to read it and writes it back to the session file.

- `--user-agent STRING` and `--no-session-writeback` behave as they do on `thread`.

### `post`, `like` and `unlike`

```bash
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta --json post CODE
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta like PK
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta unlike PK
```

`post CODE` reads the post whose web address carries `CODE`. The text form prints the code, the
`pk`, the author and the time, then `has_liked` with the like and comment counts, then the first
caption line. The JSON form is `{"command": "post", "post": {...}}` with the keys `feed` uses for
a post, less `is_seen`, which this read does not carry.

`like PK` and `unlike PK` write to the account. The target is the post's `pk`, digits only, and
an explicit argument: there is no default and no prompt. The `<pk>_<author id>` form is refused
by the parser with exit code 2 before a client is opened. Each sends one write and never sends
it again. On exit code 11 the outcome is unknown, and the way to find out is `dumpsta post CODE`
before deciding to send again. The JSON form is `command`, `pk` and `has_liked`, the state the
upstream's answer confirmed.

- `--user-agent STRING` and `--no-session-writeback` behave as they do on `thread`.

### `comments`, `comment` and `delete-comment`

```bash
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta --json comments PK
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta comment PK "TEXT"
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta delete-comment PK COMMENT_ID
```

`comments PK` reads one page of the comments on the post whose `pk` is `PK`, and `--after
CURSOR` reads the page after an earlier one. The text form prints one line per comment, its time,
id, author and text, then a count and either the next cursor or `no more comments`. The JSON form
is `command`, `pk`, `comment_count`, `more_available`, `end_cursor` and `comments`, each comment
carrying `id`, `text`, `created_at`, `author` with `id`, `username` and `is_verified`, then
`like_count`, `reply_count`, `parent_comment_id` and `has_liked`. `more_available` is the
server's `has_next_page` and nothing else.

`comment PK TEXT` and `delete-comment PK COMMENT_ID` write to the account. Both take their target
and the text as explicit arguments: there is no default and no prompt. The post is its `pk` and
the comment its id, digits only, and anything else is refused by the parser with exit code 2
before a client is opened. Each sends one write and never sends it again. A comment appends, so
on exit code 11 read `dumpsta comments PK` and look for the viewer's own comment before sending
again, because a second send is a second comment everyone who can see the post sees. The JSON
form of `comment` is `command`, `pk` and `comment`, the created comment with its four page-only
keys null. The JSON form of `delete-comment` is `command`, `pk`, `comment_id` and `deleted`. A
delete the upstream answers as having deleted nothing ends with exit code 6, `UpstreamRejected`,
code `comment_not_deleted`.

- `--user-agent STRING` and `--no-session-writeback` behave as they do on `thread`.

### `events`

```bash
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta events --duration 600
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta --json events --duration 600 --surface async --ids-only
```

Listens through `events()` for `--duration` seconds and prints one line per event as it arrives,
flushed at once, then one summary line. There is no prompt and nothing is written to the
account: a poll reads the inbox listing and the pages of threads that gained messages, and never
opens a thread the way a browser does before marking it seen. The first poll prints nothing
unless `--since` is given. See [realtime-events.md](realtime-events.md) for what a poll sends.

- `--since MESSAGE_ID` is the last message already handled. The listener catches up from its
  time in every listed thread, and prints an `events_dropped` line with no count and no thread
  when it cannot find it.
- `--interval SECONDS` replaces `Behavior.poll_interval_seconds`, 60 by default, for this run.
  Every request still passes the pacer.
- `--surface sync`, the default, drains a `SyncClient` listener with `wait_for_events`, the way
  the Swift app will. `--surface async` iterates `AsyncClient.events` instead, on one event loop
  for the whole run.
- `--ids-only` prints a message's id, thread, sender id, time and content type and never its
  text, its sender's name or its reactions. Use it whenever the output lands in a log.
- `--user-agent STRING` and `--no-session-writeback` behave as they do on `thread`.

The text form is `new_message  SENT_AT  THREAD_FBID  SENDER_FBID  ID  TEXT` per message and
`events_dropped  count: N|unknown  thread: FBID|any` per gap marker. The JSON form is one object
per line rather than one document, because the output is a stream: `{"event": "new_message",
"message": {...}}` with the `thread` command's message keys, or the five `--ids-only` keys, and
`{"event": "events_dropped", "count": ..., "thread_fbid": ...}`. The last line is the summary,
`command`, `surface`, `duration_seconds`, `poll_interval_seconds`, `new_messages` and
`events_dropped`. A failure that ends the listener ends the command with that failure's exit
code, the blocking listener's final `ListenerStopped` included.

## Exit codes

A harness cannot branch on prose, so every deliberate failure has its own number. The mapping
is exhaustive over the public exception hierarchy and a gate asserts that, so adding a public
error class without a code fails the suite rather than quietly arriving as the generic one.
The numbers are permanent, and reordering them breaks anything that scripts the command.

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | `DumpstagramError`, or any failure with no more specific code |
| 2 | Usage: a bad command line, a missing session path, an unreadable session file |
| 3 | `AuthenticationFailed` |
| 4 | `CheckpointRequired` |
| 5 | `RateLimited` |
| 6 | `UpstreamRejected` |
| 7 | `NotFound` |
| 8 | `SchemaChanged` |
| 9 | `TransportFailure` |
| 10 | `OperationCancelled` |
| 11 | `OutcomeUnknown`: a write may or may not have applied, added 2026-09-23. `like`, `unlike`, `comment`, `delete-comment`, `note set` and `note delete` are the commands that can end with it |

Failure text goes to stderr through the library's redaction, which is the one place a cookie
reaches output with nobody having written it there.

## What it does not cover yet

The Phase 2 stop condition in [roadmap.md](roadmap.md) asks for a profile, a feed page with
working pagination, and a direct thread. All three now exist as commands, and the condition is
met.

What the feed command does not reach is anything inside a post beyond its own fields. A
carousel's slides, a video's renditions, the comments and the likers are all sent on the
payload and all dropped at the mapper, because no capability reads them yet. Video posts do
come back: one was read live on 2026-09-21 with `media_type` 2 and `product_type` `clips`,
and it mapped without its video-specific fields.

Two fields the upstream sends on a profile are not modelled, because the only live response
measured was the viewer reading the viewer and both were null on it: `friendship_status` and
`mutual_followers_count`. Reading someone else's profile is expected to populate them, and
that has not been observed.

## Verification

Forty-four gates in `tests/test_cli.py`, all offline, driven through the `Client` protocol
with a fake. `scripts/verify_cli_gates.py` breaks the source once per gate and reports red
then green, and `scripts/verify_notes_gates.py` does the same for the `note list` gate and
for the four `note set` and `note delete` gates in `tests/test_notes.py`, and
`scripts/verify_likes_gates.py` for the two `like` and `unlike` gates in `tests/test_likes.py`, and
`scripts/verify_comments_gates.py` for the four comment command gates in `tests/test_comments.py`,
and `scripts/verify_poller_gates.py` for the five `events` gates in `tests/test_cli.py`. The live acceptance run for the thread command is recorded in
`logs/cli-acceptance-2026-09-21-025734.json`: three requests, one page of 20 messages, then
two pages of 40 distinct messages in 3394 ms, which is the pacer's floor showing up as wall
time.

The profile command's live acceptance run is in
`logs/cli-profile-acceptance-2026-09-21-042735.txt`: three requests, the username route
reporting `requests_spent` 2 and the `--by-id` route reporting 1, both returning the same
account with the same counts, and the text form rendering in eight lines.

The feed command's live acceptance run is in
`logs/cli-feed-acceptance-2026-09-21-052604.txt`: two requests, two pages, 19 items of which 7
were posts and 7 were distinct, `more_available` still true at the end, and an `end_cursor`
2008 characters long. The log records author name lengths rather than names and the cursor's
length rather than the cursor, because a timeline is other people's content.

`scripts/verify_feed_gates.py` covers the feed gates in both files: seventeen mutations, each
seen red then green on 2026-09-21, logged to `logs/mutation-feed-2026-09-21-052446.json`.

The `events` command's reduced live acceptance ran 2026-09-23 through `probes/events_live.py`,
which calls the same `main` with `--json --ids-only --duration 150 --interval 60` and counts
every request at the transport. Blocking surface: three listing reads, all 200 and the same
length, nothing printed, exit 0, log `logs/events-live-sync-2026-09-23-065330.json`. Async
surface: three listing reads and one thread read, all 200, two unarranged new messages printed
as ids only, exit 0, log `logs/events-live-async-2026-09-23-065605.json`. Every request held the
account's pacer slot. The planned run of ten polls with an arranged incoming message is still
owed.
