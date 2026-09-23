# Overnight handoff, 2026-09-23

The orchestrator ran the build plan checklist from the approved live home load onward while the
owner was asleep. Every ruling it made is in `engine/docs/build-plan.md` 17.13, numbered 18 to 29,
each marked as ruled by the orchestrator on the owner's delegation.

## How far it got

Step 12a closed, and with it the Phase 3 baseline. Step 13 landed whole. Steps 15 and 16 are done
and verified live. Step 14 landed its read only. Step 20 and Step 22 are done, and Steps 21 and 23
landed everything except the live runs that need a message sent by hand. Steps 17 and 18 were not
started. Neither stop condition holds, so no version was cut and `pyproject.toml` still says
`0.0.0`. `1.0.0` is not reachable until the blocked items below clear.

The suite is at 562 passed, the snapshot at 362 lines with every one of the 254 baseline lines
present, and all 25 mutation harnesses exit 0 with no gate missed.

## Steps, in order

| Step | Commit | Live requests | Result |
|---|---|---|---|
| Approved live home load with the cookie sync tail | 413793a | 10, 2 to facebook.com | All 200, fr stored at 126 characters. Closes Step 12a, and this commit is the Phase 3 baseline |
| Step 13.0 scouting, no writes | none, knowledge base only | 12 browser page loads, background calls not captured | Hypothesis findings for like, unlike, comment, comment delete, follow, unfollow, direct send, post read, comment page. Direct send is an HTTP GraphQL mutation |
| Provenance gate extended, additive surface check | dcde97a | 0 | Failure codes and non-instagram hosts checked, each with controls. Checkpoint markers exempted by an enumerated list, ruling 20 |
| Step 13 write path, OutcomeUnknown, write pacing | ed13dfb, 6b9be90 | 0 | 19 mutations red then green |
| Step 14 notes tray read | 8f59d33 | 52, one browser inbox load, no write | notes() and dumpsta note list. Set and delete blocked, ruling 22 |
| Own profile read for media_count | none | 1 | media_count 8, account private |
| Step 15 like, unlike, single-post read | d7b3242 | 16 | Likes converge. The post ends liked, as the owner left it, ruling 24 |
| Step 16 comments | 7518750 | 15 | Three comments created and deleted, the post ends with 0 comments |
| Step 20 inbox listing, Step 21 reads 1 and 2 | 0095585 | 2 | Identical on 15 of 15 rows, 60.6 s apart |
| Step 22 events surface and buffer | f9d5327, 6e7bd85, 22be23f | 0 | 22 mutations red then green. The behavior harness anchors I broke in ed13dfb were repaired |
| Step 23 poller | 0005878 | 7, plus one probable from a test, below | Reduced live run on both surfaces. Two unarranged messages were printed as ids only |
| Harness exits and network guard | 16e66cf | 0 | Three CLI gates had not fired since 4a457df. They are fixed, and every harness now refuses a missed anchor |

## Live traffic, counted honestly

The engine and probes sent 52 requests, counted exactly. On top of that:

- One probable bootstrap GET to www.instagram.com with a synthetic session, sent by a Step 22 gate
  during a Step 23 suite run. That gate is retired, and the network guard now makes a repeat
  impossible.
- The browser sent 12 page loads in Step 13.0 whose background calls were not captured, an
  estimated 240 to 460 requests, plus 52 measured in Step 14.
- Since c0fc47c, two page load gates may have sent cookieless requests to www.facebook.com
  during suite runs. The count is unknown and they carried no account material. Fixed in 16e66cf.

Counting the browser estimate, the night landed somewhere between about 360 and 580 against the
400 budget. Ruling 23 stopped browser discovery after Step 14 and capped the engine at 60 more.
No CheckpointRequired and no throttle was seen at any point.

## Rulings made on the owner's behalf

In 17.13, rulings 18 to 29. These are the ones most worth reading:

- **Ruling 18.** Step 12a closed without the human timing samples from other days.
- **Ruling 22.** No note write while the owner's hand-made song note is up.
- **Ruling 23.** How the budget is counted, and no more browser discovery tonight.
- **Ruling 24.** A write cycle restores the starting state.
- **Ruling 25.** Input names were settled with a delete of a comment that cannot exist.
- **Ruling 26.** Step 22 went ahead before Step 21 closed.

The comment text "nice light" and the note text "brb" were chosen by the orchestrator. They are
stored in `.env` as `IG_COMMENT_TEXT` and `IG_NOTE_TEXT`.

## Blocked, and why

- **Step 14, set and delete.** The owner's song note, made by hand at about 00:55 UTC, would be
  replaced by a set and removed by the delete, and the engine cannot recreate it. Both mutation
  doc_ids were read unchanged and the close friends audience is 1, but each finding has one
  live pass and needs a second before its doc_id may enter the package.
- **Steps 17 and 18.** No follow target and no direct message target were named.
- **Step 21, reads 3 to 5, and the arranged Step 23 run on each surface.** Both need a message
  sent by hand while the probe waits, per ruling 10.
- **The Phase 3 and Phase 4 stop conditions, and the 1.0.0 cut.** They follow from the items
  above.
- **The human timing samples.** They need other days.

## Open questions for the owner

- `engine/dumpstagram/_private/web/bootstrap.py:120` carries a comment line
  `# G9N7E-K9NZE-GTWKC-XQ9TR`, added in ec7b338. It looks like a key, and it was left alone.
- The Step 23 `since` bounds, three pages per thread and three threads searched, are guesses.
- Twice during the night, a harness mutation came back into a file after it had been restored,
  most likely because the `~/Documents` sync agent restored an older copy. Every commit tonight
  was made on a green suite. Still, it is worth running `git status` after any harness run.

## Exact next action

When you are awake, you can send yourself a message on another device while this runs, which
closes Step 21 and gives the Step 23 acceptance its arranged message:

```
uv run python probes/inbox_change_feed.py --stage full
```

Then name `FOLLOW_TARGET` and `DM_TARGET` for Steps 17 and 18. You can also either say the song
note may go or wait for it to expire, and Step 14's set and delete follow with about 7 requests.

## Continuation, same day, after the owner named the targets

The owner named the follow and direct message target and allowed the note to change, recorded
as ruling 30. The loop then ran to the end of the checklist. Rulings 31 to 36 cover it.

| Step | Commit | Live requests | Result |
|---|---|---|---|
| Step 14 note set and delete | 1423105 | 11 | Close friends, value 1, accepted. No note left up |
| Step 17 follow and unfollow | a773a1a | 16 | Three follows, each undone. The target ends unfollowed |
| Step 18 direct send and unsend | 4fe139d | 9 engine, 51 browser | Three messages, each unsent. The browser's Message click created the thread |
| Phase 3 stop condition from dumpsta, 0.3.0 | a404e15, tag v0.3.0 | 26 | Five writes, each confirmed and reversed |
| Step 21 full, Step 23 arranged, Phase 4, 0.4.0 | 7880d95, tag v0.4.0 | 37 | Events printed 44.49 s sync and 44.13 s async after the send. Three messages, each unsent |
| Freeze, Phase 5 entry gates, 1.0.0 | 20d4ab5, tag v1.0.0 | 1 | Additive freeze holds. Prepared, not published |

Still open: 17.8 item 3 waits for the app roadmap. Seven gates need git and fail from an
unpacked sdist. The write budget and the write stop reset with each `dumpsta` process. Human
timing rests on one sample, and Intel is unverified.
