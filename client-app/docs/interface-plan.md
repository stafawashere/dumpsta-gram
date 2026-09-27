# Interface plan and the dummy engine

What the app's interface does on every interaction, what it still lacks, and what the engine
has to grow before the bridge can replace the dummy. Written 2026-09-27 against Dumpsta-Engine
1.1.0 and `engine/tests/public_surface.txt` at that version.

## The dummy engine

`src/InstagramPlus/Engine/Dummy/DummyEngine.swift` is an actor that conforms to the same two
protocols the bridge wrapper will conform to, so no store knows which one it is talking to.

| Protocol | File | Contents |
|---|---|---|
| `EngineClient` | `Engine/EngineClient.swift` | The 1.1.0 surface: feed, profiles, post, comments, likes, follows, publish, delete, inbox, messages, requests, unread counts, send, unsend, notes, and the event listener |
| `ProposedEngineSurface` | same file | 19 capabilities the interface needs and the engine does not have. Every one is an engine gap, listed below |

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
3. **A cold start costs about 20 s at parity.** The home page makes six reads: feed, stories,
   suggestions, profile activity, the viewer's profile and the inbox, at a mean 3.3 s apart.
   The feed goes first so the page is useful after one read, and the rest fill in behind it.
4. **Search spends a paced request per query.** The store waits for 350 ms of quiet typing
   before asking. Even so, a person typing a name in three bursts spends three requests.
5. **The engine cannot start a conversation.** `send` takes a `thread_fbid`, and nothing in
   1.1.0 creates a thread. The Message button on a profile only works when a thread already
   exists, and says so otherwise.
6. **Several controls have no write behind them.** Comment likes, message reactions, muting a
   thread, marking one unread, editing a profile, and the post settings on Create (location,
   hidden counts, comments off) are shown and explain that the engine lacks them.
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

## Views still to build

Ordered by what the engine can back today, then by how much of the interface depends on it.

| View | Engine support | Needs |
|---|---|---|
| Message requests tab | `message_requests` exists | A list view reusing thread rows, and accept or delete, which the engine lacks |
| Inbox pagination and older messages | `inbox(after:)` and `messages(after:)` exist | Load more at the list ends |
| Post delete, own posts | `delete_post` exists | A confirm dialog in the post menu |
| Media download | `media.download` exists | Save to disk from the post menu |
| Carousel paging and video playback | renditions exist on `Post` | A pager in the media view, and an AVPlayer for `VideoRendition` |
| Highlight viewer | none | Engine highlights read, then the story viewer reused |
| Story creation | none | Engine story publish |
| New conversation and group creation | none | Engine thread create |
| Message reactions, replies, photos | none | Engine writes for each |
| Comment likes and replies | reply ids exist on `Comment`, no write | Engine writes |
| Edit profile, archive, close friends, blocked and muted | none | Engine reads and writes |
| Hashtag and place pages, search tabs | none | Engine search beyond users |
| Account switcher | the engine is instance scoped already | One `EngineGateway` per account, and a switcher in the sidebar. Dual-account testing wants this first |
| Share sheet | none | Sending a post into a thread, an engine write |
| Live, insights | none | Out of scope for now |

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

`--exercise` drives 13 interactions through the stores and prints one PASS or FAIL line
each: feed, pagination, a like reaching the engine, an uncertain unlike read back rather than
resent, a failed like rolled back, the inbox and listener, a send settling, a reply arriving
through the event buffer, a write stop, a checkpoint halting the session, nothing sent while
checkpointed, resuming, and parity spacing two reads. Run 2026-09-27: 13 pass. Two checks were
proven able to fail by removing the read-back on an uncertain write and the gateway's refusal
while checkpointed: both went red, and one other check went red with them, then all 13
passed again once restored. `DUMMY_ENGINE_TRACE=1` prints every request to standard error.

`--snapshot-dir` writes 19 captures: every page, both themes where it matters, a notice, and
the checkpoint, revoked and session setup states.

Both probes start from the app's initialiser rather than from a view. A view's task never ran
while the display was asleep on 2026-09-27, which hung the first probe runs with nothing
written. INFERENCE that the sleeping display is the cause. The move fixed it either way.
