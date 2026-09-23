# The web request contract

What `dumpstagram/_private/web/` sends, why every field is in it, and what happens when one is
wrong. Written 2026-09-21, when the layer was implemented.

This is the canonical description of the request shape. [session-and-auth.md](session-and-auth.md)
owns the credential and token facts, [rate-limiting-and-safety.md](rate-limiting-and-safety.md)
owns the pacing numbers, and this document owns the request itself.

Provenance for every literal named here is the reverse-engineer knowledge base:
`bootstrap-web-tokens` and `direct-thread-message-page`, both `verified`, observed
2026-09-20 and replayed 2026-09-21. See
[../../docs/knowledge/live-reproduction-2026-09-21.md](../../docs/knowledge/live-reproduction-2026-09-21.md).

## The four modules and what each one may know

```
dumpstagram/_private/
   transport.py           Sender, Request, Response. The only place httpx exists
   web/
      classify.py         the only place a response becomes a success or a failure
      bootstrap.py        one authenticated page load, tokens out of the HTML
      documents.py        the persisted GraphQL query registry
      requests.py         the body and header set, built from a Session
```

`_core` never imports any of it directly and never sees a URL. It passes an intent plus typed
parameters, and the surface adapter turns that into a `Request`. This is the boundary
[ADR-0007](../../docs/decisions/ADR-0007-web-graphql-surface-first.md) exists to protect, so
that a later mobile private API surface is a second adapter rather than a rewrite.

## The two-request dependency

A GraphQL call cannot be made from a cold session. The order is fixed:

```
Session (cookies)
   -> bootstrap: GET /direct/inbox/
      -> fb_dtsg, lsd, app_id, spin, hsi, haste_session written onto the Session
         -> requests: POST /api/graphql carrying all of it
            -> classify: success or the error the body describes
```

The tokens are not cookies. They live in the HTML of any authenticated page. A `Session`
reloaded from disk carries the ones it was saved with, so a warm start costs one request and a
cold start costs two. Whether stored tokens survive long enough to make a warm start reliable
is UNRESOLVED; see the token lifetime question in
[../../docs/knowledge/assumptions-and-open-questions.md](../../docs/knowledge/assumptions-and-open-questions.md).

## Bootstrap

`bootstrap.py` loads `https://www.instagram.com/direct/inbox/` shaped as a navigation, not as
an API call: `sec-fetch-site: none`, `sec-fetch-mode: navigate`, `sec-fetch-dest: document`,
and redirects followed. Any authenticated page carries the tokens. This one is used because it
is the page both measured runs used and because the first target surface is the direct inbox.

### What is scraped, and the pattern that scrapes it

| Value | Pattern anchor | Notes |
|---|---|---|
| `fb_dtsg` | `"DTSGInitialData",[],{"token":"` | 84 chars on both measured days. The only body field the upstream validates |
| `lsd` | `"LSD",[],{"token":"` | 22 chars on both days |
| `__spin_r` | `"__spin_r":` | Rotates between days |
| `__spin_b` | `"__spin_b":"` | `trunk` on both days |
| `__spin_t` | `"__spin_t":` | |
| `__rev` | `"server_revision":`, falling back to `__spin_r` | |
| `__hsi` | `"hsi":"` | |
| haste session | `"haste_session":"` | Sent as `__hs` |
| app id | `"X-IG-App-ID":"` | Falls back to `936619743392459`, which was identical on both days |
| actor id | `"RelayAPIConfigDefaults",[],{"accessToken":"...","actorID":"` | Added 2026-09-23. The account's Facebook-side id, 17 digits, equal to the page's `NON_FACEBOOK_USER_ID` on every captured inbox and home document and different from `ds_user_id`. Stored as `Session.actor_id` and sent only by the note create. Optional: a page without it bootstraps, and only the create refuses |

### Three failure behaviours that are deliberate

**A missing `fb_dtsg` or `lsd` raises `AuthenticationFailed`.** It does not return `None` for
the request builder to send as an empty string. An empty `fb_dtsg` returns the HTML application
shell under HTTP 200, which reaches the caller as a schema failure and sends them looking in
entirely the wrong place.

**A challenge is checked for before the page is read.** `classify_checkpoint_only` scans the
response URL and any `Location` header, which is where user content cannot appear. Without it a
challenge redirect reaches the token scraper, comes back with no `fb_dtsg`, and is reported as
bad credentials. A dead session and a checkpointed account need different things from the user:
one needs re-adoption, the other needs the user to open a browser.

**The viewer id is never taken from the page.** Every `"USER_ID"` match in the bundle was the
logged-out placeholder `"0"` on both measured days. It comes from the `ds_user_id` cookie. This
is the inherited bug recorded in [session-and-auth.md](session-and-auth.md), generalised in
`_first_match`'s docstring: when scraping a value out of a bundle, ask what the *first* match
is, not merely whether a match exists.

The app id is the one value with a constant fallback, and that is defensible for a reason the
others do not share: it is not per session and not per page, so falling back is falling back to
a value that was correct twice, not to a guess.

## The persisted query registry

`documents.py` holds one `PersistedQuery` per query, each carrying its `doc_id`, its
`friendly_name`, the id of the finding it came from, and the URL it answers on. One name, one
place.

| Name | `doc_id` | Friendly name | URL | Finding |
|---|---|---|---|---|
| `THREAD_MESSAGE_PAGE` | `27502152406082940` | `useIGDMessageListPaginationQuery` | `API_GRAPHQL_URL` | `direct-thread-message-page` |
| `THREAD_DETAIL` | `28730473946590056` | `IGDThreadDetailQuery` | `API_GRAPHQL_URL` | `open-a-direct-thread` |
| `THREAD_OLDER_PAGE` | `28079551424999855` | `IGDMessageListOffMsysQuery` | `API_GRAPHQL_URL` | `direct-thread-older-page-offmsys` |
| `PROFILE_BY_ID` | `28036671149327607` | `PolarisProfilePageContentQuery` | `API_GRAPHQL_URL` | `read-a-user-profile` |
| `USER_ID_BY_USERNAME` | `28821682214127849` | `PolarisProfilePostsQuery` | `API_GRAPHQL_URL` | `resolve-a-username-to-a-user-id` |
| `HOME_TIMELINE_FEED` | `27932834733065642` | `PolarisFeedRootPaginationCachedQuery_subscribe` | `GRAPHQL_QUERY_URL` | `home-timeline-feed-page` |
| `INBOX_TRAY` | `29231580869776032` | `IGDInboxTrayQuery` | `API_GRAPHQL_URL` | `read-the-notes-tray-on-the-direct-inbox` |

The table above lists the entries the first capabilities added. `documents.py` is the complete
list, and its own docstrings carry each later entry's evidence.

**The notes tray is sent alone, a recorded departure.** Added 2026-09-23. `INBOX_TRAY` takes no
variables and is sent with `https://www.instagram.com/direct/inbox/` as its referer, the shape
of every captured inbox load. A browser never sends it by itself: an inbox load sends the
document, then ten queries within 4 ms of each other at about 500 ms, of which the tray is one,
then fifteen `IGDThreadDetailQuery` prefetches, the common page-load companions and the cookie
sync tail. The engine does not model the inbox load's direct block yet, so `notes()` sends the
tray query alone under every behavior. It is not a `Behavior` setting, because a setting chooses
between routes and there is only one route here. Modelling the inbox load, from findings
`direct-inbox-thread-list`, `direct-inbox-unread-thread-count`, the six empty-variable direct
findings and this one, would make it the parity route and add the setting.

**A post read, a like and an unlike are each sent alone, a recorded departure.** Added
2026-09-23 with Step 15. `POST_BY_SHORTCODE` (`27830990013244856`, `PolarisPostRootQuery`),
`LIKE_MEDIA` (`27182485238052618`, `usePolarisLikeMediaXIGLikeMutation`) and `UNLIKE_MEDIA`
(`27345296031770102`, `usePolarisLikeMediaXIGUnlikeMutation`) all answer on `API_GRAPHQL_URL`.
The post read's variables are the shortcode and the two provider values the profile timeline
query was captured sending, `PolarisShortDramaEnabled` false and
`PolarisMultiCaptionCarouselEnabled` true, with the post page as its referer. Both mutations take
`{"input": {"client_mutation_id", "media_id", "tracking_token"}}`: `media_id` is the media `pk`,
FACT from six sends, `client_mutation_id` is the account pacer's count of writes built, as a
browser tab counts its mutations, and `tracking_token` is null. The referer is the home page,
where a feed like is made. What a browser sends around any of them is unrecorded, because
ruling 23 in [build-plan.md](build-plan.md) allowed no browser load when the three were verified,
and every observation is an engine send. So the parity gate for each holds the one request's
shape, and three details are departures by omission until a browser capture says otherwise:
the Relay network layer's `actor_id`, absent because the session does not hold it; the feed
item's `organic_tracking_token`, null because the capability is handed an identifier and not the
item; and the post page's own document and companions. All six sends succeeded with those
omissions. The discovery sends carried the post page as referer and the acceptance sends the
home page, and both answered the same, which is weak evidence the referer is not checked here.

**A comment page read, a comment and a comment delete are each sent alone, a recorded
departure.** Added 2026-09-23 with Step 16. `COMMENT_PAGE` (`28169471862682868`,
`PolarisPostCommentsPaginationQuery`), `CREATE_COMMENT` (`27261905640092552`,
`PolarisPostCommentInputRevampedMutation`) and `DELETE_COMMENT` (`27034318419564986`,
`usePolarisPostDeleteCommentMutation`) all answer on `API_GRAPHQL_URL`, every one keyed on the
media `pk`. The page read sends `after`, `before` null, `first` 10, `last` null, `media_id`,
`sort_order` "popular" and `PolarisIsLoggedIn` true. The create sends `{"connections": [],
"data": {"comment_text", "media_id"}}`: its variable is `data`, so no `client_mutation_id`, and
`connections` is a handle into the browser's Relay store that the engine does not have, sent
empty and accepted on three sends. The delete sends `{"input": {"client_mutation_id",
"comment_id", "media_id"}}`, `client_mutation_id` from the account pacer's write count as for a
like. The delete's input field names are not in its compiled artifact and the bundle holding the
call site was never loaded, so they were settled by the upstream's own coercion on 2026-09-23: an
input of only `client_mutation_id` was refused with code 1675012 `noncoercible_variable_value`,
and `comment_id` "0" with `media_id` was accepted and answered a null root, nothing deleted,
before any real write was sent. Departures by omission until a browser capture says otherwise:
the post page's own document and companions, the post page's first comment page query
`PolarisPostCommentsContainerQuery`, which the engine replaces with the pagination query for every
page, the browser's page size, which is unobserved and makes `first` 10 an ASSUMPTION, the
Relay store handle in `connections`, the delete's `actor_id`, and the post page as referer, since
each capability is handed a `pk` and not the shortcode the page address needs. The referer is the
home page on every send. All fourteen engine sends carried those omissions, seven reads, three creates and four deletes, and every real write applied.

**A follow and an unfollow are each sent alone, a recorded departure.** Added 2026-09-23 with
Step 17. `FOLLOW_USER` (`27767812149509802`, `usePolarisFollowUserFollowMutation`) and
`UNFOLLOW_USER` (`25174972798866458`, `usePolarisFollowUserUnfollowMutation`) answer on
`API_GRAPHQL_URL`, with the home page as referer, where the compiled artifact was read off a
suggested account's Follow button. Each sends `{"target_user_id": <numeric account id>}` and
nothing else: the variable is not `input`, so the Relay network layer adds no
`client_mutation_id` and no `actor_id`, and the follow's `include_follow_friction_check` is a
literal in the query text rather than a variable. The follow answers `data.xdt_create_friendship`
and the unfollow `data.xdt_destroy_friendship`, each `{"friendship_status": {"following"},
"id"}` with the account id echoed. Each finding reached two observations with the discovery run's
engine sends before either `doc_id` entered `documents.py`, and three with the acceptance run.
Three other compiled follow artifacts and two unfollow ones, `usePolarisFollowMutation`,
`usePolarisFollowMutationBypassFrictionMutation`, the `ToggleFollow` pair and
`usePolarisUnfollowMutation`, take `container_module` and `nav_chain` or media attribution, and
were not sent. Which one the profile header's button holds is unobserved. Departures by omission
until a browser capture says otherwise: the page the follow is made from and its load, any
companion a click sends, and the header's own artifact if it differs. All six engine sends, three
follows and three unfollows, carried those omissions, and every one applied, confirmed by a
profile read.

**The inbox listing is private and sent alone.** Added 2026-09-23 with Step 20. `DIRECT_INBOX`
(`28794932076791671`, `PolarisDirectInboxQuery`) answers on `API_GRAPHQL_URL` with the inbox as
referer and no path headers. Its variables are `device_id_for_iris_subscription` and four
provider flags, `IGDIsProfessionalAccountGK` false, `IGDPinnedThreadsRenderEnabledGK` true,
`IGDMaxUnreadMessagesCount` 5 and `IGDThreadListActionsEnabledGK` true, the values every
captured inbox load sent for this account. A browser mints the device id per document, and a
replay with a random one answered, so the caller of `build_inbox_listing_request` passes one it
keeps for as long as its inbox is notionally open. No capability method sends it. The listener
behind `events()` does, from Step 23, as one request per poll with one device id for the
listener's life, followed by `IGDMessageListOffMsysQuery` pages for each thread whose newest
message moved, the older page builder with a null cursor for the newest page. A poll is a
departure from parity under ADR-0013 whatever the preset, because no browser was seen
re-reading the listing on a timer, and the push socket is the likely reason, INFERENCE. It also
leaves out what a browser sends around a thread it reads, the thread open and the mark-read
mutation, so a listener marks nothing seen.

**A note set and a note delete are each sent alone, a recorded departure.** Added 2026-09-23
with Step 14. `CREATE_NOTE` (`28592645767037889`, `usePolarisCreateInboxTrayItemSubmitMutation`)
and `DELETE_NOTE` (`28419182984337833`, `usePolarisDeleteInboxTrayItemSubmitMutation`) answer on
`API_GRAPHQL_URL`, both with the inbox as referer, where the composer lives. The create sends
`{"input": {"actor_id", "additional_params": {"note_create_params": {"note_style": 0, "text"}},
"audience", "client_mutation_id", "inbox_tray_item_type": "note"}}`, where `actor_id` is
`Session.actor_id` from the bootstrap page and never `ds_user_id`, `audience` is 0 or 1, and
`client_mutation_id` is the account pacer's write count as for a like. Audience 1, close friends,
was first sent by the engine on 2026-09-23 and the answer and the tray both carried it back. The
delete sends `{"inbox_tray_item_id"}`, not wrapped in `input`, so no `client_mutation_id`, and its
success is a null root field. Each finding reached two observations with the discovery run's
engine sends, before either `doc_id` entered `documents.py`, and three with the acceptance run.
Departures by omission until a browser capture says otherwise: the inbox load a browser has
already made around the composer, and the bootloader requests that opening the composer and the
own-note popup send. Every engine send carried those omissions, two creates and two deletes, and
every write applied.

**The URL is per query, and that was learned the hard way rather than designed.** It was one
module constant until 2026-09-21, when the feed was added. The feed answers only on
`https://www.instagram.com/graphql/query`. The identical request, same `doc_id`, same headers,
same variables, posted to `https://www.instagram.com/api/graphql` where the other three answer,
comes back HTTP 200 with `data.xdt_api__v1__feed__timeline__connection` set to null, no `errors`
array, no `error` field and no `errorSummary`. There is nothing in that body for `classify` to
catch, so a caller sees an empty feed rather than a failure. A query's path is therefore part of
its recorded contract, and a new entry copies the path its finding observed rather than the one
its neighbour uses.

A `doc_id` written inline at a call site is the literal the provenance gate exists to catch.
Rotation is the most fragile thing in the system: a rotated id returns an error envelope under
HTTP 200, so nothing downstream notices. When a query starts failing, the registry entry is the
first suspect and the fix is a replay through the `reverse-engineer` skill, not an edit here.

## The request body

Twenty-two form fields, `application/x-www-form-urlencoded`.

```
av  __d  __user  __a  __req  __hs  dpr  __ccg  __rev  __hsi  __comet_req
fb_dtsg  jazoest  lsd  __spin_r  __spin_b  __spin_t
fb_api_caller_class  fb_api_req_friendly_name  server_timestamps  doc_id  variables
```

`jazoest` is computed rather than scraped: the string `"2"` followed by the sum of the
character codes of `fb_dtsg`. It is not a checksum the upstream verifies. It is reproduced
because the browser sends it.

`av` is the viewer id, from the cookie. `__user` is `"0"`, which is what the browser sends and
is not the viewer id despite its name.

## The header set

Fourteen headers: `content-type`, `sec-fetch-site`, `sec-fetch-mode`, `sec-fetch-dest`,
`user-agent`, `x-ig-app-id`, `x-csrftoken`, `x-fb-lsd`, `x-fb-friendly-name`, `x-asbd-id`,
`origin`, `referer`, `accept`, `accept-language`.

The `referer` names the thread being read, which is the page a request like this comes from.

A query that answers on `/graphql/query` adds two more, `x-bloks-version-id` and
`x-root-field-name`. FACT from every capture of 2026-09-23: each browser request to that path
carried both, and no request to `/api/graphql` carried either, so `PersistedQuery` decides it
from its path. The bloks id is the `versioningID` of the `WebBloksVersioningID` config in the
bootstrap page, 64 hex characters, stored on the session as `bloks_version_id`. The root field
is the query's own `root_field`. A session with no bloks id is bootstrapped before the feed
request, and a page that stops carrying the config makes the builder raise `SchemaChanged`
rather than send an empty header. Neither header has been ablated, so whether the upstream
checks them is unknown.

Every browser request on both paths also carried `x-ig-max-touch-points`, which the engine does
not send yet. It belongs with the common page-load burst.

Redirects are not followed on the GraphQL POST. A followed challenge redirect hides itself from
the URL scan that `classify` performs first.

## Why the padding is sent when only three items are checked

FACT, from the prior project's 33-request single-removal ablation: exactly three of roughly 38
items sent are validated.

| Item | Where | What happens without it |
|---|---|---|
| `fb_dtsg` | body | HTML application shell under HTTP 200 |
| `sec-fetch-site` | header | Rejected |
| `content-type` | header | Rejected |

Everything else can be dropped without the upstream noticing. It is sent anyway, and that is a
decision rather than an oversight. **A request carrying only what is validated is a request no
browser has ever sent**, which makes it trivially distinguishable from one. The cost of the
padding is zero and the cost of being distinguishable is an account.

This is why there are two separate gate families over the request: one asserting the three
validated items are present, and one asserting the full 22-field body and 14-header set has not
eroded. The second one would look like pedantry without this reasoning behind it.

The validated items are named in code as `VALIDATED_BODY_FIELDS` and `VALIDATED_HEADERS`, so a
session that needs to know which three they are does not have to find this document first.

## Pagination

`build_thread_page_request` takes `after` for the cursor and `newer_than_message_id` for a
top-up. Termination comes from `page_info.has_next_page` and never from a short page.

Since 2026-09-23 the capability sends two other queries and the old builder serves only the
internal smoke read and the probes. `build_thread_detail_request` is the thread open: variables
`min_uq_seq_id` null, `thread_fbid`, `IGDEnableOffMsysChatThemesQErelayprovider` false and
`IGDInitialMessagePageCountrelayprovider` 20, in that order. FACT from the four captures of
2026-09-23: all 63 browser requests carried exactly that, false included. The finding's replay
template carries true and answered too, so the flag is not what makes the request succeed, and
the engine sends what the browser sends. The answer roots at
`data.get_slide_thread_nullable.as_ig_direct_thread.slide_messages`, with the same 28-key message
nodes the pagination query returns. Its `end_cursor` is the `after` of the browser's first older
page, FACT from the same captures. `build_thread_older_page_request` sends the eight variables
`build_thread_page_request` sends to `IGDMessageListOffMsysQuery`. Every browser request on it
carried a 132-character `after` and a null `newer_than_message_id`, so a top-up on this query is
ASSUMPTION: same variables and root field as the old query, never sent by anything yet.

`PAGE_SIZE` is 20 and there is no reason to change it. Requesting 20, 50, and 200 each returned
exactly 20. Request count is therefore a fixed function of data volume, which is what makes a
dry-run cost estimate possible at all.

`newer_than_message_id` is the variable the prior project always passed as null. For a polling
listener it is the difference between a constant drip and a full re-read, which is why it is in
the signature from the start. See
[realtime-events.md](realtime-events.md).

## Identifier kinds

`thread_fbid` is in the parameter name on purpose. One thread has three distinct ids and the
names are not portable across Instagram's own surfaces: `thread_fbid` in server-rendered HTML,
`thread_v2_id` in REST, `messaging_thread_key` for the URL alias, and `thread_id` meaning
something else entirely. Passing the wrong kind returns an empty result rather than an error,
so the kind belongs in the signature rather than in something a caller works out.

One exception observed on 2026-09-23. `IGDThreadDetailQuery` takes its id as `thread_fbid`, yet
14 of the 16 detail queries in one capture asked with a different id and got back a thread whose
`thread_fbid` differed from the one asked for, with `thread_key` echoing the asked id. The
browser's older pages then used the returned `thread_fbid`. So the detail query resolves at
least the URL id to the fbid. FACT from one capture. The engine does not rely on it yet.

## Two literals the provenance gate is told to ignore

`check_provenance.py` matches literals by shape, so two values in `bootstrap.py` trip it while
being genuinely not endpoints. Both carry `# provenance: ignore` with a reason on the same line,
which is the mechanism the gate documents for exactly this case.

| Literal | Why it is not an endpoint |
|---|---|
| `ORIGIN = "https://www.instagram.com"` | An origin. It is used for the `origin` and `referer` headers, not as a request target |
| `DEFAULT_APP_ID = "936619743392459"` | An `x-ig-app-id` header value. Fifteen digits, so it matches the `doc_id` pattern |

A related trap is worth naming. `BOOTSTRAP_URL` and the GraphQL URL were originally f-strings
over `ORIGIN`, which meant the scanner never saw either endpoint and reported a clean tree that
proved nothing about them. They are written as full literals so the gate can actually check them,
and `API_GRAPHQL_URL` and `GRAPHQL_QUERY_URL` in `documents.py` keep that form. Any URL assembled
at runtime is invisible to this gate.

## What is not implemented here

- No write request. Every query here is a read. The write path exists in `_core/writing.py`,
  and no write request has been built on it yet.
- No mobile surface. The registry and the builders are web only, per ADR-0007.
- Nothing inside a post beyond its own fields. A carousel's slides, a video's renditions, the
  comments and the likers all arrive on the feed payload and all stop at the mapper, because no
  capability reads them.
