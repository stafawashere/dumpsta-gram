# Session, authentication, and identity

Phase 1 of [roadmap.md](roadmap.md). The layer everything else sits on. If this is wrong,
every feature above it is wrong.

Revised 2026-09-20 against measurements inherited from
[../../docs/knowledge/prior-art-dumpsta-js.md](../../docs/knowledge/prior-art-dumpsta-js.md).
Claims are tagged. The web surface now carries real evidence. The mobile surface does not.

## Two surfaces, one chosen

The corpus originally assumed the mobile private API and treated device fingerprinting and
request signing as the hard core of this phase. A prior JavaScript project measured a different
route working, and it needs neither. **The web surface is now the target**, per
[../../docs/decisions/ADR-0007-web-graphql-surface-first.md](../../docs/decisions/ADR-0007-web-graphql-surface-first.md).
The mobile column below is kept for the day a second adapter is justified.

| | Web GraphQL surface | Mobile private API |
|---|---|---|
| Evidence | Measured live, 2026-09-21, roughly 650 requests | None |
| Device fingerprint | Not required. FACT | Assumed required. ASSUMPTION |
| Payload signing | Not required. FACT | Assumed required. ASSUMPTION |
| Credential | Borrowed browser `sessionid` cookie plus tokens scraped from one HTML page. FACT | Unknown |
| Proven capability | Reading direct-message threads | Unknown |
| Full capability goal | Unknown | Assumed reachable. INFERENCE |

Consequences of choosing the web surface, all of which shrink Phase 1: no device identity is
generated, no signing code is written, and the credential material is browser-shaped. The
transport in `_private` still describes requests as an intent plus typed parameters, so a
mobile adapter can be added later without touching `_core`.

## What the web surface actually validates

FACT. Established by ablation against the live API: one baseline request, then the same request
re-sent 33 times with one field or header removed each time, at 3500 ms spacing.

The browser sends 26 body fields and about a dozen headers. Exactly three things are checked.

| Layer | Validated | Provably ignored |
|---|---|---|
| Body | `fb_dtsg` | 19 other fields, including `lsd`, `jazoest`, `__spin_*`, `av`, `__user` |
| Headers | `content-type`, `sec-fetch-site` | 8 others, including `x-csrftoken`, `x-ig-app-id`, `user-agent`, `referer`, `origin` |

Single-removal ablation cannot prove a minimum, since it only shows each field is individually
unnecessary. The minimum was therefore constructed and sent directly, and it worked.

**Knowing the minimum is not a reason to send it.** A stripped request is a fingerprint. The
prior client kept sending the full browser-shaped request deliberately, and documented the
minimum only so a future breakage could be bisected. This project inherits that posture. See
[../../docs/decisions/ADR-0003-no-browser-driver.md](../../docs/decisions/ADR-0003-no-browser-driver.md).

## HTTP 200 is not a success signal

FACT, and the single most important operational finding inherited. Every failure mode observed
on the GraphQL gateway arrived with status `200` and an error envelope in the body. Missing
`fb_dtsg`, missing `sec-fetch-site`, and missing `content-type` all return 200. The last one
returns the HTML app shell, because the form body is never parsed.

A client that branches on status alone reads a rejected request as a successful one and writes
an empty result while reporting success.

The transport layer therefore inspects the body on every response, and the error hierarchy is
driven by payload content rather than status code. This is an architectural invariant, recorded
in [architecture.md](architecture.md), not a defensive nicety.

## The `Session` object

Per-account state, constructed by the caller, passed into a client, serializable to disk and
back. See
[../../docs/decisions/ADR-0004-instance-scoped-sessions.md](../../docs/decisions/ADR-0004-instance-scoped-sessions.md).

| Field group | Contents | Notes |
|---|---|---|
| Credential material | The three required cookies plus the scraped tokens | Identity |
| Device identity | Present in shape only, unpopulated | Not needed on the web surface. FACT. No generator gets written until a mobile adapter exists |
| Proxy configuration | Proxy URL and credentials if used | Part of apparent identity, so it belongs here rather than as a per-call argument |
| Checkpoint state | Whether the account is currently in a challenge | An account-level pause, not a global one |

### Cookies on the web surface

FACT. Three cookies are required and the session constructor should refuse to start without
them: `sessionid`, `ds_user_id`, `csrftoken`. Others, `mid`, `datr`, `ig_did`, `rur`, are
present in a real browser jar and are carried when available.

Note the asymmetry. `csrftoken` is required as a cookie, and the `x-csrftoken` header derived
from it is not validated. It also does not substitute for `fb_dtsg`. Dropping `fb_dtsg` while
keeping the header returns the HTML shell.

### Tokens come from one authenticated page load

FACT. `fb_dtsg` and `lsd` are not cookies. They are embedded in the HTML of any authenticated
page and are extracted by regex from a minified bundle. Observed lengths were 84 and 22
characters respectively, from roughly 810 KB of HTML. `jazoest` is computed rather than
scraped, as `"2"` followed by the sum of the character codes of `fb_dtsg`.

This extraction is the second most fragile thing in the system, behind `doc_id` rotation. A
module rename, a quoting change, or a Relay upgrade breaks it with no notice. The failure must
be loud: raise rather than proceed with a null token.

Implemented 2026-09-21 in `dumpstagram/_private/web/bootstrap.py`. A missing `fb_dtsg` or `lsd`
raises `AuthenticationFailed`, and the response URL is scanned for a challenge before the page
is read, so an account sitting in a checkpoint is not reported as having bad credentials. The
finding behind it is `bootstrap-web-tokens` in the reverse-engineer knowledge base.

### What the session file stores, added 2026-09-21

`hsi` and `haste_session` joined the serialised session at `schema_version` 1. They are the
`__hsi` and `__hs` body fields, both ignored by the upstream under ablation and both sent to
match the shape a browser sends. The version was not bumped because the format already ignores
unknown keys on read and defaults missing ones, and nothing has been released that could hold
a file without them. A reloaded session therefore reproduces the observed request exactly,
rather than sending two empty fields.

### `bloks_version_id`, added 2026-09-23

The `x-bloks-version-id` header value, read from the bootstrap page's `WebBloksVersioningID`
config and sent on every `/graphql/query` request. Added at `schema_version` 1 for the same
reason as `hsi`: missing keys load as `None`. A session saved before it existed carries page
tokens but no bloks id, and the feed bootstraps once to get it rather than failing. Its lifetime
is unmeasured. INFERENCE: it tracks a web build, so it changes on deploys rather than per
session.

### `actor_id`, added 2026-09-23

The account's Facebook-side id, read from the bootstrap page's `RelayAPIConfigDefaults` config,
where it is the `actorID`, and sent by the note create as `actor_id`. FACT from captures and one
live bootstrap: 17 digits, equal to the page's `NON_FACEBOOK_USER_ID`, and a different number from
`ds_user_id`, which stays the only source of the viewer's Instagram id. Added at
`schema_version` 1 under the key `"actor_id"` for the same reason as `hsi`: missing keys load as
`None`. A session saved before it existed carries page tokens but no actor id, and `set_note`
bootstraps once to get it rather than failing. The bootstrap never fills it with `ds_user_id`.
It is an identifier of the viewer's own account, not a credential, so it is not redacted, and
the probes that read it log only its length.

### `fr`, added 2026-09-23

The page-load cookie sync sends the `fr` value a browser keeps in `localStorage`, and the
engine carries it as `Session.fr` under the key `"fr"` at `schema_version` 1, `None`
when absent, never in a representation or a log. The design, the update rule it copies
from the page, and the ruling that lets it be supplied at adoption as `IG_FR` are in
[build-plan.md](build-plan.md), section 17.2.3.

The cookie sync tail in `_core/cookie_sync.py` applies that rule since 2026-09-23. It sends
the stored value, or null, as the exchange's payload. An answer equal to it changes nothing,
an empty answer sets `fr` to `None`, any other answer is stored, and a failed exchange sets it
to `None`. The engine changes the session in memory only. The CLI saves it after each command,
but a one-shot command usually closes its client before the tail departs, so the stored value
changes only for a caller whose client lives past the 4 to 10 s delay. A tail that meets a
checkpoint sets `Session.checkpoint_active`.

## Two inherited bugs worth not repeating

Both had the same shape, and both produced a complete, plausible, entirely wrong result rather
than an error. That failure class is the one no amount of eyeballing output catches.

**The first regex match was the wrong one.** `"USER_ID"` appears more than once in the page, and
the first occurrence is the logged-out placeholder `"0"`. Taking match zero set the viewer id to
`"0"`, which would have inverted the outgoing flag on every exported record. Nothing errors.

Generalised rule, and it is worth applying everywhere in `_private`: when scraping a value out
of a bundle, ask what the *first* match is, not merely whether a match exists.

**Plausible field names held different numbers.** One thread has three distinct ids, and the
names are not portable across Instagram's own surfaces. The same thread is `thread_fbid` in
server-rendered HTML, `thread_v2_id` in REST, `messaging_thread_key` for the URL alias, and
`thread_id` means something else entirely. A resolver that searched for the names used by one
surface returned "unresolved" for a thread fully described in the page it had just downloaded.

Generalised rule: grep the artifact you actually have, not the one you read about.

## Thread identity

FACT. Three ids for one thread, and confusing them yields empty results rather than errors.

| Name | Where it appears |
|---|---|
| Alias | The number in `/direct/t/<id>/`, and `messaging_thread_key` in REST |
| Canonical fbid | `thread_v2_id` in REST, `thread_fbid` in thread-page HTML. This is what the paging query wants |
| Thread igid | `thread_id` in REST, a 128-bit number that is neither of the above |

Passing the alias where the canonical id belongs does not error. It returns nothing useful,
which is worse. The practical rule inherited is to always resolve before paging, and to record
which resolution path answered so a run log shows how the id was obtained.

Two resolution paths exist, HTML and a REST inbox fallback. The REST path is structurally more
durable because it has no `doc_id` to rotate.

## Session persistence

The Phase 1 stop condition is unchanged: authenticate, save the session to disk, kill the
process, reload, and make an authenticated call without re-authenticating.

Met 2026-09-21 by `probes/adopt_and_save.py` and `probes/reload_and_call.py`, three live requests
across two processes. The reload probe read no credential from `.env` at all, and the stored
`fb_dtsg` was accepted without a re-bootstrap, so the session file alone carried the call. The
session file is `engine/state/session.json`, gitignored under `state/`, written owner-only, 734
bytes. What the run does not establish is token lifetime: the stored token was 6.1 seconds old,
against an existing lower bound of 16 minutes. Rerunning the reload probe against an old session
file is the cheapest measurement of that, one request.

**This project reaches it the same way the prior project did, by not logging in.** Phase 1
adopts an existing browser session. Ruled 2026-09-20 in
[../../docs/decisions/ADR-0008-adopt-existing-browser-session.md](../../docs/decisions/ADR-0008-adopt-existing-browser-session.md).
That avoids password handling, avoids two-factor flows, and avoids the most detectable action
an automated client can take, in the phase with the least working code to diagnose a problem
with.

Automated authentication is a stated future goal, not a rejected option. When it arrives it
populates the same `Session` object through an additional constructor path. Nothing written now
may assume credentials always come from outside, and nothing written now may add a second
credential boundary.

One hard constraint comes with this route: `sessionid` is HttpOnly, so no page script can read
it. It has to be copied by hand from the browser's developer tools. Any approach claiming to
read it from page JavaScript is either wrong or is describing a browser extension with cookie
permissions. Dumpsta-App therefore needs a credential-entry flow rather than a login form.

The second constraint is that the engine cannot renew what it did not create. When the browser
session expires or the user logs out elsewhere, the engine detects the revocation and says so
plainly. It does not attempt recovery.

### Token lifetime is unmeasured

UNRESOLVED, inherited. The prior project bootstrapped once per process and reused tokens for the
whole run. The longest observed run was roughly 16 minutes over 306 requests with no
token-related failure. Whether `fb_dtsg` expires on a timescale that matters for a long-running
client is unknown. If a long session starts failing mid-way, re-bootstrapping is the first thing
to try.

This matters more for this project than it did for the prior one, because a desktop client stays
open for hours where an exporter ran for minutes.

## Challenge, checkpoint, and two-factor

Routine, not edge cases. The library surfaces them as first-class states, never as generic
errors.

**Checkpoints must be structurally non-retryable, not non-retryable by convention.** The prior
project marked its checkpoint error `fatal` and excluded it from the retry path in code,
reasoning that a comment saying "do not retry challenges" would not survive a refactor. Retrying
around a challenge is what escalates a soft block into a locked account.

**A false positive in that guard is itself a serious bug**, and this is the subtlest lesson
inherited. Because checkpoints are never retried, a guard that fires on innocent content does
not produce a warning, it makes the operation permanently unfinishable. The prior project's
guard scanned the first 4000 bytes of every response body for markers such as `/challenge/` and
`login_required`. A single serialised message was about 4734 bytes, so that window was user
content. A participant sending a message containing `/challenge/` would have aborted the run,
reported a challenge that never happened, and every resume would have aborted at the same page.

The fix, and the rule this project inherits: always scan the response URL and any `Location`
header, where user content cannot appear. Scan the body only when it is not a successful data
payload, since a real checkpoint never arrives inside one.

Note that this was found by reasoning about the guard, not by hitting it. Zero of 6115 real
messages contained a marker string.

**Server-initiated logout.** An empty `Set-Cookie` value is how a server expires a cookie.
Treating it as noise means continuing to make requests with a credential the server has already
revoked. Clearing a required cookie must raise.

**Two-factor** arrives with the deferred login work, and when it does it must not block waiting
for input. A blocking
prompt inside the library would deadlock the Swift UI. The caller supplies the second factor
through a dedicated call. See
[../../docs/bridge/threading-and-gil.md](../../docs/bridge/threading-and-gil.md).

## Credential handling

Inherited as a requirement, because the prior project demonstrated both the right practice and a
real leak.

- Credentials come from the environment or a local file with restrictive permissions. A session
  cookie is a full account takeover token with no second factor, so a world-readable credentials
  file is a defect, not a style preference.
- Secrets are redacted in logs and never written into exported data.
- Redaction is verified by scanning for the live values with a positive control, not by reading
  the code. The prior project's scan found zero hits in logs, exports, and state, and was only
  meaningful because the same grep demonstrably found those values in the credentials file.
- That same audit caught a different leak: a diagnostic tool was writing real message bodies
  into a directory outside the ignore list. Error envelopes were kept verbatim, since they carry
  no user content.

Data handling for message content itself is covered in
[../../docs/knowledge/risks-and-constraints.md](../../docs/knowledge/risks-and-constraints.md).

## What Phase 1 deliberately excludes

No features. The temptation to add one endpoint to prove the transport works should be resolved
with a throwaway script, not a committed capability, because a capability written before the
model layer exists will not have a typed boundary.
