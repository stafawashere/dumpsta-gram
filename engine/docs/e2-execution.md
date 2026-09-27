# E2 execution list

The route through E2 of [web-parity-plan.md](web-parity-plan.md), "read everything a signed-in
user can see", `1.2.0`. Prepared offline on 2026-09-23 so the live nights go straight to replays.
Rulings W41 to W44 in the plan govern it.

No request carrying the account's session was sent to prepare it. The inputs were the census of
E1 item 2, the compiled artifacts the census scout read in the browser, 78 cookieless fetches of
static bundles (`probes/e2_bundle_artifacts.py`, reverse-engineer run `run-2026-09-23-231418`),
and the request bodies already kept in the skill's recorded captures. Every contract below is a
HYPOTHESIS until its probe runs. The `doc_id` values, the variable templates and the observed
shapes live in the local knowledge base as hypothesis findings, never here, per W41.

## How to read a batch

- **Operations.** The census name, or `REST` with the path for a route that is not a Relay
  operation. `verified` marks an operation a finding already backs, `lazy` one that only a
  lazily loaded chunk carries, and `capture first` one whose variables were never observed and
  that no probe guesses (W44).
- **Variables.** Where the engine gets each argument at call time.
- **Method.** The proposed public name on the W1 and W19 namespaces. Names follow W19: a read
  keyed on a lookup value is `by_<key>`, and every paged read gets an `iter_` companion under
  W23 and W24.
- **Pagination.** What ends a walk. Every one ends on the upstream's own signal only.
- **Side effect.** What a browser does besides reading. Anything another person can see is
  flagged, and W42 and W43 say what runs.
- **Live cost.** Requests to verify: every hypothesis read replayed twice, the standing rule,
  plus the reads that produce the arguments and one bootstrap per probe. Conditional requests
  are a second GraphQL path on a null root and pages that exist only on a large account.

## Order

Cheapest and most valuable first. Batches 1 to 9 have a probe ready; batch 10 is the one browser
capture night that unblocks the rest.

| Order | Batch | Probe | Requests | Conditional |
|---|---|---|---|---|
| 1 | Direct read side, done 2026-09-24 | `probes/e2_direct_read.py` | 9, spent 9 | 3, spent 0 |
| 2 | Profile tabs over GraphQL, done 2026-09-27 | `probes/e2_profile_tabs.py` | 12, spent 8 on each of 3 runs | 4, spent 0 |
| 3 | Relationship lists, done 2026-09-27 | `probes/e2_follow_lists.py` | 6, spent 7 on each of 2 runs | 1, spent 1 on each |
| 4 | Post depth, done 2026-09-27 | `probes/e2_post_depth.py` | 13, spent 13, and 4 of `e2_next_pages.py` | 7, spent 0 |
| 5 | Stories, read only, done 2026-09-27 | `probes/e2_stories.py` | 8, spent 8 | 4, spent 0 |
| 6 | Own account, done 2026-09-27 | `probes/e2_own_account.py` | 7, spent 7 | 3, spent 0 |
| 7 | Discovery feeds, done 2026-09-27 | `probes/e2_discovery_feeds.py` | 9, spent 11 | 5, spent 2 |
| 8 | Search, done 2026-09-27 | `probes/e2_search.py` | 7, spent 7 | 3, spent 0 |
| 9 | Page models, the inbox load done 2026-09-27 | `probes/e2_page_models.py` | 10, spent 10 | 4, spent 0 |
| 10 | Capture night | browser, no probe | about 15 page loads | |
| 11 | Replays the capture unblocks, 11a profile, 11b reels and search, 11c saved and close friends, 11d the blocked list and the post page, 11e the explore next page, the audio page and the mutual followers, done 2026-09-27 | `probes/e2_capture_replays.py`, `probes/e2_blocked_list_replay.py`, `probes/e2_last_reads_replay.py` | 27, profile stage spent 10; 11e 13, spent 18 | 7; 11e 4 |
| 12 | Story seen, done 2026-09-27 on the owner's own highlight | `probes/story_seen_own_highlight.py` | 4, spent 4 | |

Batches 1 to 9 spend 80 requests, 114 at most, 9 of them bootstraps, at the probe spacing of
2850 ms, four to six minutes of wire time for all nine. With batches 11 and 12 the E2
verification estimate is about 125 to 160 engine requests and about 15 browser page loads. The
plan's standing rule sets the phase budget when E2 opens; this is the input to it, not the
budget.

Each probe stops the whole run at the first checkpoint, throttle, authentication failure or
HTML shell, and never retries one. After any probe stops that way, no further batch runs that
night.

## Batch 1: direct read side

| Operation | Kind | Status |
|---|---|---|
| `PolarisDirectInboxQuery` | first page | verified, public as `direct.inbox` |
| `IGDThreadListOffMsysPaginationQuery` | next pages | verified 2026-09-24, public as `direct.inbox` with a cursor |
| `IGDMessageRequestLeftRailStandaloneQuery` | pending and spam folders | verified 2026-09-24, public as `direct.message_requests` |
| `useIGDSystemFolderUnreadThreadCountQuery` | unread counts per folder | verified, public as `direct.unread_counts` |
| `IGDBadgeCountOffMsysQuery` | the direct badge | verified, a shipped companion, no capability (W47) |
| `IGDInboxInfoOffMsysQuery` | a thread's details panel | verified 2026-09-24, no capability (W47) |

**Status: done on 2026-09-24, rulings W45 to W48.** The probe ran with 9 requests and no
conditional one, every hypothesis read replayed twice with a 200 and no null root, and the three
findings were promoted to verified. The reads shipped as `client.direct.inbox(*, after=None) ->
Page[DirectThread]`, `client.direct.iter_inbox(*, limit, after=None)`,
`client.direct.message_requests() -> MessageRequests` and `client.direct.unread_counts() ->
UnreadCounts`, on both clients with no flat twin, and as `dumpsta inbox`, `dumpsta
message-requests` and `dumpsta unread`. The live acceptance through `dumpsta` spent 5 requests
more, 14 in all, and no browser page load. What the run found that the plan did not know:

- The next page's `id` is the mailbox id, which every mailbox root carries and which equals the
  viewer's messaging id. Only the first page's answer carries it beside the cursor, so the cursor
  `direct.inbox` hands out joins the two (W46).
- Neither unread query answers with a number. Each answers a folder's first page of rows with
  their read receipts, and the browser counts. The engine counts a row unread when it is marked
  unread or the viewer's receipt is older than its last activity or absent, an INFERENCE (W47).
- Both request folders were empty, so a request row has not been seen. It is mapped as an inbox
  row, loudly, and its non-empty verification moves to E6 under W44.
- The details panel answers admin ids, capability bitmasks and the members, with no activity and
  no receipts, so it adds nothing a `DirectThread` lacks and backs no capability (W47).

Variables. The iris device id is a fresh uuid per client, as the poller already sends. The next
page takes the mailbox `id` and the `end_cursor` from the first page, `folder` INBOX, and
`count` 15, which is the first page's compiled size and not an observed value. The requests
query takes the device id and a "30 days ago" timestamp in milliseconds, whose type is not
observed. The details panel takes a `thread_fbid`, which `direct.threads` rows carry.

Methods, as planned. `client.direct.threads(*, after=None) -> Page[Thread]` and
`iter_threads(*, limit)`, the private inbox listing made public; `client.direct.requests() ->
Page[Thread]` for pending, with spam as a folder argument if the answer separates them;
`client.direct.unread_counts()`; `client.direct.thread_info(thread_fbid)`. The `Thread` model is
new and public. W45 renamed them as shipped: `inbox`, `iter_inbox`, `message_requests`,
`unread_counts` and the `DirectThread` model, and W47 dropped `thread_info`.

Pagination. `threads_by_folder.page_info.has_next_page`, cursor `end_cursor`.

Side effect. None for a listing. Opening a request thread marks it seen to the sender
(INFERENCE, as an open thread does), which is why no method here opens one (W43).

Also in the bundle, never observed on the wire: `REST /api/v1/direct_v2/pending_inbox/`, an
alternate route to the requests, kept as the fallback if the GraphQL one is refused.

Not a capability, with the reason: the three partnership inbox queries and the two
professional pagination queries serve professional accounts only, and the owner's is not one
(ASSUMPTION, not checked against the account).

## Batch 2: profile tabs over GraphQL

| Operation | Kind | Status |
|---|---|---|
| `PolarisProfilePostsQuery` | the grid's first page | verified, public as `profiles.posts` |
| `PolarisProfilePostsTabContentQuery_connection` | the grid's next pages | verified 2026-09-27, public as `profiles.posts` with a cursor |
| `PolarisProfileStoryHighlightsTrayContentQuery` | the tray's first page | verified, public as `profiles.highlights` |
| `ProfileStoryHighlightsTrayContentQuery_connection` | the tray's next pages | hypothesis, never answered, no tray had a second page (W54) |
| `PolarisProfileSuggestedUsersWithPreloadableQuery` | suggested beside a profile, preloaded | verified, a profile page companion |
| `PolarisProfileSuggestedUsersWithLazyQueryQuery` | the same, on demand | verified 2026-09-27, public as `profiles.suggested` |
| `PolarisSuggestedUserListQuery` | the suggested accounts list | verified 2026-09-27, public as `profiles.suggested_for_you` |
| `PolarisSuggestedUserListRefetchQuery` | its refetch | alternate of the list, same root, no capability |

**Status: done on 2026-09-27, rulings W52 to W56.** The probe ran three times at 8 requests
each, 24, with no conditional request: the owner's grid fits one page and his tray holds one
highlight, so neither next page was sent, and the first two runs stopped at the grid's field
errors before the probe support learned to keep a partial answer. The grid's next page was then
replayed twice by `probes/e2_next_pages.py` on a public account the owner's timeline shows, 10
requests for that whole probe, shared with batch 4, and the finding was promoted to verified with
the two suggested lists. The reads shipped as `client.profiles.posts(username, *, after=None) ->
Page[Post]`, `client.profiles.iter_posts(username, *, limit, after=None)`,
`client.profiles.highlights(user_id) -> HighlightTray`, `client.profiles.suggested(user_id) ->
tuple[ProfileSummary, ...]` and `client.profiles.suggested_for_you() -> tuple[SuggestedAccount,
...]`, on both clients with no flat twin, with the new public models `Highlight`,
`HighlightTray`, `ProfileSummary`, `ListFriendshipStatus` and `SuggestedAccount`, and as
`dumpsta posts`, `highlights`, `suggested` and `suggested-for-you`. The live acceptance through
`dumpsta`, `probes/e2_profile_tabs_cli_acceptance.py`, ran on 2026-09-27 with every step exit 0 and
7 requests, 2 more than planned because the first step drew the stale token envelope of W57 and
bootstrapped once: the owner's 8 posts in one page with W52's field errors live, 1 highlight,
18 suggested beside the profile and 5 suggested for you. Log `logs/e2-profile-tabs-cli-2026-09-27-022848.json`. What the run found that the plan did not know:

- The grid answered beside field errors, one per post whose location picture failed, and the
  classifier refused the page. W52 makes such an answer a partial answer, for every batch.
- A grid node is the home timeline's post node with `is_seen` null, so the grid returns `Post`
  and reads that null as False (W53).
- A list row's relationship carries eight flags, not the profile's ten, so rows get
  `ListFriendshipStatus` rather than `FriendshipStatus`, and the suggested accounts list carries
  no `is_private` at all (W55).
- The suggested accounts list carries the line the website shows under each account, so
  `suggested_for_you` returns `SuggestedAccount` rather than bare rows (W55).

Variables. The grid is keyed on `username`, which `profiles.by_id` returns, with `data` copied
from the verified first page and `after` from its cursor; `first` and `include_multi_captions`
on the next page are not observed. The tray is keyed on the numeric `user_id`. The suggested
lists take `target_id` and module `profile`, or a `data` object with module `discover_people`,
both observed in a recorded browse.

Methods, as planned. `client.profiles.posts(user, *, after=None) -> Page[Post]` and `iter_posts`, where
`user` is a `Profile` or a username; `client.profiles.highlights(user_id) ->
Page[Highlight]` and `iter_highlights`; `client.profiles.suggested(user_id)` and
`client.profiles.suggested_for_you()`, each returning `tuple[ProfileSummary, ...]`.

Pagination. `page_info.has_next_page` on both connections.

Side effect. None.

W53 took a username only, W54 shipped the tray as a first page with no iterator, and W55 returned
`SuggestedAccount` from the list.

The profile's reels tab and tagged tab, which no page load compiled, were captured on the capture
night (batch 10) and shipped in batch 11a.

## Batch 3: relationship lists

| Operation | Kind | Status |
|---|---|---|
| `REST GET /api/v1/friendships/{user_id}/followers/` | followers, a page | verified 2026-09-27, public as `profiles.followers`, next pages on `max_id` |
| `REST POST /api/v1/friendships/show_many/` | the viewer's relationship to many ids | verified 2026-09-27, sent after each followers page, folded into the rows (W59) |
| `REST GET /api/v1/friendships/{user_id}/following/` | following, a page | verified 2026-09-27, public as `profiles.following` in batch 11a (W99) |
| mutual followers | | not captured, both accounts opened showed 0, still waiting |

**Status: done on 2026-09-27 for the followers, rulings W58 to W60.** The probe ran twice at 7
requests, 14, the conditional next page sent on both runs, and both findings were promoted to
verified, the followers page at six replays and the statuses at four. The read shipped as
`client.profiles.followers(user_id, *, after=None) -> Page[ProfileSummary]` and
`client.profiles.iter_followers(user_id, *, limit, after=None)`, on both clients with no flat
twin, with the new setting `Behavior.follow_list_statuses` and no new model, and as `dumpsta
followers`. The live acceptance through `dumpsta`, `probes/e2_follow_lists_cli_acceptance.py`,
ran on 2026-09-27 with both steps exit 0 and 5 requests: 19 followers over two pages with no overlap, statuses on all 19, and the site root referer of W58 answered, log `logs/e2-follow-lists-cli-2026-09-27-025019.json`. What the run found that the plan did not know:

- `max_id` set to `next_max_id` reaches the next page: 7 new accounts, zero overlap, on both runs.
- A short page is not the end. The second page held 7 accounts where 12 were asked for and still
  said `has_more` true with a cursor, and the owner has 82 followers. No last page has been read,
  so `has_more` false ending the walk is an INFERENCE (W58).
- The browser sends the statuses for exactly the ids of the page it just loaded, in its order,
  with the same web session id. Later pages were not browsed, so one statuses request per page is
  an INFERENCE, and it is the default with `Behavior.follow_list_statuses` as the departure (W59).
- A status carries the six flags `ListFriendshipStatus` requires and neither `followed_by` nor
  `blocking`, so batch 2's model fits as it was (W59).
- Neither REST read has a `doc_id`, so the doctor's canary does not replay them (W60).

Following shipped in batch 11a. Mutual followers are not implemented: the capture night opened
two followed accounts whose mutual followers line read 0, so no request was observed.

Variables. The followers page takes the account's numeric id in the path and the query
`count` 12 and `search_surface` follow_list_page, observed on the owner's own followers. The
next page parameter is not observed; the probe tries `max_id` from `next_max_id` once and records
the answer as evidence for or against it. `show_many` takes the listed ids as `user_ids`.

Methods, as planned. `client.profiles.followers(user_id, *, after=None) -> Page[ProfileSummary]` and
`iter_followers`, `client.profiles.following` and `iter_following`, and
`client.profiles.mutual_followers(user_id)`. The relationship statuses fold into
`ProfileSummary.friendship_status`, as the browser's list does, rather than a method. The first
two shipped as planned; the rest wait on the capture night.

Pagination. `next_max_id` and `has_more`, both in the answer. W58 ends the walk on `has_more`
and carries `next_max_id` as the cursor, sent back as `max_id`.

Side effect. None. Reading any account's list is visible to nobody (W43), but E2 acceptance runs
on the owner's own lists, and on a public account the owner follows for mutual followers.

## Batch 4: post depth

| Operation | Kind | Status |
|---|---|---|
| `PolarisPostChildCommentsQuery` | replies, first page | verified 2026-09-27, public as `media.replies` |
| `PolarisPostCommentsChildrenPaginationtQuery` | replies, next pages | verified 2026-09-27, public as `media.replies` with a cursor |
| `PolarisPostLikedByListDialogQuery` | likers | verified 2026-09-27, public as `media.likers` |
| `PolarisPostActionLoadPostQueryMediaIdQuery` | a post by media pk | verified 2026-09-27, public as `media.by_id` |
| `PolarisPostModalContextQuery` | a post modal's context | verified 2026-09-27, no capability and not sent (W66) |
| `PolarisDesktopPostPageRelatedMediaGridQuery` | more posts from the author | verified 2026-09-27, public as `media.more_from_author` |

**Status: done on 2026-09-27, rulings W61 to W67.** `probes/e2_post_depth.py` ran once with 13
requests and no conditional one, and the replies' next page was replayed twice by
`probes/e2_next_pages.py` on a comment with 52 replies, 4 of that probe's 10 requests, shared with
batch 2; all six findings were promoted to verified. The reads shipped as
`client.media.replies(post_pk, comment_id, *, after=None) -> Page[Comment]`,
`client.media.iter_replies(post_pk, comment_id, *, limit, after=None)`,
`client.media.likers(post_pk) -> tuple[ProfileSummary, ...]`, `client.media.by_id(post_pk) ->
PostDetail` and `client.media.more_from_author(author_id) -> tuple[PostThumbnail, ...]`, on both
clients with no flat twin, with the new public models `Location`, `UserTag` and `PostThumbnail`,
the new fields `location`, `user_tags` and `collaborators` on `Post` and `PostDetail` and
`user_tags` on `CarouselChild`, and as `dumpsta replies`, `likers`, `more-from-author` and `post
--by-id`. The live acceptance through `dumpsta`, `probes/e2_post_depth_cli_acceptance.py`, ran on 2026-09-27 with every step exit 0 and 11 requests, after a first run stopped at `post --by-id` on a reel and led to W63's original sound gap: 94 likers, 1 reply on one page, the reel by pk with 2 user tags, and 6 posts from its author, log `logs/e2-post-depth-cli-2026-09-27-033207.json`. What the
run found that the plan did not know:

- `first` does not bound a page of replies: 3 asked, 9 and then 11 answered. A reply is the
  comment page's node with `child_comment_count` null, so `reply_count` is `None` on a reply (W61).
- The likers are a sample: 98 accounts for a post counting 193647 likes, with nothing to page on
  (W62).
- The post read by media pk carries less than the shortcode read: slides without a kind, no image
  description, no collaborators, tags without positions. `by_id` leaves those empty (W63).
- The strip under a post takes no post, only the author, and its items are too thin for `Post`,
  so it returns `PostThumbnail` (W64).
- A tag on a slide can come without `pk`, and a location's `pk` is a string on the timeline and a
  number on a grid (W65).
- The post modal's context repeats what the post reads carry, so it backs nothing (W66).

Variables. Every one takes the media `pk`, which `feeds.home`, `profiles.posts` and
`media.by_code` return, except the related grid, which takes only the author's id. Replies also
take the parent comment's `pk` from `media.comments`, plus `is_chronological` true and `first` 3
on the first page and 10 on later ones, the probe's values and not a browser's. The related grid
takes `count` 6, the probe's value.

Methods, as planned. `client.media.replies(post_pk, comment_id, *, after=None) -> Page[Comment]` and
`iter_replies`; `client.media.likers(post_pk) -> tuple[ProfileSummary, ...]`, since the
artifact selects `likers_connection.nodes` with no page info; `client.media.by_id(post_pk) ->
PostDetail`; `client.media.more_from_author(post_pk, author_id) -> tuple[Post, ...]`. User tags,
location and collaborators are new fields on `Post` and `PostDetail`, not methods: the item
`by_id` answers selects `usertags`, `location` and the coauthor fields, and the probe records
their keys. Carousel children came with the E1 model. All shipped as planned except
`more_from_author`, which takes the author's id only and returns `PostThumbnail` (W64).

Pagination. Replies on `page_info.has_next_page`. Likers and the related grid are single reads.

Side effect. None.

Also in the bundle, never observed on the wire: `REST /api/v1/media/{media_id}/likers/`, the
alternate if the GraphQL likers query is refused.

Not a capability, with the reason: the three comment translation queries are machine
translation offered on demand, not content, and wait for E5's parity closure; the sharer queries
answer only for a link carrying a share id; the caption AI summary is generated text, not the
post.

## Batch 5: stories

| Operation | Kind | Status |
|---|---|---|
| `PolarisStoriesV3TrayContainerQuery` | the tray | verified, a shipped companion, public as `stories.tray` |
| `PolarisStoriesV3ReelPageStandaloneQuery` | one account's reel, or one highlight | verified 2026-09-27, public as `stories.reel` and `stories.highlight` |
| `PolarisStoriesV3ReelPageGalleryQuery` | the gallery around a reel | verified 2026-09-27, no capability and not sent (W71) |
| `PolarisStoriesV3ReelPageGalleryPaginationQuery` | the gallery's next reels | hypothesis, never answered |
| `PolarisStoriesV3SeenMutation` | mark one item seen | verified 2026-09-27, a write, public as `stories.mark_seen` and sent after `reel` and `highlight` by default (W93, W94) |

**Status: done on 2026-09-27 for the reads, rulings W68 to W72.** `probes/e2_stories.py` ran once
with 8 requests and no conditional one, in run `run-2026-09-27-014102`: the tray with 33 reels,
the owner's one highlight twice with 18 items, the owner's own reel once with no reel, since he
had no live story, and the gallery over his highlights twice. The reads shipped as
`client.stories.tray() -> tuple[TrayReel, ...]`, `client.stories.reel(user_id) -> StoryReel |
None` and `client.stories.highlight(highlight_id) -> StoryReel`, on both clients with no flat
twin, with the new public models `TrayReel`, `StoryReel`, `StoryItem`, `StoryOwner`,
`StoryVideo`, `StoryMention` and `StoryMusic`, and as `dumpsta stories-tray`, `story` and
`highlight`. W68 amends W42: the reads ship before the seen mutation is verified and send no
seen marking, a named departure from W6 until batch 12; `mark_seen` and
`Behavior.mark_stories_seen` arrive with that run, which closed the departure on 2026-09-27
(W93, W94). The CLI acceptance,
`probes/e2_stories_cli_acceptance.py`, ran on 2026-09-27 with every step exit 0 and 4 requests, each a read query and none a seen mutation: 33 tray reels, no live reel of the owner's, 1 highlight and its 18 items, log `logs/e2-stories-cli-2026-09-27-035531.json`. What the run found that the
plan did not know:

- The tray rows carry no items, only the owner, times, a seen time and a rank, so the tray is
  its own model (W69).
- A story's video renditions carry `url` and `type` and no dimensions, so they are `StoryVideo`
  rather than `VideoRendition` (W70).
- No live story item has been read. A highlight's items are story items, and a live reel's are
  ASSUMED to share their shape (W70).
- The gallery answered the same reel the standalone query did, one edge, with nothing to page
  on, so it backs nothing (W71).

Variables. A reel takes `reel_ids_arr` of account ids, observed; a highlight takes
`is_highlight` true and the highlight's id, INFERENCE. The gallery takes the tray's reel ids.
The seen mutation takes the reel id, the item's id, its owner, its `taken_at` and the time of
viewing, all observed as types.

Methods. `client.stories.tray() -> tuple[StoryReel, ...]`, `client.stories.reel(user_id) ->
StoryReel`, `client.stories.highlight(highlight_id) -> StoryReel`, and
`client.stories.mark_seen(item)`. This batch opens the `stories` namespace (W20).

Pagination. The gallery's `page_info.has_next_page`. A reel is one read.

Side effect. FLAGGED. A browser marks every item it shows as seen, and the seen list shows the
viewer to the story's owner. W6 makes that the default and `Behavior.mark_stories_seen` the
departure. Under W42 the probe reads only the owner's own highlights and reel and never sends
the mutation; `--third-party-reel` adds one read, never a mutation, of another account's reel,
off by default. The mutation is verified only in batch 12, an arranged run on a story the owner
posts from his phone and deletes afterwards. Viewing a story of the W30 partner is never planned.

Not a capability, with the reason: the two ads pool queries are ads (the plan excludes them);
`PolarisAPIReelSeenMutation` and `PolarisAPIForceStorySeenMutation` are alternate compiled routes
of the seen mutation, which the recorded browse never sent.

Also in the bundle: `REST /api/v1/feed/reels_media/`, an alternate reel route never observed.

## Batch 6: own account

| Operation | Kind | Status |
|---|---|---|
| `REST GET /api/v1/friendships/pending/` | incoming follow requests | verified 2026-09-27, public as `account.follow_requests` |
| `REST POST /api/v1/news/inbox/` | the activity feed | verified 2026-09-27, public as `account.activity` |
| `REST POST /api/v1/news/inbox_seen/` | mark the activity feed seen | hypothesis, observed once, never sent (W74) |
| `PolarisActivityFeedStoriesViewQuery` | the activity feed and requests over GraphQL | hypothesis, lazy, capture first |
| `usePolarisNotificationsNavItemQuery` | the notifications badge | hypothesis, capture first |
| `PolarisSavedCollectionPickerQuery` | saved collections | verified 2026-09-27, both answers empty, not shipped (W75); the saved tab's own query shipped in batch 11c (W106) |
| `PolarisSavedCollectionPickerPaginationQuery` | saved collections, next pages | hypothesis |
| `PolarisProfileSavedTabContentQuery` | the saved tab's collections | verified 2026-09-27, public as `account.collections` in batch 11c |
| `REST GET /api/v1/feed/saved/posts/` | saved posts, the "All posts" view | verified 2026-09-27, public as `account.saved` in batch 11c |
| Bloks app `close_friends_screen_v2` | the close friends list | verified 2026-09-27, public as `account.close_friends` in batch 11c |
| Bloks app `blocked_accounts_v2` and action `blocked_accounts_reloader` | the blocked list | hypothesis, captured, replay probe written, not shipped (W108) |
| archive | | capture first |

**Status: done on 2026-09-27 for the follow requests and the activity feed, rulings W73 to
W76.** `probes/e2_own_account.py` ran once with 7 requests and no conditional one, in run
`run-2026-09-27-014102`: the pending follow requests twice with 1 account each, the activity
feed twice with 0 new and 69 earlier items, 264 KB each, and the saved collections list twice,
empty. The reads shipped as `client.account.follow_requests() -> FollowRequests` and
`client.account.activity() -> ActivityFeed`, on both clients with no flat twin, opening the
`account` namespace (W20), with the new public models `FollowRequests`, `ActivityFeed`,
`ActivityItem`, `ActivityLink`, `ActivityMedia`, `ActivityCounts` and `ActivitySection`, and as
`dumpsta follow-requests` and `activity`. The CLI acceptance,
`probes/e2_own_account_cli_acceptance.py`, ran on 2026-09-27 with both steps exit 0 and one API request each, so no `news/inbox_seen` went out: 1 follow request, 69 activity items and `is_last_page` true, log `logs/e2-own-account-cli-2026-09-27-042111.json`. What the run found that
the plan did not know:

- The owner's account is private, so the follow requests were not empty: one account on both
  reads, with `next_max_id` null and `big_list` false. A row's `pk` is a number there where the
  followers list sends a string, so the row is read from `id` (W73).
- The activity feed answered `is_last_page` true and `continuation_token` 0 on both reads, so it
  is one read and carries the flag; how a next page would be asked for is not observed (W74).
- The second feed read answered a `last_checked` that falls on the first read's send, inside
  the probe's 17 s run, where the first answered one 26 minutes older, so the read itself may
  record a check (INFERENCE, W74).
- An item's `rich_text` is its `text` with each link written in as markup, on all 69, and
  `images` repeats `media`, so neither is modelled (W74).
- The saved collections list answered an empty `viewer` both times, 230 bytes, no edge, because
  the owner has no collection, so no collection row has been seen and nothing ships (W75).

The activity feed does not mark anything seen, by the orchestrator's ruling on the owner's
delegation: `news/inbox_seen` is never sent until a verified finding exists, a named departure
from ADR-0013 in the style of W68 (W74). Saved posts, the archive, the close friends and blocked
lists, the notifications badge and the GraphQL activity view wait on the capture night, and
saved collections on a non-empty observation (W75).

Variables. The two REST reads take nothing but the session and, for the POST, `fb_dtsg` and
`jazoest`, which the bootstrap gives. The collections take `first` and `after`. The GraphQL
activity view takes two request objects never observed and `mark_as_seen`; the badge takes a
`device_id` whose origin is not observed; saved posts take `collection_types` values never
observed.

Methods, as planned. `client.account.activity() -> ActivityFeed`, `client.account.follow_requests() ->
tuple[ProfileSummary, ...]`, `client.account.badges()`, `client.account.saved(*, after=None)`
and `iter_saved`, `client.account.collections()` and `iter_collections`,
`client.account.archive()`, `client.account.close_friends()`, `client.account.blocked()`. This
batch opens the `account` namespace (W20). The first two shipped, `follow_requests` returning
`FollowRequests` with the upstream's more flag rather than a bare tuple (W73); the rest wait.

Pagination. Collections on `page_info.has_next_page`; the activity feed is one read.

Side effect. FLAGGED, own account only. An inbox load follows `news/inbox` with
`REST POST /api/v1/news/inbox_seen/`, and the GraphQL view carries `mark_as_seen`. Both clear
the owner's own notifications badge, which nobody else sees. The probe sends neither, and the
page model (batch 9) decides whether `account.activity` marks seen by default, as a browser
opening the notifications page would.

Second account. FLAGGED. The owner's follow requests are empty unless his account is private
and someone asked, and his blocked list is empty unless he has blocked someone. E2 verifies the
empty answers only; the non-empty shapes wait for E6, where block and follow requests run.

## Batch 7: discovery feeds

| Operation | Kind | Status |
|---|---|---|
| `REST GET /api/v1/discover/web/explore_grid/` | the explore grid | verified 2026-09-27, public as `feeds.explore`, first page only |
| `PolarisExploreLocationsContainerQuery` | a location's header | verified 2026-09-27, public as `feeds.place` |
| `PolarisLocationPageTabContentQuery` | a location's grid | verified 2026-09-27, public as `feeds.location`, first page only |
| `PolarisLocationPageTabContentQuery_connection` | its next pages | verified as answering 2026-09-27, but it answered the cursor it was sent, so not registered or sent (W79) |
| `PolarisAPICheckNewFeedPostsExistQuery` | new posts on the home feed | verified 2026-09-27, public as `feeds.has_new_posts` |
| `PolarisClipsHomeRootQuery` | the reels feed, as the census guessed it | not sent by a `/reels/` load, not registered (W101) |
| `PolarisClipsTabRootPaginationQuery` | its next pages, as guessed | not sent, not registered |
| `PolarisClipsTabDesktopContainerQuery` | the reels feed's first page | verified 2026-09-27, public as `feeds.reels` in batch 11b |
| `PolarisClipsTabDesktopPaginationQuery` | its next pages | verified 2026-09-27, public as `feeds.reels` with a cursor in batch 11b |
| audio page | | capture first |

**Status: done on 2026-09-27 for the explore grid, a place's header and first grid page, and the
new posts check, rulings W77 to W81.** `probes/e2_discovery_feeds.py` ran once with 11 requests,
two of them the conditional next page, in run `run-2026-09-27-014102`: the explore grid twice,
four sections and 20 posts each, the header of the first place its posts named twice, that
place's ranked grid twice with 21 posts, its next page twice with 24, and the new posts check
twice, false. The reads shipped as `client.feeds.explore() -> ExploreGrid`,
`client.feeds.place(location_id) -> Place`, `client.feeds.location(location_id, *,
tab=LocationTab.RANKED) -> LocationPosts` and `client.feeds.has_new_posts() -> bool`, on both
clients with no flat twin, with the new public models `ExploreGrid`, `ExploreSection`, `Place`,
`LocationPosts` and `LocationTab`, and as `dumpsta explore`, `place`, `location` and `new-posts`.
The CLI acceptance, `probes/e2_discovery_feeds_cli_acceptance.py`, ran on 2026-09-27 with every step exit 0 and 4 requests, none a next page query: 4 explore sections and 20 posts, a place header, 21 posts on its grid and no new posts, log `logs/e2-discovery-feeds-cli-2026-09-27-045328.json`. What the run found that the plan did not know:

- The explore grid's posts are REST media nodes, which leave out eight keys a GraphQL node sends
  null; they read as null, and the posts are the timeline's `Post` (W77). No next page was sent,
  so the grid is its first page with `more_available`, and there is no `iter_explore`.
- The header is not a search, so it is `feeds.place` rather than the plan's `search.place`, and a
  new `Place` model rather than `Location` extended (W78).
- The grid's next page query, sent the first page's cursor, answered that same cursor twice, with
  20 of its 24 posts already on the first page. Paging is not shown to advance, so the grid is its
  first page with `has_more`, and there is no `iter_location` (W79).
- The grid's author carries no full name, so its posts are `PostThumbnail` (W79).
- The new posts check carries one flag, false both times (W80).

The reels feed shipped in batch 11b; audio pages wait. The doctor replays twenty-seven reads,
the place steps keyed on the first place a timeline or grid post names (W81).

Variables. The explore grid takes five observed constants; its next page parameter is not
observed. A location takes its `pk`, which a post's `location` carries, and `tab` ranked or
recent, the artifact's default being ranked. The reels feed takes a `data` object never
observed.

Methods. `client.feeds.explore(*, after=None)` and `iter_explore`; `client.feeds.location(
location_id, *, tab="ranked", after=None)` and `iter_location`, with `client.search.place(
location_id)` for the header; `client.feeds.reels(*, after=None)` and `iter_reels`;
`client.feeds.has_new_posts() -> bool`; `client.feeds.audio(audio_id)`.

Pagination. `page_info.has_next_page` on the GraphQL grids. The explore grid's REST terminator is
not observed.

Side effect. None.

Not a capability, with the reason: the desktop, channel and non-personalised reels tab queries
and the four chained reels queries under a post are alternate routes into the same reels
connection root, and batch 10 decides which one a `/reels/` load sends; the ads pool is ads;
the two scrubber spritesheet queries are thumbnails for a player's seek bar; the reel AI
summary is generated text; `PolarisFeedTimelineRootV2Query` is an alternate route of the shipped
home feed.

## Batch 8: search

| Operation | Kind | Status |
|---|---|---|
| `PolarisSearchNullStateQuery` | recent searches | verified 2026-09-27, public as `search.recent` |
| `PolarisSearchBoxNonProfiledRefetchableQuery` | non-personalised typeahead | verified 2026-09-27, public as `search.accounts`, accounts only |
| `PolarisHashtagHeaderActionButtonsQuery` | a hashtag's header | verified 2026-09-27, public as `search.hashtag` |
| `PolarisSearchBoxContainerQuery` | typeahead across accounts, hashtags, places | not sent by the signed-in box the capture night observed, not registered (W102) |
| `PolarisSearchBoxRefetchableQuery` | the personalised typeahead as the box sends it | verified 2026-09-27, public as `search.top` and the default route of `search.accounts` in batch 11b |
| `PolarisKeywordSearchExplorePageRelayQuery` | keyword results, which a hashtag page renders | verified 2026-09-27, first page, public as `search.keyword` in batch 11b; its pagination not observed |

**Status: done on 2026-09-27 for the recent searches, the non-personalised typeahead and a
hashtag's header, rulings W82 to W85.** `probes/e2_search.py` ran once with 7 requests, none
conditional, in run `run-2026-09-27-014102`: the recent searches twice, 15 entries each, the
non-personalised typeahead twice on a nine character term, 18 accounts each, and a hashtag's
header twice, 179 bytes. The reads shipped as `client.search.recent() -> tuple[RecentSearch,
...]`, `client.search.accounts(query) -> tuple[ProfileSummary, ...]` and
`client.search.hashtag(tag) -> Hashtag`, on both clients with no flat twin, opening the `search`
namespace, with the new public models `RecentSearch`, `RecentSearchKind` and `Hashtag`, and as
`dumpsta recent-searches`, `search` and `hashtag`. The CLI acceptance,
`probes/e2_search_cli_acceptance.py`, ran on 2026-09-27 with every step exit 0 and 3 requests, each its own query: 15 recent searches (4 accounts, 11 keywords), 18 accounts for the query and the tag's id, log `logs/e2-search-cli-2026-09-27-051346.json`. What the run found that
the plan did not know:

- A recent search is a union of four slots, of which only accounts (4) and keywords (11) were
  filled. A hashtag or a place entry is carried by its kind with no payload, and a broken union
  raises (W82).
- The non-personalised typeahead answers accounts only, no hashtags or places, so it is
  `search.accounts` rather than `search.top`, which waits for the personalised typeahead. A
  signed-in browser is believed to send the personalised one, so sending this is a named
  departure (W83).
- The hashtag header carries only the tag's id, so `Hashtag` is the id and the tag asked for.
  A tag with a `#` is refused rather than stripped (W84).

The personalised typeahead and the keyword grid, which is also the hashtag page's grid, shipped
in batch 11b. The doctor replays thirty reads, the typeahead keyed on the viewer's own
username and the header on the tag its finding was verified with (W85).

Variables. Recent searches take nothing. The non-personalised typeahead takes the query text.
The hashtag header takes the tag. The personalised typeahead's `data` object and the keyword
grid's two session ids were never observed.

Methods. `client.search.top(query) -> SearchResults` with accounts, hashtags and places;
`client.search.recent()`; `client.search.hashtag(tag)`; `client.search.keyword(query, *,
after=None)` and `iter_keyword`, which is also the hashtag grid. This batch opens the `search`
namespace (W20).

Pagination. `page_info.has_next_page` on the keyword grid.

Side effect. None to another person. INFERENCE: a typed query does not enter the recent
searches until a result is clicked, and nothing is clicked.

Also in the bundle: `REST /api/v1/fbsearch/search_engine_result_page/`, never observed.

## Batch 9: page models

The inbox load and the post page document, which close the notes, post and comment parity
departures of `1.0.0`.

Inbox load. Its burst is already recorded in the skill's captures, so the model is designed
from them without a load. Companions: the verified header, account switcher, automatic previews,
quick promotion, feature limits, presence setup, unread count and chat tabs jewel, plus
`useIGDShouldShowAdResponsesTabQuery` and `IGDThreadlineContainerQuerySuggestedQuery`, the two
the probe replays. The load also sends `friendships/pending`, `news/inbox` and
`news/inbox_seen` (batch 6). `IGDChatTabsContentOffMsysQuery` is the floating chat tabs every
non-inbox page sends and joins the home and profile companions.

Post page. `PolarisPostCommentsContainerQuery` and `PolarisLikedByTextDaisyReduxQuery`, which
the probe replays, and the document itself, which no capture holds (batch 10).

Not a capability, with the reason: `PolarisViewerSettingsQuery` answers only the reduce motion
flag; the Threads and profile nav badges count the Threads app; the scroll break interstitial,
the creator marketplace badge, the messaging eligibility, the profile view insights and the
follow confirmation dialog are chrome for professional accounts or for a regional notice; the
threadline chat query reads reel shares inside a thread and belongs with E4's message kinds.

**Status: done on 2026-09-27 for the inbox load, rulings W86 to W90, and for the post page in
batch 11d, rulings W111 to W113.** `probes/e2_page_models.py` ran once with 10 requests in run `run-2026-09-27-014102`,
replaying the post page's two companions and the two inbox queries twice each, log
`logs/e2-page-models-2026-09-27-013957.json`. The post page ships nothing, because its document has
never been captured, and its two verified companions are not registered until it does (W86). The
inbox load became the parity route of `client.direct.notes()`, `direct.inbox()` with no cursor
and `direct.unread_counts()`, chosen by the new `Behavior.inbox_route`, `InboxRoute.PAGE` by
default and `InboxRoute.QUERIES` as the departure (W87). It was designed from the two full inbox
cold loads of 2026-09-23 with no new load. What the recordings said that this list did not:

- The load sends ten queries together, the tray, the listing and both unread folders among them,
  so the three reads share one load, and the inbox document preloads none of them (W87).
- The header query is sent only on a thread page, and the chat tabs jewel only on pages that are
  not direct, so neither goes out; `useIGDShouldShowAdResponsesTabQuery` and
  `IGDThreadlineContainerQuerySuggestedQuery`, verified today, were in none of five captured
  inbox loads and are not registered (W88).
- The load prefetches the thread detail of every row of its first page, pinned threads first in
  `pinned_threads_v2` order, fifteen requests, which this list did not name (W89).
- `friendships/pending` and `news/inbox` went out in one of the two loads and are sent as
  companions whose answers are not read; `news/inbox_seen` is never sent (W74, W88).
- `IGDChatTabsContentOffMsysQuery` has no finding, so it waits rather than joining the home and
  profile companions.

Under the default behavior each of the three reads costs 31 requests with a full first page. The
CLI acceptance, `probes/e2_page_models_cli_acceptance.py`, ran twice: `note
list`, `inbox --pages 2` and `unread`, 94 requests, 110 at most (W90). Its first run sent the
whole load and stopped on an `ambient_data` item in the notes tray, a defect of `notes()` on every
route, fixed by skipping an item of another kind that carries no note (W91). Its second run, after W91, passed with every step exit 0 and 94 requests, all 200: each of the three loads sent its whole block, 15 thread details and both account reads and no `news/inbox_seen`, 10 notes, 30 threads over two inbox pages, log `logs/e2-page-models-cli-2026-09-27-055040.json`. The post, like and comment
departures of `1.0.0` stay open for batch 10.

## Batch 10: the capture night

One browser night under the ruling 23 cap, reads only, each a page load or a click inside one:

| Load | Unblocks |
|---|---|
| a profile's following list, opened | following, and its next page parameter |
| another public profile, its mutual followers line opened | mutual followers |
| the owner's profile, reels tab and tagged tab | two profile tabs |
| `/reels/` | the reels feed's `data`, and which tab route it sends |
| the search box with a typed query, then its results page | the typeahead `data`, the keyword grid's session ids |
| the owner's `/saved/` and one collection | `collection_types`, a collection's contents |
| `/notifications/` | the GraphQL activity view's objects, the badge's `device_id` |
| the story archive | the archive route |
| settings, close friends and blocked accounts | two lists |
| one audio page | the audio route |
| one post page, cold | the post page document and its burst |
| explore, scrolled once | the explore grid's next page parameter |

Opening a message request thread, viewing another person's story and anything that clicks a
control someone else can see stay out of it (W43).

**Status: read-only part captured on 2026-09-27, reverse-engineer run `run-2026-09-27-131354`, 366
requests to the site counted from the capture windows, browser background calls included, under
ruling 23's 400.** Every observed operation is a hypothesis finding with its replay template in
the local knowledge base, and `probes/e2_capture_replays.py` replays them in six stages, 27
requests, not yet run. What it found:

- The post page document preloads five queries, among them the comments container and the
  related grid at count 7, so neither goes out as a request, and the liked by line was not sent.
- The profile's reels tab and tagged tab each have their query, and the following list is the
  followers route's twin with a numeric `max_id` offset and `show_many` after each page.
- `/reels/` sends the desktop clips tab container with `seen_reels` as a JSON string on later
  pages, not the reels root the census guessed. The personalised typeahead goes out as the
  refetchable query, not the container, and the keyword grid keys both session ids on one
  client made uuid.
- Saved: the saved tab query lists collections only, and "All posts" is REST
  `feed/saved/posts/`. The story archive grid is a comet GET carrying a page token whose source
  was not observed, so it is not replayed.
- The notifications panel is REST only, and the page sent `news/inbox_seen` 7 ms after the panel
  opened, clearing the owner's own badge. FACT, one observation. The GraphQL activity view was not
  sent, so its objects stay unobserved.
- Not captured: mutual followers (two followed accounts showed a count of 0), the blocked list and
  an audio page (budget), and the explore next page (the window was occluded and the grid never
  rendered). The story seen mutation and the blocked list with an entry were left out: both are
  writes, and the orchestrator's first attempt to include them was refused by the session's
  permission check, so they wait for the owner.

## Batch 11a: profile tabs and following, from the capture night

| Operation | Kind | Status |
|---|---|---|
| `PolarisProfileReelsTabContentQuery` | the reels tab's first page | verified 2026-09-27, public as `profiles.reels` |
| `PolarisProfileTaggedTabContentQuery` | the tagged tab's first page | verified 2026-09-27, public as `profiles.tagged` |
| `REST GET /api/v1/friendships/{user_id}/following/` | following, a page, `max_id` a numeric offset | verified 2026-09-27, public as `profiles.following` |
| mutual followers | | not captured, still waiting |

**Status: done on 2026-09-27, rulings W97 to W100.** The browser captured each read in
`run-2026-09-27-131354`, and `probes/e2_capture_replays.py --stage profile` replayed each twice in
`run-2026-09-27-151121`, 10 requests with the bootstrap and the owner's profile, log
`logs/e2-capture-replays-2026-09-27-151227.json`. It shipped `client.profiles.reels(user_id) ->
ProfileReels`, `client.profiles.tagged(user_id) -> TaggedPosts`,
`client.profiles.following(user_id, *, after=None) -> Page[ProfileSummary]` and
`client.profiles.iter_following(user_id, *, limit, after=None)`, on both clients with no flat
twin, with the new models `ReelThumbnail`, `ProfileReels` and `TaggedPosts`, and as `dumpsta
profile-reels`, `tagged` and `following`. The live acceptance,
`probes/e2_profile_tabs_more_cli_acceptance.py`, is written for the owner's own account, six
requests, nine at most, and ran on 2026-09-27 with every step exit 0 and 6 requests, the site root referer answering all three reads: 1 reel, 4 tagged posts, 24 accounts followed over two pages with no overlap, log `logs/e2-profile-tabs-more-cli-2026-09-27-160153.json`. What the batch found:

- The reels tab roots at the account's user node, and its item carries no username and no
  caption, so it is a new `ReelThumbnail` with `play_count` (W97).
- The tagged tab's item is the strip's item with ten keys more, so it is `PostThumbnail`, and its
  `end_cursor` is the string `None` beside `has_next_page` false (W98).
- Neither tab had a next page on the owner's account, so both are first pages with `has_more`.
- The following list is the followers list's twin without `search_surface`, its cursor a numeric
  offset, and it is ranked: two first pages seconds apart shared 11 of 12 accounts in a different
  order. `Behavior.follow_list_statuses` governs both lists (W99).
- The doctor replays both tabs on the viewer's own id, thirty-two reads (W100).

## Batch 11b: the reels feed, the personalised typeahead and the keyword grid, from the capture night

| Operation | Kind | Status |
|---|---|---|
| `PolarisClipsTabDesktopContainerQuery` | the reels feed's first page | verified 2026-09-27, public as `feeds.reels` |
| `PolarisClipsTabDesktopPaginationQuery` | its next page, `seen_reels` the reels shown | verified 2026-09-27, public as `feeds.reels(after=...)` and `iter_reels` |
| `PolarisSearchBoxRefetchableQuery` | the personalised typeahead | verified 2026-09-27, public as `search.top` and the default route of `search.accounts` |
| `PolarisKeywordSearchExplorePageRelayQuery` | the keyword grid, which is also a hashtag's grid | verified 2026-09-27, public as `search.keyword`, first page only |
| `report-a-reel-video-view`, `PolarisClipsAdsPoolQuery` | a played reel's view report, the ads pool | not sent, the engine plays nothing (W101) |

**Status: done on 2026-09-27, rulings W101 to W104.** The browser captured each read in
`run-2026-09-27-131354`, and `probes/e2_capture_replays.py --stage search` and `--stage reels`
replayed each twice in `run-2026-09-27-151121`, 5 requests each with the bootstrap, logs
`logs/e2-capture-replays-2026-09-27-151138.json` and `-151307.json`. It shipped
`client.feeds.reels(*, after=None) -> Page[Post]` and `feeds.iter_reels(*, limit, after=None)`,
`client.search.top(query) -> SearchResults` and `client.search.keyword(query) ->
KeywordResults`, on both clients with no flat twin, with the new models `SearchResults`,
`SearchResult`, `SearchResultKind`, `SearchPost` and `KeywordResults`, the new setting
`Behavior.typeahead_route` with `TypeaheadRoute`, and `dumpsta reels`, `search-top` and `keyword`,
`search` and `search-top` taking `--non-personalised`. The live acceptance,
`probes/e2_discovery_search_cli_acceptance.py`, planned at seven requests and nine at most, ran on 2026-09-27, 7 requests, every step exit 0, log `logs/e2-discovery-search-cli-2026-09-27-163749.json`. What the batch found:

- A `/reels/` load sends the desktop clips tab container, not the reels root the census guessed,
  and a reel is the timeline's media node with keys left out and two in another shape, so it is a
  `Post` with what it lacks read as W101 records. An original sound carried no mute flag on any of
  the 8 read, so those reels' `audio` is `None`; the 3 songs are read.
- The next page names the reels already shown in `seen_reels`, a JSON string, so the cursor
  carries the upstream's cursor and the pks of its page's reels, and nothing else carries state.
- The feed is ranked: two next pages on one cursor shared 3 of 4 reels in a different order.
- A signed-in search box sends the refetchable typeahead, not the container. It blends accounts
  with keyword suggestions by an explicit `position`; hashtags and places were empty lists, so
  they are carried by kind alone. It became the default route of `search.accounts`, and the
  non-profiled query is the departure (W102). One query answered 5 accounts where the non-profiled
  one answered 18.
- The keyword grid keys both session ids on one uuid and sends no page size; its posts come three
  to a row among header and accounts rows that carry nothing, and they lack `product_type` and
  viewer state, so they are the new `SearchPost` (W103).
- `/explore/tags/<tag>/` lands on the keyword page for `#<tag>`, so a hashtag's posts are
  `search.keyword("#" + tag)`; only the plain text has been replayed.
- The doctor replays thirty-six reads, the keyword grid on `CANARY_KEYWORD` (W104).

## Batch 11c: saved posts, saved collections and close friends, from the capture night

| Operation | Kind | Status |
|---|---|---|
| `REST GET /api/v1/feed/saved/posts/` | the saved "All posts" view, first page | verified 2026-09-27, public as `account.saved` |
| `PolarisProfileSavedTabContentQuery` | the saved tab's collections | verified 2026-09-27, public as `account.collections` |
| Bloks app `close_friends_screen_v2` | the close friends settings screen | verified 2026-09-27, public as `account.close_friends` |
| `close_friend_count_updater` | a Bloks action the page sends after the list | never sent, effect UNRESOLVED (W107) |
| Bloks app `blocked_accounts_v2`, action `blocked_accounts_reloader` | the blocked list | verified 2026-09-27 by two replays, public as `account.blocked` in batch 11d (W108, W110) |

**Status: done on 2026-09-27 for the saved posts, the saved tab and the close friends list,
rulings W105 to W109.** The browser captured each read in `run-2026-09-27-131354` and
`probes/e2_capture_replays.py --stage saved` and `--stage close-friends` replayed each twice in
`run-2026-09-27-151121`. It shipped `client.account.saved() -> SavedPosts`,
`account.collections() -> SavedCollections` and `account.close_friends() -> tuple[ProfileSummary,
...]`, on both clients with no flat twin, with the new models `SavedPost`, `SavedPosts`,
`SavedCollection`, `SavedCollectionKind`, `SavedCollections` and `CollectionCover`, and `dumpsta
saved`, `collections` and `close-friends`. The live acceptance,
`probes/e2_own_account_more_cli_acceptance.py`, three requests, five at most, ran on 2026-09-27, 3 requests, every step exit 0, log `logs/e2-own-account-more-cli-2026-09-27-174542.json`. What the batch found:

- A saved post is the explore grid's REST media without `comment_count` on all 42 read, so it is
  the new `SavedPost` rather than `Post`, and the saved advertisement lacks the counts flag, which
  is `None` there (W105). The view is the first page with `more_available`.
- The saved tab answered two collection rows, "All posts" with 232 posts and "Audio", which
  amends W75; a named collection's type is unobserved and reads as `OTHER` (W106).
- The close friends screen is a Bloks tree carrying two lists of accounts, told apart by the
  state their rows start in: 7 close friends and 114 accounts offered to add, identical across
  four answers whose component ids all differed, so the list is read by structure (W107).
- The blocked list's "empty" capture hit the error route; the other two show a screen app fetch
  then a reloader action whose container ids come from the first answer, and a list of 53 and 52
  accounts, so the owner's list is not empty. Nothing shipped until the probe's replay (W108); the
  probe then ran twice, and the list shipped in batch 11d (W110).
- The doctor replays thirty-seven reads, the saved tab keyed on nothing (W109).

## Batch 11d: the blocked list and the post page

| Operation | Kind | Status |
|---|---|---|
| Bloks app `blocked_accounts_v2`, then action `blocked_accounts_reloader` | the blocked list, two fetches in one action | verified 2026-09-27 by two replays, public as `account.blocked` |
| `GET /p/<code>/` | the post page document, preloading the post, its first comments and its author's grid | verified 2026-09-27, the parity route of `media.by_code` and the whole of `media.page` |
| `PolarisPostCommentsPaginationQuery` | every comments page | unchanged, sent alone, the named departure for a read keyed on a pk (W111) |
| like, unlike, comment | writes | unchanged, sent alone, a named departure (W113) |

**Status: done on 2026-09-27, rulings W110 to W114.** `probes/e2_blocked_list_replay.py` ran twice
on 2026-09-27, 3 requests each, logs `logs/e2-blocked-list-replay-2026-09-27-174549.json` and
`-174606.json`, and the post page document was verified by the post stage of
`probes/e2_capture_replays.py` in `run-2026-09-27-151121` and captured cold twice in
`run-2026-09-27-131354`. It shipped `client.account.blocked() -> tuple[BlockedAccount, ...]`,
`client.media.page(code) -> PostPage`, and `Behavior.post_route` with `PostRoute.PAGE`, the
default, under which `media.by_code` and the flat `post` load the post page as a browser does,
and `PostRoute.QUERY`, the departure, on both clients, with `dumpsta blocked` and `post-page`. The
live acceptance, `probes/e2_post_page_cli_acceptance.py`, is written for the owner's own account
and the first post of its grid, seventeen requests, twenty at most, ran on 2026-09-27, 17 requests, every step exit 0, log `logs/e2-post-page-cli-2026-09-27-181927.json`. What the
batch found:

- The blocked screen's answer names the reloader with two consecutive container ids, the same way
  on four answers, and the reloader's answer replaces that list container's children with one list
  of six keys a row (W110).
- A blocked row's `secondary_text` is the account's full name only on a row blocked by hand; on
  the 41 rows with `is_auto_blocked` it is one interface line, so a row is the new
  `BlockedAccount` with that text kept as text, not `ProfileSummary` (W110).
- The post page document preloads five results; the post, the first comments and a grid of 7 that
  holds the post itself are read, as the new `PostPage` (W111).
- A pk gives the post page's address only for a public post: 206 of 585 codes read are longer than
  the pk's encoding, private accounts' posts among them. So `comments(post_pk)` stays a query, and
  `media.page(code)` is the parity route of the first comments (W111).
- The page's companions are the badge count, the stories tray, the jewel pair and one quick
  promotion call, six requests with the document (W112).
- Writes stay single, since no capture pairs a page load with a like or a comment (W113).

## Batch 11e: the explore next page, the audio page and the mutual followers

| Operation | Kind | Status |
|---|---|---|
| `GET /api/v1/discover/web/explore_grid/` with `max_id` | the explore grid's later pages | verified 2026-09-27 by two replays, public as `feeds.explore(after=...)`, `explore_posts` and `iter_explore` |
| `POST /api/v1/clips/music/` | an audio's page, first and later | verified 2026-09-27 by two replays each, public as `feeds.audio`, `audio_clips` and `iter_audio` |
| `GET /api/v1/friendships/<id>/mutual_followers/`, then `show_many` | the mutual followers, first page | verified 2026-09-27 by two replays, public as `profiles.mutual_followers` |

**Status: done on 2026-09-27, rulings W115 to W120.** Browser run `run-2026-09-27-182013`
captured the four reads, and `probes/e2_last_reads_replay.py` replayed each twice in run
`run-2026-09-27-183420`, all three stages, 18 requests, every replay 200, logs
`logs/e2-last-reads-replay-2026-09-27-183434.json`, `-183506.json` and `-183534.json`. It shipped
`client.feeds.explore(*, after=None)` with `ExploreGrid.end_cursor`, `feeds.explore_posts` and
`feeds.iter_explore`; `feeds.audio(audio_id, *, after=None) -> AudioPage`, `feeds.audio_clips` and
`feeds.iter_audio`; `profiles.mutual_followers(user_id) -> MutualFollowers`; and `Post.audio_id`,
on both clients, with `dumpsta explore --pages`, `audio` and `mutual-followers`. The live
acceptance, `probes/e2_last_reads_cli_acceptance.py`, ten requests, eleven at most, ran on 2026-09-27, 9 requests, every step exit 0, log `logs/e2-last-reads-cli-2026-09-27-192842.json`. What the batch found:

- The explore grid's cursor is the answer's root `max_id`, equal to its `session_paging_token` on
  all five answers read; the root `next_max_id` is a page counter. A REST first page's cursor
  paged, 18 posts with none repeated, on both replays (W115).
- A later explore page lays each section out as one `medias` list of tiles, `dynamic_grid`, which
  the mapper reads into the same featured and fill posts (W115).
- An audio's one-reel page said `more_available` true and its next page was empty and said false,
  in the browser and on both replays, so a walk spends that empty read (W116).
- A song's later pages send no track and a clip count of 0; the track and count are a first
  page's (W116).
- The mutual followers answer carries no `has_more`; `next_max_id` was null on all three answers,
  so the read is a first page, and the browser followed it with `show_many` (W117).
- A reels feed reel whose original sound lacks the mute flag has no `audio`, so `Post.audio_id`
  carries the audio page's id from the node itself (W118).
- The reels feed sends some reels' place with only its name and pk, which stopped the first
  acceptance run at `dumpsta reels`; such a reel's `location` is `None` and `Post.tagged_place`
  names the place on every read, a batch 11b gap closed here (W120).
- The iterators walk `Page` reads, so `explore_posts` and `audio_clips` are the pages
  `iter_explore` and `iter_audio` walk, and the two `feeds.explore` surface lines changed to gain
  `after` (W119).

## Batch 12: story seen

| Operation | Kind | Status |
|---|---|---|
| `PolarisStoriesV3SeenMutation` | mark one item seen, a write the item's owner sees | verified twice 2026-09-27, run `run-2026-09-27-135628` |

**Status: done on 2026-09-27, rulings W93 to W96, on the owner's own highlight rather than a live
story.** The owner opened his own highlight in the browser, which sent the mutation once with
the five variables the finding records, and `probes/story_seen_own_highlight.py` replayed it on
the highlight's second item, 4 requests, the same 196 byte answer, log
`logs/story-seen-own-highlight-2026-09-27-142451.json`. No other person was shown as a viewer.
A live reel's mutation was not observed: its `reelId` as the owner's account id is INFERENCE, and
the arranged run on a story posted from the owner's phone that W42 described was not needed for
the verification and has not run.

It shipped `client.stories.mark_seen(item, *, reel) -> None` on both clients, one write through
`send_write` (W93), and `Behavior.mark_stories_seen: bool = True`: under the default,
`stories.reel()` and `stories.highlight()` mark their first item seen after the read, the item a
browser shows first, and the tray marks nothing (W94). **Reading another account's story through
the engine now puts the viewer in its seen list, as the website does.** `dumpsta story` and
`highlight` mark by default and take `--no-mark-seen`, and `dumpsta story-seen REEL_ID ITEM_PK`
marks one item (W95). W68's departure is closed. The live acceptance,
`probes/e2_story_seen_cli_acceptance.py`, is written for the owner's own highlight only, five
requests, and has not run.

## Visibility and second account, collected

| Item | Flag |
|---|---|
| Story seen mutation | Visible to the story's owner. Verified on the owner's own highlight (W93); the engine's default now sends it on any story it reads (W94). |
| Another person's story, read | Read query only, behind a flag, never the W30 partner (W42). |
| Opening a message request thread | Marks it seen to the sender, INFERENCE. Never run (W43). |
| `news/inbox_seen`, activity `mark_as_seen` | The owner's own badge only. Not sent in discovery. |
| Follow requests, blocked list | Non-empty case needs another person's action, E6. |
| Mutual followers | A public account the owner follows, read only. No second account needed. |

## Where the contracts are

Local, never committed: the 39 hypothesis findings of `run-2026-09-23-231418` in
`skills/reverse-engineer/knowledge/endpoints/`, each with its replay template, the extraction
`skills/reverse-engineer/var/runs/run-2026-09-23-231418/bundle-artifacts.json`, and the patterns
that run recorded. Each probe reads its contracts from those files at run time. A finding whose
replay passes twice becomes the verified evidence an engine change cites.
