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
| 6 | Own account | `probes/e2_own_account.py` | 7 | 3 |
| 7 | Discovery feeds | `probes/e2_discovery_feeds.py` | 9 | 5 |
| 8 | Search | `probes/e2_search.py` | 7 | 3 |
| 9 | Page models, companions | `probes/e2_page_models.py` | 10 | 4 |
| 10 | Capture night | browser, no probe | about 15 page loads | |
| 11 | Replays the capture unblocks | written after batch 10 | about 40, HYPOTHESIS | |
| 12 | Story seen, arranged | written after batch 5 | about 4 | |

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

Needs capture first (batch 10), waiting on the capture night: the profile's reels tab and tagged
tab. No page load compiled
either, and neither is in the home document's lazy chunk map.

## Batch 3: relationship lists

| Operation | Kind | Status |
|---|---|---|
| `REST GET /api/v1/friendships/{user_id}/followers/` | followers, a page | verified 2026-09-27, public as `profiles.followers`, next pages on `max_id` |
| `REST POST /api/v1/friendships/show_many/` | the viewer's relationship to many ids | verified 2026-09-27, sent after each followers page, folded into the rows (W59) |
| following | | capture first, waiting on the capture night |
| mutual followers | | capture first, waiting on the capture night |

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

Following and mutual followers are not implemented. No request for either was observed, so both
wait on the capture night (batch 10), which opens a following list and a mutual followers line.

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
| `PolarisStoriesV3SeenMutation` | mark one item seen | hypothesis, variables observed, WRITE-LIKE, never sent (W68) |

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
`Behavior.mark_stories_seen` arrive with that run. The CLI acceptance,
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
| `REST GET /api/v1/friendships/pending/` | incoming follow requests | hypothesis, observed once |
| `REST POST /api/v1/news/inbox/` | the activity feed | hypothesis, observed once |
| `PolarisActivityFeedStoriesViewQuery` | the activity feed and requests over GraphQL | hypothesis, lazy, capture first |
| `usePolarisNotificationsNavItemQuery` | the notifications badge | hypothesis, capture first |
| `PolarisSavedCollectionPickerQuery` | saved collections | hypothesis |
| `PolarisSavedCollectionPickerPaginationQuery` | saved collections, next pages | hypothesis |
| `PolarisProfileSavedTabContentQuery` and its `_connection` | saved posts | hypothesis, capture first |
| archive, close friends list, blocked list | | capture first |

Variables. The two REST reads take nothing but the session and, for the POST, `fb_dtsg` and
`jazoest`, which the bootstrap gives. The collections take `first` and `after`. The GraphQL
activity view takes two request objects never observed and `mark_as_seen`; the badge takes a
`device_id` whose origin is not observed; saved posts take `collection_types` values never
observed.

Methods. `client.account.activity() -> ActivityFeed`, `client.account.follow_requests() ->
tuple[ProfileSummary, ...]`, `client.account.badges()`, `client.account.saved(*, after=None)`
and `iter_saved`, `client.account.collections()` and `iter_collections`,
`client.account.archive()`, `client.account.close_friends()`, `client.account.blocked()`. This
batch opens the `account` namespace (W20).

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
| `REST GET /api/v1/discover/web/explore_grid/` | the explore grid | hypothesis, observed once |
| `PolarisExploreLocationsContainerQuery` | a location's header | hypothesis |
| `PolarisLocationPageTabContentQuery` | a location's grid | hypothesis |
| `PolarisLocationPageTabContentQuery_connection` | its next pages | hypothesis |
| `PolarisAPICheckNewFeedPostsExistQuery` | new posts on the home feed | hypothesis |
| `PolarisClipsHomeRootQuery` | the reels feed | hypothesis, capture first |
| `PolarisClipsTabRootPaginationQuery` | its next pages | hypothesis, capture first |
| audio page | | capture first |

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
| `PolarisSearchNullStateQuery` | recent searches | hypothesis |
| `PolarisSearchBoxNonProfiledRefetchableQuery` | non-personalised typeahead | hypothesis |
| `PolarisHashtagHeaderActionButtonsQuery` | a hashtag's header | hypothesis |
| `PolarisSearchBoxContainerQuery` | typeahead across accounts, hashtags, places | hypothesis, capture first |
| `PolarisSearchBoxRefetchableQuery` | its refetch | alternate of the container, same root |
| `PolarisKeywordSearchExplorePageRelayQuery` and its pagination | keyword results, which a hashtag page renders | hypothesis, capture first |

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

## Visibility and second account, collected

| Item | Flag |
|---|---|
| Story seen mutation | Visible to the story's owner. Only on the owner's own story, arranged (W42). |
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
