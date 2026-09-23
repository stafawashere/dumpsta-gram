# Web coverage

The denominator the web parity phases scope from, per ruling W12 of
[web-parity-plan.md](web-parity-plan.md). It summarises the operation census of E1 item 2,
taken 2026-09-23 in `run-2026-09-23-190729`. The census itself, with every operation, its user
action, its `doc_id` and the loads that parsed it, lives in
`skills/reverse-engineer/knowledge/census.md`, which is local and never committed. This file
carries counts only.

## What is counted

FACT. Every compiled Relay operation that carries a `doc_id` and is a query, a mutation or a
subscription, found by the reverse-engineer skill's `scout_operations.py` across thirteen page
loads of the owner's session, plus the five operations the engine already sends that no cold
load parses (the first thread page, the share sheet null state, the note set and delete, and
the unsend). Fragments and client store updates without a `doc_id` are not counted.

The count is a lower bound, for two reasons.

- Lazy chunks load only when a control is used, so follower lists, likers, the post and story
  composers, edit profile, block and most dialogs are not in it yet. The note and unsend
  mutations were already known to be absent from every cold load.
- REST routes under `/api/v1/` are not Relay operations. INFERENCE: the notifications list,
  the explore grid and the audio page are served that way, since each page was loaded and
  rendered and no compiled operation was parsed only there. They show zero or one operation
  below for that reason, and they are not uncovered pages.

Each operation belongs to exactly one page type, the one whose user action it serves. `shared`
is the chrome every page carries: badges, quick promotions, consent flows, cookie sync.

An operation counts as covered when it backs a public capability of `1.0.0`. The engine also
sends ten further operations as page load companions for browser parity, and those are shown
separately rather than counted as capabilities.

## Totals

| Measure | Count |
|---|---|
| Operations | 265 |
| Parsed on a page load | 260 |
| Known from findings, parsed on no load | 5 |
| Queries, mutations, subscriptions | 160, 104, 1 |
| Excluded, with a recorded reason | 69 |
| In scope | 196 |
| Backing a public capability | 20 |
| Sent by the engine at all, companions included | 30 |
| Needing a second account | 7 |

**Covered: 20 of 265 operations, 7.5 percent. Of the 196 in scope, 10.2 percent.** Counting
the companions the engine sends, 30 of 265, 11.3 percent.

No `doc_id` the engine carries differs from the one the current bundle compiles, for the 25
engine operations a load parsed.

## Per page type

| Page type | Operations | Capability | Engine sends | Excluded | Loaded as |
|---|---|---|---|---|---|
| home | 8 | 1 | 1 | 0 | its own load |
| explore | 0 | 0 | 0 | 0 | its own load, grid over REST (INFERENCE) |
| reels | 15 | 0 | 0 | 0 | its own load |
| profile | 24 | 4 | 8 | 7 | the owner's own profile |
| post | 45 | 6 | 6 | 15 | one of the owner's own posts |
| stories | 13 | 0 | 1 | 0 | the home bundle, the owner has no live story |
| inbox | 21 | 4 | 4 | 1 | its own load |
| thread | 43 | 5 | 5 | 6 | the inbox bundle, no thread opened |
| notifications | 1 | 0 | 0 | 0 | its own load, list over REST (INFERENCE) |
| search | 7 | 0 | 0 | 0 | the explore and home bundles |
| saved | 10 | 0 | 0 | 0 | the owner's own saved tab |
| settings | 37 | 0 | 0 | 17 | its own load |
| hashtag | 3 | 0 | 0 | 0 | a public hashtag page |
| location | 3 | 0 | 0 | 0 | a public location page |
| audio | 0 | 0 | 0 | 0 | a public audio page, over REST (INFERENCE) |
| shared | 35 | 0 | 5 | 23 | every load |
| **total** | **265** | **20** | **30** | **69** | |

## Per phase

| Phase | Operations |
|---|---|
| shipped in `1.0.0`, capabilities and companions | 30 |
| E2, reads | 85 |
| E3, own-account writes | 23 |
| E4, direct messaging and push | 30 |
| E5, settings and login offline | 21 |
| E6, second account | 7 |
| excluded | 69 |

The seven E6 operations are replying to another account's story, liking and unliking a story,
creating a group thread, approving a restricted account's comment, unrestricting, and logging
out (W13).

## Exclusions

| Reason | Operations |
|---|---|
| Consent or Accounts Center flow | 16 |
| Teen supervision, needs a guardian account | 15 |
| Alternate compiled route of an action already shipped | 8 |
| Ads and boost, paid | 8 |
| Logged-out surface | 5 |
| W5 reporting | 3 |
| New account onboarding | 3 |
| Client store update, INFERENCE never sent | 3 |
| Calls | 2 |
| Telemetry | 2 |
| AI bot feedback, feedback to Meta, business onboarding, leaving the school program | 4 |

## Page loads spent

13 browser page loads and 0 engine requests. Each load's own background traffic, counted by
`Network.requestWillBeSent` in the scout tab: 2620 requests in all. 229 went to Instagram's
API paths (`/api/graphql`, `/graphql/query`, `/api/v1/`), 276 to other instagram.com paths,
1997 to the CDN hosts, 13 to facebook.com, and 105 were inline `data:` or `blob:` URLs. No checkpoint, login wall or throttle was
seen.

## How to regenerate

Rerun the scouts, then `uv run --no-project python
skills/reverse-engineer/scripts/build_census.py --run <run-id>`, which refuses to write while
any operation lacks a classification row, and copy its totals here. E5's coverage report
regenerates both.
