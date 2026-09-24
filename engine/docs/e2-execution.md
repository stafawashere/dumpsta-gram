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
| 1 | Direct read side | `probes/e2_direct_read.py` | 8 | 3 |
| 2 | Profile tabs over GraphQL | `probes/e2_profile_tabs.py` | 12 | 4 |
| 3 | Relationship lists | `probes/e2_follow_lists.py` | 6 | 1 |
| 4 | Post depth | `probes/e2_post_depth.py` | 13 | 7 |
| 5 | Stories, read only | `probes/e2_stories.py` | 8 | 4 |
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
| `PolarisDirectInboxQuery` | first page | verified, private since Step 20 |
| `IGDThreadListOffMsysPaginationQuery` | next pages | hypothesis |
| `IGDMessageRequestLeftRailStandaloneQuery` | pending and spam folders | hypothesis |
| `useIGDSystemFolderUnreadThreadCountQuery` | unread counts per folder | verified |
| `IGDBadgeCountOffMsysQuery` | the direct badge | verified, a shipped companion |
| `IGDInboxInfoOffMsysQuery` | a thread's details panel | hypothesis |

Variables. The iris device id is a fresh uuid per client, as the poller already sends. The next
page takes the mailbox `id` and the `end_cursor` from the first page, `folder` INBOX, and
`count` 15, which is the first page's compiled size and not an observed value. The requests
query takes the device id and a "30 days ago" timestamp in milliseconds, whose type is not
observed. The details panel takes a `thread_fbid`, which `direct.threads` rows carry.

Methods. `client.direct.threads(*, after=None) -> Page[Thread]` and `iter_threads(*, limit)`,
the private inbox listing made public; `client.direct.requests() -> Page[Thread]` for pending,
with spam as a folder argument if the answer separates them; `client.direct.unread_counts()`;
`client.direct.thread_info(thread_fbid)`. The `Thread` model is new and public.

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
| `PolarisProfilePostsQuery` | the grid's first page | verified |
| `PolarisProfilePostsTabContentQuery_connection` | the grid's next pages | hypothesis |
| `PolarisProfileStoryHighlightsTrayContentQuery` | the tray's first page | verified |
| `ProfileStoryHighlightsTrayContentQuery_connection` | the tray's next pages | hypothesis |
| `PolarisProfileSuggestedUsersWithPreloadableQuery` | suggested beside a profile, preloaded | verified |
| `PolarisProfileSuggestedUsersWithLazyQueryQuery` | the same, on demand | hypothesis, variables observed |
| `PolarisSuggestedUserListQuery` | the suggested accounts list | hypothesis, variables observed |
| `PolarisSuggestedUserListRefetchQuery` | its refetch | alternate of the list, same root |

Variables. The grid is keyed on `username`, which `profiles.by_id` returns, with `data` copied
from the verified first page and `after` from its cursor; `first` and `include_multi_captions`
on the next page are not observed. The tray is keyed on the numeric `user_id`. The suggested
lists take `target_id` and module `profile`, or a `data` object with module `discover_people`,
both observed in a recorded browse.

Methods. `client.profiles.posts(user, *, after=None) -> Page[Post]` and `iter_posts`, where
`user` is a `Profile` or a username; `client.profiles.highlights(user_id) ->
Page[Highlight]` and `iter_highlights`; `client.profiles.suggested(user_id)` and
`client.profiles.suggested_for_you()`, each returning `tuple[ProfileSummary, ...]`.

Pagination. `page_info.has_next_page` on both connections.

Side effect. None.

Needs capture first (batch 10): the profile's reels tab and tagged tab. No page load compiled
either, and neither is in the home document's lazy chunk map.

## Batch 3: relationship lists

| Operation | Kind | Status |
|---|---|---|
| `REST GET /api/v1/friendships/{user_id}/followers/` | followers, one page | hypothesis, observed once |
| `REST POST /api/v1/friendships/show_many/` | the viewer's relationship to many ids | hypothesis, observed once |
| following | | capture first |
| mutual followers | | capture first |

Variables. The followers page takes the account's numeric id in the path and the query
`count` 12 and `search_surface` follow_list_page, observed on the owner's own followers. The
next page parameter is not observed; the probe tries `max_id` from `next_max_id` once and records
the answer as evidence for or against it. `show_many` takes the listed ids as `user_ids`.

Methods. `client.profiles.followers(user_id, *, after=None) -> Page[ProfileSummary]` and
`iter_followers`, `client.profiles.following` and `iter_following`, and
`client.profiles.mutual_followers(user_id)`. The relationship statuses fold into
`ProfileSummary.friendship_status`, as the browser's list does, rather than a method.

Pagination. `next_max_id` and `has_more`, both in the answer. Which of the two the web client
stops on is not observed, and the model waits for that before it names a terminator.

Side effect. None. Reading any account's list is visible to nobody (W43), but E2 acceptance runs
on the owner's own lists, and on a public account the owner follows for mutual followers.

## Batch 4: post depth

| Operation | Kind | Status |
|---|---|---|
| `PolarisPostChildCommentsQuery` | replies, first page | hypothesis |
| `PolarisPostCommentsChildrenPaginationtQuery` | replies, next pages | hypothesis |
| `PolarisPostLikedByListDialogQuery` | likers | hypothesis, lazy |
| `PolarisPostActionLoadPostQueryMediaIdQuery` | a post by media pk | hypothesis |
| `PolarisPostModalContextQuery` | a post modal's context | hypothesis |
| `PolarisDesktopPostPageRelatedMediaGridQuery` | more posts from the author | hypothesis |

Variables. Every one takes the media `pk`, which `feeds.home`, `profiles.posts` and
`media.by_code` return. Replies also take the parent comment's `pk` from `media.comments`, plus
`is_chronological` and `first`, neither observed. The related grid takes the author's id from the
post and a `count` that is not observed.

Methods. `client.media.replies(post_pk, comment_id, *, after=None) -> Page[Comment]` and
`iter_replies`; `client.media.likers(post_pk) -> tuple[ProfileSummary, ...]`, since the
artifact selects `likers_connection.nodes` with no page info; `client.media.by_id(post_pk) ->
PostDetail`; `client.media.more_from_author(post_pk, author_id) -> tuple[Post, ...]`. User tags,
location and collaborators are new fields on `Post` and `PostDetail`, not methods: the item
`by_id` answers selects `usertags`, `location` and the coauthor fields, and the probe records
their keys. Carousel children came with the E1 model.

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
| `PolarisStoriesV3TrayContainerQuery` | the tray | verified, a shipped companion |
| `PolarisStoriesV3ReelPageStandaloneQuery` | one account's reel, or one highlight | hypothesis, variables observed |
| `PolarisStoriesV3ReelPageGalleryQuery` | the gallery around a reel | hypothesis, variables observed |
| `PolarisStoriesV3ReelPageGalleryPaginationQuery` | the gallery's next reels | hypothesis, variables observed |
| `PolarisStoriesV3SeenMutation` | mark one item seen | hypothesis, variables observed, WRITE-LIKE |

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
