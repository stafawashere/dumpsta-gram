# The `dumpsta` command

The engine's first consumer, and the acceptance harness for the Phase 2 stop condition.
[ADR-0005](../../docs/decisions/ADR-0005-engine-first-build-order.md) makes it a real
consumer rather than a demo: every capability it reaches, it reaches through `SyncClient`, so
anything awkward to do from the command line is a gap in the public API rather than something
the command works around. `events --surface async` is one exception, and it goes through
the other public surface, `AsyncClient`, never past it. `doctor` is the other: it checks the
private query registry, which is not a capability and stays off the public surface, so it reaches
the canary through the private assembly function `_rotation_doctor` in `dumpstagram/aio.py` and
still imports nothing from `_core` or `_private` itself.

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
| `inbox` | an inbox page load for the first page, up to 31, then 1 per page | Lists the direct inbox, newest activity first, with each thread's `FBID`. Opens no thread, so marks nothing read |
| `message-requests` | 1, plus 1 if the session has no token yet | Lists the pending and spam message requests, one page each. Opens no request thread |
| `unread` | an inbox page load, up to 31 | Counts the unread threads in the inbox and the pending requests |
| `profile USERNAME` | 2, or 1 with `--by-id`, plus 1 if the session has no token yet | Reads one account's profile |
| `posts USERNAME` | 1 per page, plus 1 if the session has no token yet | Reads pages of an account's posts grid, twelve posts a page |
| `highlights USER_ID` | 1, plus 1 if the session has no token yet | Lists an account's story highlights, the tray's first page. Opens no story |
| `suggested USER_ID` | 1, plus 1 if the session has no token yet | Lists the accounts suggested beside an account's profile |
| `suggested-for-you` | 1, plus 1 if the session has no token yet | Lists the accounts suggested to the viewer, each with the reason the website shows |
| `followers USER_ID` | 2 per page, plus 1 if the session has no token yet | Reads pages of an account's followers with the viewer's relationship to each |
| `feed` | 1 per page, plus 1 if the session has no token yet | Reads pages of the home timeline |
| `note list` | an inbox page load, up to 31 | Reads the notes tray and marks the viewer's own note |
| `note set TEXT --audience AUDIENCE`, `note delete NOTE_ID` | 1 write, plus 1 read if the session has no token yet, or for `set` no Facebook-side id | Sets the viewer's note, replacing any note up, or deletes it. Writes to the account |
| `post CODE`, `post --by-id PK` | 1, plus 1 if the session has no token yet | Reads one post by its shortcode, or by its `pk`, with its `pk` and the viewer's like state |
| `like PK`, `unlike PK` | 1 write, plus 1 read if the session has no token yet | Likes or unlikes one post. Writes to the account |
| `follow USER_ID`, `unfollow USER_ID` | 1 write, plus 1 read if the session has no token yet | Follows or unfollows one account. Writes to the account, and the account is notified of a follow |
| `comments PK` | 1, plus 1 if the session has no token yet | Reads one page of a post's comments, with each comment's id |
| `replies PK COMMENT_ID` | 1 per page, plus 1 if the session has no token yet | Reads pages of the replies under one comment, oldest first |
| `likers PK` | 1, plus 1 if the session has no token yet | Lists the accounts the likes dialog shows for one post, a sample on a popular post |
| `more-from-author AUTHOR_ID` | 1, plus 1 if the session has no token yet | Lists the posts a post page shows from its author |
| `stories-tray` | 1, plus 1 if the session has no token yet | Lists the accounts in the stories tray. Reads no items and marks nothing seen |
| `story USER_ID` | 1 and 1 write, plus 1 if the session has no token yet; 1 with `--no-mark-seen` | Reads one account's live stories, every item, and marks the first item seen, which the account sees |
| `highlight HIGHLIGHT_ID` | 1 and 1 write, plus 1 if the session has no token yet; 1 with `--no-mark-seen` | Reads one highlight, every item, and marks the first item seen, which its owner sees |
| `story-seen REEL_ID ITEM_PK` | 1 and 1 write, plus 1 if the session has no token yet | Marks one story item seen. Writes to the account, and the item's owner sees you among its viewers |
| `follow-requests` | 1 | Lists the accounts asking to follow the viewer, the first page, and whether more exist |
| `activity` | 1, plus 1 if the session has no token yet | Reads the viewer's activity feed. Marks nothing seen |
| `explore` | 1 | Reads the explore grid's first page, section by section, and whether it goes on |
| `place LOCATION_ID` | 1, plus 1 if the session has no token yet | Reads a place's header: name, category, address, coordinates and post count |
| `location LOCATION_ID` | 1, plus 1 if the session has no token yet | Reads the first page of the posts tagged at a place, and whether more exist |
| `new-posts` | 1, plus 1 if the session has no token yet | Asks whether the home feed has new posts |
| `recent-searches` | 1, plus 1 if the session has no token yet | Reads your recent searches, accounts and keywords |
| `search QUERY` | 1, plus 1 if the session has no token yet | Reads the accounts QUERY matches, ranked without your profile |
| `hashtag TAG` | 1, plus 1 if the session has no token yet | Reads a hashtag's header, its id |
| `comment PK TEXT`, `delete-comment PK COMMENT_ID` | 1 write, plus 1 read if the session has no token yet | Comments on one post, or deletes one comment. Writes to the account |
| `send-message FBID TEXT` | 1 write, plus 1 read if the session has no token yet | Sends one text message into one direct thread. Writes to the account, and the thread's other people are notified |
| `unsend-message FBID MESSAGE_ID` | 1 read and 1 write, plus 1 read if the session has no token yet | Unsends one of the viewer's own messages. Writes to the account |
| `publish-photo IMAGE` | 2 writes and 1 read, plus 1 read if the session has no token yet | Uploads one JPEG, publishes it as a post and reads it back by its code. Writes to the account, visible to everyone who can see it |
| `publish-carousel IMAGE IMAGE...` | 1 write per image, 1 more and 1 read, plus 1 read if the session has no token yet | Publishes two or more JPEGs as one carousel and reads it back. Writes to the account |
| `delete-post PK CODE` | 1 write and 1 read, plus 1 read if the session has no token yet | Deletes one of the viewer's own posts and reads it to confirm it is gone. Writes to the account |
| `events --duration SECONDS` | 1 per poll, plus 1 per page of a thread that gained messages, plus 1 if the session has no token yet | Prints new direct messages as they arrive, for a fixed time. Marks nothing seen |
| `doctor` | 0 without `--live`. With it, 2 documents and at most 24 reads, paced, plus the bundle fetches, cookieless and unpaced, 1000 at most | Checks every stored `doc_id` against the one the site's bundles compile, and replays each read once. Writes and companions are checked by artifact only and never sent |

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

```bash
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta session --clear-write-stop
```

`--clear-write-stop` lifts the write stop kept in the pacing ledger beside the session file,
`state/session.json.ledger`, and adds `write_stop_cleared` to the output, True when a stop was
set. It keeps the hour's write departures, so the budget still counts them. It spends no live
request. Run it only after a person has looked at the account, since the stop is set by a
rejection nothing recorded explains, the likeliest form of an action block. It goes
through `dumpstagram.session.clear_write_stop`. A ledger that cannot be read is left as it is
and the command exits 8, `SchemaChanged`. Deleting that file by hand lifts the
stop and also forgets the hour's writes.

Every command built from a session file shares that ledger, so a write budget spent by one
`dumpsta` process is spent for the next, and a stop one of them saw refuses writes in the rest.

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
Each message in the JSON form carries `offline_threading_id`, the identifier the sending client
generated, which is how `send-message` output is matched to the message it created.

Tokens harvested during a read are written back to the session file by default. Without it
every invocation pays a bootstrap request the previous one already paid for.

### `inbox`, `message-requests` and `unread`

```bash
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta inbox --pages 2
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta --json message-requests
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta unread
```

`inbox` prints one entry per thread in the upstream's order: the last activity, the `FBID`
`thread` takes, the title, the flags that apply (`unread`, `pinned`, `muted`, `group`) and the
upstream's one-line preview. `--pages N` reads at most `N` pages, default 1, and stops earlier on
the page's own `has_next_page`. `--after CURSOR` takes a `next_cursor` an earlier `inbox` run
printed and no other, because that cursor carries the mailbox the next page is keyed on (W46).
The JSON form carries `pages_read`, `thread_count`, `more_available`, `end_cursor` and every
thread with its participants.

`message-requests` prints the pending and the spam folder, one page each, with
`more_available` on a folder that has more. No request thread is opened, because opening one
marks it seen to its sender.

`unread` prints `unread inbox: N  pending requests: M`, and marks a count with `+` when its
folder has rows past the first page the count is taken over. A thread counts as unread when it is
marked unread or the viewer's read receipt is older than its last activity, the engine's reading
of the rows rather than the website's own rule (W47).

Since E2 batch 9 `inbox` reads its first page, and `unread` its counts, from a load of the direct
inbox as a browser reads them, which needs no stored token: the document, the ten queries of its
direct block together, and the page's companions, 31 requests with a full first page (W87 to
W89). `note list` does the same. A later `inbox` page is one request. `Behavior.inbox_route`
chooses the route in the library; the commands run the default behavior.

All three take `--user-agent` and `--no-session-writeback`, and write harvested tokens back by
default. Live on 2026-09-24 through `probes/e2_direct_read_cli_acceptance.py`, 5 requests: two
inbox pages of 15 threads each, both request folders empty, and one unread thread that the
listing and the count agreed on.

### `posts`, `highlights`, `suggested` and `suggested-for-you`

```bash
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta posts some.account --pages 2
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta --json highlights 1234567890
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta suggested 1234567890
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta suggested-for-you
```

`posts` prints one line per post in the grid's order, pinned posts first: the time, the
shortcode `post` takes, the counts and the caption's first line. `--pages N` reads at most `N`
pages of twelve, default 1, and stops earlier on the page's own `has_next_page`. `--after
CURSOR` takes a `next_cursor` an earlier `posts` run printed for the same account. The JSON form
carries `pages_read`, `post_count`, `more_available`, `end_cursor` and every post in the form
`feed` prints one, `is_seen` always false (W53).

`highlights` prints each highlight's id and title, then `highlights: N`, marked
`more_available: True` when the tray has more than the first page, which is all that can be read
(W54). No story is opened or marked seen.

`suggested` prints one line per account suggested beside the profile: the id, the username, the
name and whether the viewer follows it. `suggested-for-you` prints the same line for each account
suggested to the viewer, with the reason the website shows under it on the next line. The JSON
forms carry each account's `id`, `username`, `full_name`, `is_verified`, `is_private` (null on
the suggested accounts list, which does not send it), both pictures and `friendship_status`
with its eight flags, and `suggested-for-you` each `reason` (W55).

`highlights` and `suggested` take the numeric account id, which `profile` prints, and refuse a
username with exit 2 before anything is sent. All four take `--user-agent` and
`--no-session-writeback`, and write harvested tokens back by default. The live acceptance,
`probes/e2_profile_tabs_cli_acceptance.py`, ran on 2026-09-27 with every step exit 0 and 7
requests.

### `followers`

```bash
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta followers 1234567890 --pages 2
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta --json followers 1234567890
```

`followers` prints one line per follower in the upstream's order, in the form `suggested` uses:
the id, the username, the name and whether the viewer follows the account, then `pages_read`,
`accounts` and `more_available`, and `next_cursor` when more exist. `--pages N` reads at most `N`
pages, default 1, and stops earlier on the page's own `has_more`. `--after CURSOR` takes a
`next_cursor` an earlier `followers` run printed for the same account. The JSON form carries
`pages_read`, `account_count`, `more_available`, `end_cursor` and every account in the form
`suggested` prints one, `friendship_status` with `followed_by` and `blocking` always null, since
the statuses the list reads do not carry them (W59). Each page is two requests, the page and the
relationship statuses a browser's list sends beside it (W58, W59). It takes the numeric account
id and refuses a username with exit 2 before anything is sent. There is no `--limit` (W60). The
live acceptance, `probes/e2_follow_lists_cli_acceptance.py`, ran on 2026-09-27, 5 requests, both steps exit 0.

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

The JSON form carries `friendship_status`, the viewer's relationship to the account: null on the
viewer's own profile, and otherwise the ten flags of `FriendshipStatus`, `following`,
`followed_by`, `outgoing_request`, `incoming_request`, `blocking`, `muting`, `is_muting_reel`,
`is_restricted`, `is_bestie` and `is_feed_favorite`. The text form adds one line with the first
three. It is how `follow` and `unfollow` are confirmed.

### `follow` and `unfollow`

```bash
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta follow USER_ID
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta unfollow USER_ID
```

Both write to the account, and the account is notified of a follow. The target is the account's
numeric id, the `id` that `dumpsta profile USERNAME` prints, as an explicit argument with no
default and no prompt. A username, or anything that is not digits, is refused by the parser with
exit code 2 before a client is opened. Each sends one write and never sends it again. The JSON
form is `command` and `user_id`, and it claims no resulting state, because the upstream's answer
cannot tell a follow from a follow request: a follow of a private account becomes a request, and
the answer then reports `following` false. Read `dumpsta profile --by-id USER_ID` for
`following` and `outgoing_request`, which is also what to do on exit code 11 before sending
again. An unfollow the upstream answers as still following ends with exit code 6,
`UpstreamRejected`, code `following_did_not_end`.

- `--user-agent STRING` and `--no-session-writeback` behave as they do on `thread`.

### `send-message` and `unsend-message`

```bash
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta send-message FBID TEXT
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta unsend-message FBID MESSAGE_ID
```

Both write to the account. `send-message` sends TEXT into the thread whose `thread_fbid` is FBID,
the value `thread` takes, and the thread's other people are notified and may read it at once. The
thread must exist. The thread and the text are explicit arguments with no default and no prompt,
and an FBID that is not digits is refused by the parser with exit code 2 before a client is
opened. The JSON form is `command`, `thread_fbid` and `message`, which carries the new message's
`id`, `thread_fbid`, `sent_at` and `offline_threading_id`. `dumpsta thread FBID --json` prints the
same `offline_threading_id` on the message it created. A send is never sent again. On exit code
11 read `dumpsta thread FBID` before deciding to send again, because a second send is a second
message.

`unsend-message` unsends the viewer's own message MESSAGE_ID, the `mid.` string `send-message`
and `thread` print, and anything else is refused by the parser with exit code 2. It opens the
thread first, because the unsend names the thread by an identifier only the thread open carries,
so it spends one read and one write. The JSON form is `command`, `thread_fbid`, `message_id` and
`unsent` true. An unsend the upstream answers as not applied ends with exit code 6,
`UpstreamRejected`, code `message_not_unsent`. The recipient may already have read the message.
Read `dumpsta thread FBID` afterwards: an unsent message is no longer listed.

- `--user-agent STRING` and `--no-session-writeback` behave as they do on `thread`.

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

`note list` reads the whole notes tray on the direct inbox from a load of the inbox, as `inbox`
does (W87), since the tray is one unpaged call of the page's direct block. The text form prints one line per note, the viewer's own marked `*`, with the
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
caption line. The JSON form is `{"command": "post", "by_id": false, "post": {...}}` with the keys
`feed` uses for a post, less `is_seen`, which this read does not carry.

`post --by-id PK` reads the post by its `pk` instead, as `profile --by-id` reads a profile by its
id, and refuses anything but digits with exit code 2 before anything is sent. `by_id` is true in
its JSON form. Its answer carries less than the shortcode read's: `carousel_media_count` counts
the slides while the slides themselves are not listed, and `accessibility_caption` and
`collaborators` are null because the answer does not carry them (W63).

Since E2 batch 4 a post's JSON form, in `feed`, `posts` and `post`, also carries `location`
(`id`, `name`, `lat`, `lng`, or null), `user_tags` (each an `account` in the form `suggested`
prints one, and a `position` of two numbers or null) and `collaborators` (accounts in the same
form). The two lists are empty when the post has none and null when the read does not say (W65).

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

### `replies`, `likers` and `more-from-author`

```bash
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta replies PK COMMENT_ID --pages 2
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta --json likers PK
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta more-from-author AUTHOR_ID
```

`replies PK COMMENT_ID` reads the replies under one comment, a comment `comments PK` lists with a
`reply_count` above zero, one line per reply in the `comments` form, oldest first, then
`pages_read`, `replies` and `more_available`, and `next_cursor` when more exist. `--pages N` reads
at most `N` pages, default 1, and stops earlier on the page's own `has_next_page`. `--after CURSOR`
takes a `next_cursor` an earlier run printed for the same comment. The JSON form carries
`command`, `pk`, `comment_id`, `pages_read`, `reply_count`, `more_available`, `end_cursor` and
`replies`, each in the form `comments` prints a comment, with `reply_count` null (W61).

`likers PK` lists the accounts the likes dialog shows, in the form `suggested` prints them, then
how many. The JSON form is `command`, `pk`, `account_count` and `accounts`. The count is the
list's length, not the post's likes: on a popular post the list is a sample (W62).

`more-from-author AUTHOR_ID` lists the strip of posts a post page shows from its author, one line
per post with its code, `pk`, counts and first caption line, then how many. It takes the author's
numeric id, `author.id` in a post's JSON form, and refuses a username with exit 2. The JSON form
is `command`, `author_id`, `post_count` and `posts`, each with `id`, `pk`, `code`, `author_id`,
`author_username`, `media_type`, `product_type`, `like_count`, `comment_count`,
`like_and_view_counts_disabled`, `caption`, `carousel_media_count` and `images` (W64).

Every post and comment id is digits only, and anything else is refused by the parser with exit
code 2 before a client is opened. All three take `--user-agent` and `--no-session-writeback`.
The live acceptance, `probes/e2_post_depth_cli_acceptance.py`, ran on 2026-09-27 with every step exit 0 and 11 requests, after a first run stopped at `post --by-id` on a reel and led to W63's original sound gap: 94 likers, 1 reply on one page, the reel by pk with 2 user tags, and 6 posts from its author, log `logs/e2-post-depth-cli-2026-09-27-033207.json`.

### `stories-tray`, `story`, `highlight` and `story-seen`

```bash
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta stories-tray
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta --json story 1234567890
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta story --no-mark-seen 1234567890
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta highlight highlight:17912345678901234
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta story-seen highlight:17912345678901234 3456789012345678901
```

**`story` and `highlight` mark the first item seen, and the account sees you among that item's
viewers**, as opening the story on the website does (W94, W95). The mark is a write after the
read: it counts against the write budget, and if it fails the command exits with the write's
error and prints no reel. `--no-mark-seen` reads without marking anything. `stories-tray` marks
nothing. `story-seen REEL_ID ITEM_PK` reads the reel `REEL_ID`, an account's numeric id or a
`highlight:<number>`, with marking off, then marks its item `ITEM_PK` seen, two requests; it prints
`marked seen: ITEM_PK in REEL_ID`, and its JSON form is `command`, `reel_id`, `item_pk` and
`marked_seen`. A reel with no live story, or no item with that pk, exits 7, and an `ITEM_PK` that
is not digits exits 2 before a client is opened.

`stories-tray` prints one line per account in the tray's order, its rank, account id, username,
the time of its latest item and when you last saw it, or `never`, then `reels: N`. The JSON form
is `command`, `reel_count` and `reels`, each with `id`, `reel_type`, `owner` (`id`, `username`,
`profile_pic_url`, `hd_profile_pic_url`, `is_verified`, `is_private`), `latest_item_at`,
`expiring_at`, `seen_at`, `ranked_position`, `muted` and `has_close_friends_items` (W69).

`story USER_ID` reads the live stories of the account whose numeric id is `USER_ID`, and
`highlight HIGHLIGHT_ID` one highlight, in the `highlight:<number>` form `highlights` prints. Both
print the reel's id, owner and title, one line per item with its time, `pk` and kind, then
`items: N`; `story` prints `no live story` when the account has none. The JSON form is `command`,
the id asked, `marked_first_item_seen`, `item_count` and `reel`, null when there is no live
story, with `id`, `reel_type`,
`title`, `cover_url`, `owner`, `latest_item_at`, `can_reshare` and `items`, each with `id`, `pk`,
`code`, `owner_id`, `media_type`, `product_type`, `taken_at`, `expiring_at`, `original_width`,
`original_height`, `audience`, `can_reply`, `can_reshare`, `is_paid_partnership`,
`is_story_edited`, `has_audio`, `video_duration`, `images`, `videos` (`url`, `version_type`),
`mentions` (`username`, `full_name`) and `music` (`title`, `artist`, `should_mute`) (W70).

`story` refuses a username and `highlight` a bare number, with exit code 2 before a client is
opened. All four take `--user-agent` and `--no-session-writeback`. The live acceptance,
`probes/e2_stories_cli_acceptance.py`, reads the tray, the owner's own reel and his first
highlight, four requests, and no other account's reel, since batch 12 with `--no-mark-seen` on
both reads; `probes/e2_story_seen_cli_acceptance.py`, written for batch 12 and not run, marks the
first and second items of the owner's own first highlight through `highlight` and `story-seen`,
five requests. The batch 5 acceptance ran on 2026-09-27 with every step exit 0 and 4 requests, each a read query and none a seen mutation: 33 tray reels, no live reel of the owner's, 1 highlight and its 18 items, log `logs/e2-stories-cli-2026-09-27-035531.json`.

### `follow-requests` and `activity`

```bash
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta follow-requests
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta --json activity
```

`follow-requests` prints one line per account asking to follow you, its id, username and full
name, then `accounts: N  more_available: B`. Only a private account receives requests, and no
next page is read (W73). The JSON form is `command`, `account_count`, `more_available` and
`accounts`, each in the `followers` row form.

`activity` prints one line per item, its time, kind and text as the website shows it, then `new:
N  earlier: N  priority: N  last_page: B`. It does not mark the feed seen, so your notifications
badge is left as it was (W74). The JSON form is `command`, `new_count`, `earlier_count`,
`priority_count`, `is_last_page`, `last_checked_at`, `counts` (the fifteen counters), `sections`
(`title`, `first_index`), and `new_items`, `earlier_items` and `priority_items`, each item with
`id`, `kind`, `story_type`, `created_at`, `text`, `links` (`start`, `end`, `kind`, `id`,
`username`), `media` (`id`, `shortcode`, `image_url`), `account_id`, `account_username`,
`account_pic_url`, `second_account_id`, `second_account_pic_url`, `follow_account` in the row
form or null, `comment_id` and `destination`.

Both take `--user-agent` and `--no-session-writeback`. The live acceptance,
`probes/e2_own_account_cli_acceptance.py`, runs both on the owner's own account, two requests,
and checks each sent exactly one API request; it ran on 2026-09-27 with both steps exit 0 and one API request each, so no `news/inbox_seen` went out: 1 follow request, 69 activity items and `is_last_page` true, log `logs/e2-own-account-cli-2026-09-27-042111.json`.

### `explore`, `place`, `location` and `new-posts`

```bash
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta explore
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta --json place 212345678901234
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta location 212345678901234
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta new-posts
```

`explore` prints each section's heading, then one line per post, its shortcode, author, likes,
comments and the first line of its caption, the large tile's post marked `featured`, then
`sections: N  posts: N  more_available: B`. Only the first page is read (W77). The JSON form is
`command`, `section_count`, `post_count`, `more_available` and `sections`, each with `feed_type`,
`featured` and `posts` in the `post` command's form.

`place` prints the place's name, id and category, its post count and coordinates, and its
address and phone where it has them. The JSON form is `command` and `place`, with `id`, `name`,
`category`, `lat`, `lng`, `media_count`, `slug`, `address`, `city`, `zip_code`, `phone` and
`price_range` (W78).

`location` prints one line per post on the first page of the place's ranked grid, its shortcode,
author, likes, comments and caption, then `posts: N  more_available: B`. No later page is read,
because the query that pages the grid answered the cursor it was sent (W79). The JSON form is
`command`, `location_id`, `post_count`, `more_available` and `posts`, each in the
`more-from-author` form.

`new-posts` prints `new_posts: B`, and its JSON form is `command` and `new_posts` (W80).

`place` and `location` take the numeric place id a tagged post's `location.id` carries, and
refuse anything else with exit 2. All four take `--user-agent` and `--no-session-writeback`. The
live acceptance, `probes/e2_discovery_feeds_cli_acceptance.py`, runs `explore`, then `place` and
`location` on the first place a post on the grid names, then `new-posts`, four requests, and
checks that no next page query went out. It ran on 2026-09-27 with every step exit 0 and 4 requests, none a next page query: 4 explore sections and 20 posts, a place header, 21 posts on its grid and no new posts, log `logs/e2-discovery-feeds-cli-2026-09-27-045328.json`.

### `recent-searches`, `search` and `hashtag`

```bash
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta recent-searches
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta --json search cats
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta hashtag cats
```

`recent-searches` prints one line per entry in the upstream's order, `account` with the account's
id, username and full name, `keyword` with the text searched, or the bare kind `hashtag` or
`place`, whose shape has not been read, then `recent searches: N` (W82). The JSON form is
`command`, `entry_count` and `entries`, each with `kind` (`user`, `keyword`, `hashtag` or
`place`), `account` in the `followers` row form or null, and `keyword` or null.

`search` prints one line per account the non-personalised typeahead answers, its id, username and
full name, then `accounts: N`. Hashtags and places are not read, and nothing is added to your
recent searches (W83). The JSON form is `command`, `query`, `account_count` and `accounts` in the
`followers` row form. A blank query exits 2.

`hashtag` prints `#TAG  id ID`, and its JSON form is `command` and `hashtag`, with `id` and `name`
(W84). TAG is the name without its `#`, letters, digits and underscores, and anything else exits 2.

All three take `--user-agent` and `--no-session-writeback`. The live acceptance,
`probes/e2_search_cli_acceptance.py`, runs the three commands, three requests, and checks that
each sent its own query and none the personalised typeahead or the keyword grid. It ran on 2026-09-27 with every step exit 0 and 3 requests, each its own query: 15 recent searches (4 accounts, 11 keywords), 18 accounts for the query and the tag's id, log `logs/e2-search-cli-2026-09-27-051346.json`.

### `publish-photo`, `publish-carousel` and `delete-post`

```bash
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta --json publish-photo square.jpg
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta --json publish-carousel a.jpg b.jpg
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta --json delete-post PK CODE
```

Landed 2026-09-23, E1 item 9. All three write to the account, with no prompt and no default
target. Each image is a JPEG file, and anything else ends with exit code 2 before a request is
sent, as does a carousel of one image, which is refused before a client is opened. `--caption
TEXT` sets the caption, empty unless given. Nothing is sent about a location, a tag or a
collaborator.

A publish reads its post back by its code in the same process and reports whether the read
shows the viewer's own post with the same `pk`, `code` and `media_type`. The JSON form is
`command`, `post` (`pk`, `id`, `code`, `taken_at`, `media_type`, `upload_ids`), `read_back`
(the `post` command's keys, or null) and `confirmed`. When the read after the publish fails the
post is still printed, with `read_back_error` naming the class and `confirmed` false, and the
exit code is the read's, so the code of a post that is up is never lost. When the publish fails
after an upload applied, stderr carries the error and then a `posting:` line naming the half that
failed and the orphaned upload ids. On exit code 11 read `dumpsta profile --by-id` for the viewer
and compare `media_count` before publishing again.

`delete-post PK CODE` takes the post's `pk`, digits only, and its shortcode, deletes it, then
reads the code again. The JSON form is `command`, `pk`, `code`, `deleted`, `gone` and, when the
read was refused, `read_refused_with`. `gone` is true only when the read is refused with code
`1675030`, which is how the upstream answered the read of each of the five deleted posts the
engine read back, and then the exit code is 0. A post that still reads back is `gone` false with
exit code 6. A read refused with another code, or failing some other way, is `gone` null with
that failure's exit code.

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

### `doctor`

```bash
uv run dumpsta doctor
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta --json doctor --live
```

The rotation canary, E1 item 7 of [web-parity-plan.md](web-parity-plan.md), rulings W31 to W33.
Without `--live` it opens no session and sends nothing: it prints what a live run would send, the
two documents, the ten reads it would replay, the bundle limit, and the ten writes and ten
companions it compares by artifact only. The JSON form is `command`, `live` false and `plan`.

With `--live` it first prints that count on stderr, then loads the inbox document the bootstrap
reads and the home document, collects every bundle on `static.cdninstagram.com` the two name,
and reads each for the `doc_id` its operations compile to, stopping once every stored operation
is found or at `--bundle-limit N`, 1000 by default. Then it replays each capability read once
through that capability's own request builder and mapper, taking a thread from the inbox, a post
and its author from the timeline, a comment with replies from that post's comments, a
username from the viewer's own profile and the first highlight on the viewer's own highlights tray, and skipping a read whose argument never turned up. The documents and reads pass the account's pacer. The bundles go
through a cookieless transport pinned to the static host and take no pacer slot. Nothing is
retried, and a checkpoint ends the run with exit code 4 and no report.

One line per stored operation: the bundle verdict, the replay verdict, the role, the operation,
the stored id and the compiled ids, then the error class and code of a failed replay or the
reason a read was skipped. The bundle verdict is `ok` when the bundles compile exactly the
stored id, `drift` when they compile another, and `missing` when no scanned bundle compiles it,
with a note when the operation's `.graphql` artifact was seen without its id module. The replay
verdict is `ok`, `failed`, `skipped`, or `artifact_only` for a write or a companion. A summary
line counts documents, bundles named, fetched and failed, reads sent, drift, missing and failed
replays. The JSON form adds `summary` and `operations` with those keys.

`missing` is not drift. Five engine operations, the note create and delete, the direct unsend,
`useIGDMessageListPaginationQuery` and `IGDOmniPickerNullStateListQuery`, were found by the
census only in chunks a page loads later, which no document names, so they are expected to read
`missing`. `--user-agent STRING` and `--no-session-writeback` behave as they do on `thread`.

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
| 11 | `OutcomeUnknown`: a write may or may not have applied, added 2026-09-23. `like`, `unlike`, `follow`, `unfollow`, `comment`, `delete-comment`, `send-message`, `unsend-message`, `note set`, `note delete`, `publish-photo`, `publish-carousel`, `delete-post`, `story-seen`, and `story` and `highlight` without `--no-mark-seen`, are the commands that can end with it |
| 12 | `doctor --live` only: a stored `doc_id` differs from the one the site's bundle compiles |
| 13 | `doctor --live` only: no `doc_id` drifted, and a read replayed once came back failed |

Failure text goes to stderr through the library's redaction, which is the one place a cookie
reaches output with nobody having written it there. Since 2026-09-23 each note the exception
carries follows it on its own line, redacted the same way, so the seam note a blocking call adds
and the `posting:` note naming an orphaned upload both reach the user.

## What it does not cover yet

The Phase 2 stop condition in [roadmap.md](roadmap.md) asks for a profile, a feed page with
working pagination, and a direct thread. All three now exist as commands, and the condition is
met.

What the feed command does not reach is anything inside a post beyond its own fields. A
carousel's slides, a video's renditions, the comments and the likers are all sent on the
payload and all dropped at the mapper, because no capability reads them yet. Video posts do
come back: one was read live on 2026-09-21 with `media_type` 2 and `product_type` `clips`,
and it mapped without its video-specific fields.

One field the upstream sends on a profile is not modelled, `mutual_followers_count`. It is null
on the viewer's own profile and was a number on another account's on 2026-09-23, and nothing yet
says what it counts against. `friendship_status`, the other field that was null on the viewer's
own profile, is modelled since Step 17.

## Verification

Forty-four gates in `tests/test_cli.py`, all offline, driven through the `Client` protocol
with a fake. `scripts/verify_cli_gates.py` breaks the source once per gate and reports red
then green, and `scripts/verify_notes_gates.py` does the same for the `note list` gate and
for the four `note set` and `note delete` gates in `tests/test_notes.py`, and
`scripts/verify_likes_gates.py` for the two `like` and `unlike` gates in `tests/test_likes.py`, and
`scripts/verify_follows_gates.py` for the three `follow`, `unfollow` and profile JSON gates in
`tests/test_follows.py`, and `scripts/verify_direct_send_gates.py` for the five `send-message`
and `unsend-message` mutations on the three gates in `tests/test_direct_send.py`, and
`scripts/verify_comments_gates.py` for the four comment command gates in `tests/test_comments.py`,
and `scripts/verify_poller_gates.py` for the five `events` gates in `tests/test_cli.py`, and
`scripts/verify_posting_gates.py` for the eight posting command gates in `tests/test_posting.py`, and `scripts/verify_direct_read_gates.py` for the four `inbox`, `unread` and `message-requests` mutations on the three command gates in `tests/test_direct_read.py`, and `scripts/verify_profile_tabs_gates.py` for the six `posts`, `highlights`, `suggested` and `suggested-for-you` mutations on the four command gates in `tests/test_profile_tabs.py`, and `scripts/verify_follow_lists_gates.py` for the five `followers` mutations on the three command gates in `tests/test_follow_lists.py`, and `scripts/verify_post_depth_gates.py` for the five `replies`, `post --by-id` and `more-from-author` mutations on the three command gates in `tests/test_post_depth.py`, and `scripts/verify_stories_gates.py` for the six `stories-tray`, `story` and `highlight` mutations on the two command gates in `tests/test_stories.py`, and `scripts/verify_account_gates.py` for the four `follow-requests` and `activity` mutations on the two command gates in `tests/test_account.py`, and `scripts/verify_discovery_gates.py` for the six `explore`, `place`, `location` and `new-posts` mutations on the two command gates in `tests/test_discovery.py`, and `scripts/verify_search_gates.py` for the seven `recent-searches`, `search` and `hashtag` mutations on the two command gates in `tests/test_search.py`. The live acceptance run for the thread command is recorded in
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

The posting commands' live acceptance ran 2026-09-23 through `probes/posting_cli_acceptance.py`,
which drives `uv run dumpsta --json` subprocesses with every request counted: `profile --by-id`,
`publish-photo`, `delete-post`, `publish-carousel`, `delete-post`, `profile --by-id`, thirteen
requests, ten to www.instagram.com and three to i.instagram.com. Both publishes were confirmed by
their read back, the carousel's with `carousel_media_count` 2, both deletes reported `gone` true
on `read_refused_with` `1675030`, and `media_count` was 8 before and after. Log
`logs/posting-cli-acceptance-2026-09-23-233411.json`.
