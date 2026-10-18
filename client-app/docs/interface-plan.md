# Interface plan and the dummy engine

What the app's interface does on every interaction, what it still lacks, and what the engine
has to grow before the bridge can replace the dummy. Written 2026-09-27 against Dumpsta-Engine
1.1.0 and `engine/tests/public_surface.txt` at that version.

## Status, 2026-09-30

The bridge replaced the dummy on 2026-09-30, and the real engine is now the app's default. This
plan is kept as the record of what the dummy taught. The live ledger is the "Final state"
section of [engine-wiring-audit-2026-09-30.md](engine-wiring-audit-2026-09-30.md), and the
counts below are copied from it.

| Bucket | Count |
|---|---|
| Wired through the real engine | 58 |
| Wired with a named gap | 16 |
| Blocked | 2 |
| Engine gap remaining | 44 (11 reads, 28 writes, 4 local fields, 1 surface entry point) |
| Engine capability the app lacks or leaves unconsumed | 14 |
| Local only | 17 |
| Non-negotiable violations left in Swift | 2 |

Wired: the viewer's and other profiles by id and by username, the profile posts, reels and
tagged grids, followers, following, mutual followers and similar accounts; `hasNewPosts`
and `suggestedUsers` on Home; comments, replies, likers and more from the
author on post detail, with the `postPage` read and `post(pk:)` read-backs; like, unlike,
comment, delete comment, delete post, photo and carousel publishing, follow and unfollow; the
inbox, message requests, unread counts and the badge, send, unsend, set and delete note, and
the three event calls; download; story and highlight reels with `markStorySeen(reelID:itemID:)`;
search, explore, explore posts, keyword search, place posts, audio and audio clips; follow
requests and the activity unread dot; group member counts; session setup, the revoked and
checkpoint states, the account switcher and log out; carousel pages, avatars and remote image
loading through `Services/MediaLoader.swift`. Wired with a named gap: `feed`, `messages`,
`notes`, the location tap, video, `storiesTray`, `reels`, `activityFeed`, the saved grid,
`highlights`, `relationships`, the recents read, `savedCollections`, `searchTop`, `hashtag` and
the session row in Settings. Each renders what is missing as unknown rather than as a default.

Blocked, two: resuming writes after a write stop and changing the timing or `Behavior`. The
engine has `Session.clear_write_stop` and the `Behavior` presets, but the protocol has no
method for either, so on the real engine the app cannot lift a write stop and every client
runs PARITY.

Wired but not confirmed live in this run: post detail extras (`media.page`, likers, more from
the author, replies, the audio chip), https media loading and video, `profile(username:)`, the
inbox read, adoption from the setup view, and the story and highlight reel reads. No write was
sent live. The resume step is `REQUEST_CAP=7 client-app/scripts/run-real-engine.command
post-detail <png>`, then the "code as read matches" line.

Top three engine gaps left:

1. Mark a direct thread read. Opening a thread never sends what a browser sends, against the
   parity default of ADR-0013, and the finding `mark-a-direct-thread-read` is verified, so it
   can be built without a new run.
2. A non-blocking submit entry point. Every engine call holds the one bridge actor, so a paced
   write stalls every read on every account for about 30 s.
3. A viewer flag on `Message` and `Reaction`, with a typed media kind beside it. Both are
   surface additions with no request, and together they remove the two violations left in
   Swift.

Story replies, action 21, are an engine gap. The reply field shows the "Not wired yet" notice
on either engine and sends nothing. Before 2026-09-30 it sent a direct message in their place.

## The dummy engine

`src/InstagramPlus/Engine/Dummy/DummyEngine.swift` is an actor that conforms to the same two
protocols the bridge wrapper will conform to, so no store knows which one it is talking to.

| Protocol | File | Contents |
|---|---|---|
| `EngineClient` | `Engine/EngineClient.swift` | The 1.1.0 surface: feed, profiles, post, comments, likes, follows, photo and carousel publishing, post delete, media download, inbox, messages, requests, unread counts, send, unsend, notes, and the event listener |
| `ProposedEngineSurface` | same file | 42 capabilities the interface needs and the engine does not have. Every one is an engine gap, listed below |

The models in `Engine/EngineModels.swift` mirror the engine's public models field for field.
Fields and types marked proposed have no engine counterpart.

### What it imitates, and where each value comes from

| Behaviour | Value | Source |
|---|---|---|
| Read spacing | 1.3 s floor plus jitter spanning 0 to 4 s | `Behavior.spacing` in `engine/dumpstagram/behavior.py`. FACT |
| Write spacing | 30 s floor plus jitter spanning 0 to 10 s, from the previous write | `Behavior.write_spacing`, itself a placeholder the engine documents as derived from nothing |
| Write budget | 30 writes in any rolling hour, then `RateLimited` with `retry_after`, nothing sent | `Behavior.write_budget_per_hour` and `_refuse_past_the_budget` in `_core/pacer.py`. FACT |
| Write stop | An unrecognised rejection refuses every later write with `UpstreamRejected(writes_stopped)`, reads carry on | `stop_writes_after_unrecognised_rejection`. FACT |
| Checkpoint | Arrives as a result, stops the listener, and is never retried | ADR-0013 and the app's non-negotiables |
| Listener | Polls the inbox every 60 s on parity, reads the threads that moved, buffers `NewMessage`, survives `TransportFailure`, stops on a checkpoint | `_core/realtime/poller.py` as described in build-plan Step 23. FACT for the behaviour, the dummy does not reproduce the queries |
| Opening a thread marks it seen | The first page read clears unread | ADR-0013, the thread open precedes a mark-seen in a browser. INFERENCE |
| Network latency | 150 to 600 ms per request | ASSUMPTION, not measured |
| Replies from others | A canned reply 4 to 18 s after a send, delivered through the listener | Stands in for the second account until dual-account tests run live |

Three timings are selectable in Settings: Parity (the numbers above), Fast (the engine's `FAST`
preset, latency only, 10 s polls) and Instant (nothing, for screenshots and probes). The
default is Fast so the interface is usable during development. Parity is what a user of the
real engine gets.

### Failures it can be told to produce

Settings, Dummy engine section. Each one exercises a path the bridge will hit for real.

| Toggle | Engine error | What the interface does |
|---|---|---|
| Checkpoint on the next request | `CheckpointRequired` | Every later call is refused before it is sent. The checkpoint screen asks the person to confirm in their browser, and continuing resumes future calls without replaying the one that was interrupted |
| Revoke the session | `AuthenticationFailed` | The revoked screen, then session setup. No renewal is attempted |
| Outcome unknown on the next write | `OutcomeUnknown` | The write is applied upstream and then reported uncertain. The app reads the thing back instead of sending again, and shows a notice |
| Unrecognised rejection on the next write | `UpstreamRejected` | Writes stop. A notice explains, and Settings offers Resume writes after the person checks the account |
| Schema change on the next feed read | `SchemaChanged` | The feed shows an error state with Try again, and a notice says the engine needs an update |
| Transport failure rate | `TransportFailure` | Reads show an error state, writes roll back, the listener carries on |
| Others reply to messages you send | none | Off makes the inbox quiet |

The request log in the same section shows every request, its kind, how long the pacer held it,
and how it ended.

## What the dummy already taught

Each of these changes how the bridge or the engine has to be built. None needs Instagram to
confirm it.

1. **Every write is optimistic, and has to be.** At parity a like departs 30 to 40 s after the
   click. The interface flips the state at once, disables the control while the write is
   queued, and shows "1 action queued" in the top bar. A failure rolls back, an uncertain result
   is read back. No write is ever re-sent by the app.
2. **The serial Python queue will stall reads behind writes.** The architecture puts every
   Python call on one serial queue. `SyncClient` blocks its caller for the whole pacer wait, so
   a like at parity would hold the queue for 30 s and every feed scroll, profile open and
   message read would wait behind it. INFERENCE from the documented architecture and the
   blocking facade, not yet observed. The bridge should either drive `AsyncClient` from the
   queue, or keep a write lane separate from the read lane. This needs deciding in step 5.2.
   On 2026-09-30 the bridge shipped with every call blocking the one actor, which the verifier
   confirmed by reading the code rather than by timing a run. It is recorded as a limitation
   and as the engine gap "non-blocking submit entry point".
3. **A cold start costs about 20 s at parity.** The home page makes six reads: feed, stories,
   suggestions, profile activity, the viewer's profile and the inbox, at a mean 3.3 s apart.
   The feed goes first so the page is useful after one read, and the rest fill in behind it.
4. **Search spends a paced request per query.** The store waits for 350 ms of quiet typing
   before asking. Even so, a person typing a name in three bursts spends three requests.
5. **The engine cannot start a conversation.** `send` takes a `thread_fbid`, and nothing in
   1.1.0 creates a thread. The interface creates one through the proposed `createThread`, so
   the Message button, the new message sheet and story replies all depend on that gap.
6. **Most of the interface is proposed surface.** Of the 69 capabilities the interface calls,
   27 exist in the engine and 42 do not. Comment likes and replies, message reactions, replies
   and photos, thread muting, message requests, sharing, hiding a post, stories, highlights,
   the archive, profile editing, close friends, blocking, muting, search beyond accounts,
   hashtag and place pages, follower lists and saved posts are all dummy-only today. The post
   settings on Create (location, hidden counts, comments off) are not sent at all.
   By 2026-09-30 the engine had grown, and the audit's final state left 44 engine gaps, 28 of
   them writes. See the status section above.
7. **`publish_photo` needs an image.** Create will not share a caption on its own.
8. **The engine's `Post` has no location, share count or save count.** The mockup shows all
   three. The dummy carries location as a proposed field and the interface shows no count
   where the engine gives none.

## Pages, what triggers what

Reads and writes name the protocol method. P marks a proposed method.

| Page | On open | Actions and the write each sends | Events consumed | States handled |
|---|---|---|---|---|
| Home | `feed`, then `storiesTray` P, `suggestedUsers` P, `profileActivity` P | like or unlike, save or unsave P, comment, follow from suggestions | none | loading, error with retry, pagination, end of feed, publishing banner |
| Post detail | `post(code:)` unless cached, `comments` | like, save P, comment, delete own comment | none | loading, not found, private |
| Stories | `markStorySeen` P per author | none | none | auto advance, pause |
| Reels | `reels` P | like, save P, follow | none | loading, error |
| Messages | `inbox`, `notes`, starts the listener | send, unsend own, set note, delete note, send again after a certain failure | `NewMessage`, `EventsDropped` reloads, `ListenerStopped` | sending, not delivered, could not confirm, live badge, resume |
| Search | `explore` P, `search` P after 350 ms | none | none | searching, no results |
| Notifications | `activity` P, `followRequests` P | approve or ignore a request P, follow back | none | loading, error |
| Create | none | `publishPhoto` | none | image required, sharing |
| Profile | `profile(id:)`, `profilePosts` P, `highlights` P, then a tab's `profileReels` P, `savedPosts` P or `taggedPosts` P | follow, unfollow, follow request on a private account | none | not found, private and locked, requested |
| Followers, following | `followers` P or `following` P | follow from the list | none | loading, not found when locked |
| Settings | the dummy engine's status each second | timing, faults, resume writes | none | none |
| Session setup, checkpoint, revoked | none | connect, resume after the browser check, log out | `ListenerStopped` with a checkpoint | all three are session states, not errors |

## Views built on 2026-09-27

An audit of every control found 26 gaps: eleven buttons with no action, nine labelled as not
in the engine, and six views that did not exist. All 26 are built. Each goes through the
engine protocols like every other call, so each is paced, can fail in every way the gateway
handles, and is visible in the request log.

| Area | Built | Engine support |
|---|---|---|
| Posts | Carousel paging, video play and pause, Share sheet to threads, Copy link, Download with a save panel, Go to post, About this account, Not interested, Delete own post with confirmation, place links, `#tag` and `@mention` links in captions | Download, delete and carousel publish are real. The rest is proposed |
| Comments | Likes, replies threaded under their parent, delete own | Proposed except delete |
| Create | Two to ten images publish as a carousel | Real |
| Stories | Composer from Add story, like, reply as a direct message | Proposed, the reply uses `send` |
| Highlights | Viewer with progress and pause | Proposed |
| Messages | New message sheet with multi-select, Requests tab with accept and delete, reply with a quoted bubble, double-click and context-menu reactions, photo messages, heart message, mute switch, load earlier messages, emoji palette | Requests read and older pages are real, the rest proposed |
| Profile | Edit profile sheet, archive page, menu with close friends, mute, block and copy link, blocked state, highlight taps, remove follower from your own list | Proposed |
| Search | Accounts, Tags and Places tabs, switching to the first tab with results | Proposed |
| Hashtag and place pages | Header with count and a grid that opens posts | Proposed |
| Settings | Accounts, Privacy lists (close friends, blocked, muted), archive link | Proposed |
| Account switcher | Sidebar menu and Settings. One `AccountSession` per account, each with its own `EngineGateway` and stores, and the whole window rebuilt on switch | The engine is instance scoped, so this is the intended shape. The dummy offers a second seeded account, `vera.studio` |

Left out deliberately: calls and voice messages, which have no plausible engine path, and
live video and insights.

## Events

What the engine emits at 1.1.0 is three types, all about direct messages. The interface
already consumes all three.

| Event | Source | Interface response |
|---|---|---|
| `NewMessage` | engine listener | Appended to the open thread, the row moves to the top and turns unread if the thread is not open, an unknown thread reloads the inbox |
| `EventsDropped` | engine listener | Reload the inbox and the open thread |
| `ListenerStopped(checkpoint)` | engine listener | The checkpoint screen |
| `ListenerStopped(error)` | engine listener | The Live badge becomes Resume live |

What the interface would use and the engine does not emit: new activity (likes, comments,
follows, requests) for the notification dot, a story tray change, typing and seen indicators,
and reaction changes. Until then the notification dot is local state and clears on opening
the page.

## Verifying it

Both probes are compiled into debug builds only and run without anyone at the screen. Both
switch the dummy engine to Instant timing first.

```
Instagram+.app/Contents/MacOS/Instagram+ --exercise
Instagram+.app/Contents/MacOS/Instagram+ --snapshot-dir <path>
```

`--exercise` drives 28 interactions through the stores and prints one PASS or FAIL line
each, then `exercise summary: PASS n FAIL n of 28 expected`. It always runs on the dummy, and
since 2026-09-30 the dummy's rolls are seeded under `--exercise`, so the run is deterministic.
The first 13 cover feed, pagination, likes, uncertain and failed writes, the inbox and
listener, sending, a reply through the event buffer, the write stop, checkpoints and parity
spacing. The other 10 cover carousel publishing, accepting a message request, a reaction, older
messages, creating a conversation, a comment like, a threaded reply, blocking removing an
author from the feed, a hashtag page, and adding and switching accounts. Run 2026-09-27: 23
pass. Five checks were proven able to fail by breaking the code each guards: the read-back on
an uncertain write, the refusal while checkpointed, request acceptance, the blocked-author
filter and loading older messages. Each went red and all 23 passed once restored.
On 2026-09-30 five checks were added: a follow and an unfollow reach the engine, a second
account gets its own engine client, removing an account closes its client, and removing an
account deletes only its own session file. Each was broken and watched go red before it
counted, and the final verifier of that run quoted `exercise summary: PASS 28 FAIL 0 of 28
expected` twice.
`DUMMY_ENGINE_TRACE=1` prints every request to standard error.

`--snapshot-dir` writes 31 captures: every page, both themes where it matters, the hashtag,
place, archive, close friends, highlight, conversation and request views, the share, new
message and edit profile sheets, a notice, the checkpoint, revoked and session setup states,
and the second account.

Both probes start from the app's initialiser rather than from a view. A view's task never ran
while the display was asleep on 2026-09-27, which hung the first probe runs with nothing
written. INFERENCE that the sleeping display is the cause. The move fixed it either way.
