# Live reproduction: bootstrap plus one page

Run on 2026-09-20 from this repository, against live Instagram, with `httpx` under
`uv run --with httpx` on CPython 3.12.13. Exactly two requests were sent. Read only. Nothing
was written, sent, marked read, or reacted to.

This is the run the corpus has been asking for since the first documentation pass. Its purpose
was to convert facts inherited from `dumpsta-js` into facts measured here. Related:
[prior-art-dumpsta-js.md](prior-art-dumpsta-js.md) for the inherited set and
[assumptions-and-open-questions.md](assumptions-and-open-questions.md) for what is still open.

## What was run

A throwaway probe script in the session scratchpad, not committed and not part of the engine.
No product code was scaffolded, because the engine's public API has not been designed yet and
this run must not prejudge it.

| Step | Request | Purpose |
|---|---|---|
| 1 | `GET https://www.instagram.com/direct/inbox/` | Bootstrap. Harvest `fb_dtsg`, `lsd`, the `__spin_*` family, and the app id out of the HTML. |
| 2 | `POST https://www.instagram.com/api/graphql` | One page of `useIGDMessageListPaginationQuery`, `doc_id` `27502152406082940`, `first: 20`, `after: null`. |

Credentials came from `.env` at the repository root, holding `IG_SESSIONID`, `IG_DS_USER_ID`,
`IG_CSRFTOKEN`, `IG_MID` and `IG_USER_AGENT`, in the shape
[the prior project's credential doc](../../../dumpsta-js/ghost/docs/protocol/credentials-and-tokens.md)
describes. No login was attempted. Reference thread fbid `17945046917948992`.

Spacing between the two requests was 2850 ms, the inherited 0.351 req/s anchor.

## Results

### Bootstrap

| Measure | Value |
|---|---|
| Status | 200 |
| HTML size | 809815 bytes |
| Elapsed | 449 ms |
| `fb_dtsg` length | 84 chars |
| `lsd` length | 22 chars |
| `x-ig-app-id` | 936619743392459 |
| `__spin_r` and `__rev` | 1047994416 |
| `__spin_b` | trunk |
| `__hsi`, `haste_session` | present |

### Page

| Measure | Value |
|---|---|
| Status | 200 |
| Body size | 37807 bytes |
| Elapsed | 151 ms |
| Top-level keys | `data`, `extensions` |
| `errors` array | absent |
| Canonical path `data.fetch__SlideThread.as_ig_direct_thread.slide_messages` | present |
| Edges | 20 |
| `page_info.has_next_page` | true |
| `end_cursor` length | 132 chars |
| Newest message id | `mid.$cAAANx1A4CESm8y_m2mgweqeUAaea` |

## Inherited facts now local

These were FACT by inheritance. They are now FACT by measurement in this repository.

| Claim | Status |
|---|---|
| Python via `httpx` is not blocked. | Reproduced. Both requests returned real data on the first attempt. |
| The web GraphQL surface needs no device fingerprint and no request signing. | Reproduced. The request carried cookies, harvested tokens, and browser-shaped headers, and nothing else. |
| Bootstrap token extraction works against the live bundle. | Reproduced. `fb_dtsg` is still 84 chars and `lsd` is still 22 chars, matching the inherited figures exactly. |
| `doc_id` `27502152406082940` is still served. | Reproduced. |
| The response path `fetch__SlideThread.as_ig_direct_thread.slide_messages` is unchanged. | Reproduced. No fallback connection search was needed. |
| Cursors are 132 characters. | Reproduced exactly. |
| `jazoest` computed as `"2"` plus the sum of `fb_dtsg` char codes is accepted. | Reproduced. |
| Sustained pacing at 0.351 req/s draws no throttling. | Not meaningfully tested at two requests. The inherited 306-page figure stands on its own evidence. |

## What this run did not reproduce

- **Page size cap of 20.** Only `first: 20` was sent, so the cap was not probed. The returned
  edge count of 20 is consistent with the cap but does not re-establish it.
- **HTTP 200 is not a success signal.** No failure occurred, so no error envelope was observed
  here. The claim remains inherited. Reproducing it means deliberately sending a bad request,
  which the prior project measured as safe on one day on one account and which is not worth
  spending on now.
- **Writes, the mobile private API, realtime, group threads, and any non-residential IP.** All
  still untouched, exactly as before.

## Two new local observations

**Every `"USER_ID"` match in the bootstrap HTML was `"0"`.** The prior project's rule was that
the first match is the logged-out placeholder and a later match carries the real viewer id. In
this run there was no non-zero match at all, so the fallback to the `ds_user_id` cookie is not
a safety net, it is the only source of the viewer id. A client that trusts the HTML for
`viewer_id` and has no cookie fallback will set it to `"0"` and invert the outgoing flag on
every record. The engine must read the viewer id from the cookie and treat the HTML as
confirmation at best.

**The message node carries fields the prior corpus never recorded**, including
`bot_response_id`, `is_ai_generated`, `igd_wearables_attribution_text`,
`igd_wearables_attribution_type`, `is_tombstone_revealable` and `is_pinned`. The schema has
moved since 2026-09-21. This is the churn that
[ADR-0007](../decisions/ADR-0007-web-graphql-surface-first.md) expects to stop at the engine
boundary, and it is a concrete argument for typed models that ignore unknown fields rather
than models that fail on them.

Also worth recording: `__spin_r` was `1047994416` here against `1047991119` in the inherited
transcript, and the bootstrap HTML was 809815 bytes against 811590. Both move without notice.
Nothing may be pinned to either.

## Safety note carried forward

`.env` at the repository root holds a live `sessionid`, which is a full account takeover token
with no second factor. It must stay out of version control and out of any log, export, or
error message. The same hazard already recorded for `dumpsta-js/ghost/.ghostrc` in
[risks-and-constraints.md](risks-and-constraints.md) now exists in this repository too.
