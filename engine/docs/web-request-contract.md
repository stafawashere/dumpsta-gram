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
| `PROFILE_BY_ID` | `28036671149327607` | `PolarisProfilePageContentQuery` | `API_GRAPHQL_URL` | `read-a-user-profile` |
| `USER_ID_BY_USERNAME` | `28821682214127849` | `PolarisProfilePostsQuery` | `API_GRAPHQL_URL` | `resolve-a-username-to-a-user-id` |
| `HOME_TIMELINE_FEED` | `27932834733065642` | `PolarisFeedRootPaginationCachedQuery_subscribe` | `GRAPHQL_QUERY_URL` | `home-timeline-feed-page` |

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

- No write. Every query here is a read, and the write path is unmeasured on this surface.
- No mobile surface. The registry and the builders are web only, per ADR-0007.
- Nothing inside a post beyond its own fields. A carousel's slides, a video's renditions, the
  comments and the likers all arrive on the feed payload and all stop at the mapper, because no
  capability reads them.
