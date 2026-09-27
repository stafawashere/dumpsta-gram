# Web parity plan, 1.1.0 to 1.6.0

Written 2026-09-23, after `1.0.0` was cut. Approved the same day: the owner delegated every open
decision, and the rulings are in the Decisions section below. It plans the engine phases whose
end state is an engine that can back a site behaving like instagram.com for a signed-in user.
[roadmap.md](roadmap.md) stays the canonical definition of Phases 1 to 6, and nothing here
reopens a locked decision.

The phases are named E1 to E6 so they do not collide with the roadmap's Phase 5 (the Swift app)
and Phase 6 (push transport). E4 absorbs Phase 6. Since 2026-09-27 the owner has a second
account, account B (W49), so every item that needs a second account the owner controls sits in
the phase it belongs to, and E6 keeps only what needs a third account (W51). Each phase ships as one
additive minor release under ADR-0011, so the Swift app can be built against `1.0.0` in parallel
and never sees a removed or changed line.

## Audit of the engine at 1.0.0

Checked in this session, 2026-09-23, from a clean tree at `9b813e6` plus the untracked
`docs/demo.py`:

| Check | Result |
|---|---|
| `uv run pytest` | `682 passed in 10.54s`, log `engine/logs/pytest-2026-09-23-182918.log` |
| `uv run mypy` | `Success: no issues found in 57 source files` |
| `uv run ruff check` and `ruff format --check` | `All checks passed!`, `158 files already formatted` |
| `check_provenance.py` | `provenance: ok, every endpoint literal is backed by a verified finding` |

The mutation harnesses were not rerun in this session. Their last recorded results are in
[engineering/project-profile.md](engineering/project-profile.md).

**What exists.** FACT. Six reads (`thread_messages`, `profile`, `profile_by_id`, `feed`, `notes`,
`post`, `comments`, counting the profile pair as one read), ten writes in five reversible pairs
(like, comment, note, follow, direct text), and `events()` on inbox polling at 60 s. The public
surface is 397 lines. The knowledge base holds 46 verified findings and 4 hypotheses, about 30 of
them persisted query documents in `_private/web/documents.py`.

**Coverage against the website.** INFERENCE, from the feature inventory in the phases below. The
website offers roughly 150 distinct user actions. The engine covers 16, about 10 percent. Nothing
yet measures the denominator, which is the first thing E1 fixes. Measured since by E1 item 2:
265 compiled operations, a lower bound, of which 20 back a capability, in
[coverage.md](coverage.md).

**Findings that shape the plan.**

1. The structure will not scale to fifteen times the capabilities. `_private/web/requests.py` is
   1244 lines, `_private/web/parse.py` 1468 and `_cli/main.py` 1350, each holding every domain.
   `aio.py` (817 lines) and `client.py` (408) are hand-kept twins with 24 async methods, held in
   step by `tests/test_facade_parity.py`. At 150 methods a flat client is hard to read and every
   capability costs four files of boilerplate.
2. `doc_id` rotation is the dominant maintenance cost as the count grows. Two rotations were
   already observed (`PolarisProfilePostsQuery` and the feed pagination query), both while the
   old id still answered. With 150 operations, rotation becomes weekly work unless it is detected
   mechanically.
3. The media model is image only. `MediaImage` carries crops of a single image. There is no video,
   no carousel child, no audio, and no way to download a rendition. A clone cannot render a reel.
4. Pacing state is per process. The write budget and the write stop reset with each `dumpsta`
   invocation, which is a recorded 1.0.0 limitation and a real gap for a long-lived server.
   Closed by E1 item 8 for clients built from a session file.
5. Every write so far runs on the owner's only account. Group threads, blocking, restricting,
   removing a follower and follow request handling each need a second or third account that the
   owner controls. Those items are collected in E6, so nothing before it waits on another account.
6. Seven recorded parity departures, each an action sent alone rather than inside its page load.
   The inbox load and the post page document are the two missing page models behind most of them.
7. An unexplained key-shaped comment, four dash-separated groups of five characters, sits at
   `dumpstagram/_private/web/bootstrap.py:134` and therefore ships in the 1.0.0 wheel. The
   overnight handoff raised it and it is still there. Resolved in E1 under W4: the line is
   removed and its text is no longer quoted in the engine's documents.
8. Seven gates fail from an unpacked sdist because they read git. Recorded, not blocking.

## What 1:1 with the website can and cannot mean

A site built on the engine can match instagram.com for everything the web client does over HTTP
and its realtime socket, for a user who supplies their own session. Three limits hold regardless
of effort:

- Video and audio calls run over WebRTC to Meta's media servers. Out of scope, since the engine
  would have to be a media stack.
- Payments, shopping checkout, Meta Verified and the Accounts Center span other Meta properties.
  Out of scope unless a phase is added for them.
- A site serving other people runs each person's own session through this engine. Every user of
  such a site carries the ToS and ban risk in
  [../../docs/knowledge/risks-and-constraints.md](../../docs/knowledge/risks-and-constraints.md),
  and the parity defaults are the main protection they have.


## Decisions

Ruled 2026-09-23 by the orchestrator on the owner's delegation ("make every decision for me").
Numbered W1 onward so they do not collide with the build plan's rulings in 17.13.

- **W1. New capabilities go on domain namespaces.** `client.direct`, `client.feed`, `client.media`,
  `client.profiles`, `client.social`, `client.stories`, `client.search`, `client.notes`,
  `client.account`, each a small object on both facades. The 24 flat methods stay forever under
  SemVer and gain namespace aliases in E1, so there is one consistent way to call everything and
  the flat names are the compatibility path. Reason: at 150 methods a flat client is unreadable,
  and namespaces are purely additive. `tests/test_facade_parity.py` extends to walk namespaces.
  The names `feed` and `notes` were taken by flat methods, see W19.
- **W2. The facades stay hand-written, not generated.** The owner chose the parity gate over a
  generated facade on 2026-09-22, and nothing since changes that.
- **W3. Push transport comes before the Swift app in engine order.** No app work is in flight, the
  `events()` surface does not change, and push returns the poll budget. The app still may start
  at any time against `1.0.0`.
- **W4. The `bootstrap.py:134` comment is removed as E1's first commit.** It has no reference
  anywhere, came in with `ec7b338`, and reads like a product key. It is already in public git
  history, so if it is a real key the owner should treat it as exposed. Removal is a patch.
- **W5. Reporting is left out.** A report sent during acceptance harms a real account, and nothing
  a clone needs depends on it.
- **W6. Viewing a story marks it seen by default**, because a browser does, with
  `Behavior.mark_stories_seen` as the named departure. The same rule applies to mark read on a
  thread the engine opens.
- **W7. Username change, own-account login and anything that locks the owner out wait for E6** and
  run on the second account. A changed username can be taken by someone else in the gap, and a
  login from a new device is the likeliest checkpoint trigger on the only account.
- **W8. The direct message target named in ruling 30 is the only other person E1 to E5 touch**,
  and only in the one-to-one thread that already exists. Nothing else visible to another person is
  run before E6.
- **W9. Group threads need three participants.** E6 runs them with the owner, the second account
  and a third account. If no third account exists, groups stay deferred rather than borrowing the
  ruling 30 target.

Rulings from W10 on were made by the orchestrator on the owner's delegation while E1 ran.

- **W10. The poller reads a known thread back with `newer_than_message_id`, and keeps its
  bounds.** Ruled 2026-09-23 for E1 item 1. When a listed thread's newest message id moves,
  the read back sends the thread's last known message id as `newer_than_message_id` on every
  page, the first with `after` null and each later one with the previous page's cursor.
  Evidence: finding `direct-thread-older-page-offmsys`, whose fifth pass
  (`run-2026-09-23-185004`, `probes/newer_than_pages.py`, four requests) had a live base with
  24 newer messages answer the newest 20 with `has_next_page` true, then after that cursor
  with the same base the remaining 4 with `has_next_page` false and never the base itself. So
  the filter pages newest first at 20 a page, exactly as the unfiltered read did, and a thread
  that gained more than 60 messages still needs a bound. The three-page cap and the
  `EventsDropped(count=None, thread_fbid=...)` marker therefore stay, and pagination still
  ends only on `has_next_page` or the cap. The client-side stops at the known message and at
  the known time also stay: with the filter honoured they never fire, and if the upstream
  ever ignores the variable they keep the read correct rather than delivering history. The
  `since` catch-up on a first poll sends no base, because the watermark belongs to one thread
  and a base from another thread has never been sent, and a thread new to the first page
  sends none because nothing in it is known. Cost is unchanged in requests and smaller in
  bytes: the four-message filtered page of that pass was 8718 bytes, a full page 39825.
- **W11. The key-shaped text is gone from the documents too.** W4 removed the comment. Its
  literal text also stood in audit finding 7 above and in the 2026-09-23 overnight handoff,
  which kept it discoverable in the tree, so both now describe it instead of quoting it. The
  history of the finding is otherwise unchanged.
- **W12. The census stays local, and a committed summary carries its numbers.** Ruled
  2026-09-23 for E1 item 2. `skills/` is never committed, so the census lives at
  `skills/reverse-engineer/knowledge/census.md` as this plan says, and
  [coverage.md](coverage.md) is committed beside this plan with, per page type, the count of
  operations and the count the engine covers, the per phase counts, and the overall share
  covered as a number, with no `doc_id` literal in it. That file is the denominator later phases
  scope from. The unit is a compiled Relay operation with a `doc_id`. An operation counts as
  covered when it backs a public capability; the ten page load companions the engine sends are
  shown beside that count, not inside it. An alternate compiled route of an action already
  shipped is excluded rather than counted as a gap, since a clone needs one route per action.
- **W13. Logging out moves to E6, and nothing planned for E2 to E5 had to move.** Ruled
  2026-09-23 from the census. The settings bundle compiles a logout mutation. Ending the
  session on the only account is the lockout W7 already sends to E6, so it runs on the second
  account. The census found six more operations that need another account, and each already
  sits in E6: replying to another account's story, liking and unliking a story, creating a group
  thread, unrestricting, and approving a restricted account's comment, which goes with restrict.
  No story create operation was compiled on any load, so whether the web client can post a story
  (E3) is still open and needs a scout of the composer.
- **W14. Three page types are read from another load's bundle rather than a load of their
  own.** Ruled 2026-09-23 to fit fifteen page types into the thirteen load budget without
  anything visible to another person. Thread is the inbox bundle: a thread load and an inbox
  load parsed the identical 618 module set in `run-2026-09-23-042538`, and this run's inbox load
  parsed the same 618, so no thread was opened and nothing was marked seen. Search is the explore
  and home bundles, which carry the search box and recent search operations; opening the Search
  control parsed nothing new and no query was typed. Stories is the viewer family compiled into
  home, because the owner has no live story and the own story URL redirected to home; no other
  account's story was opened.

- **W15. Every importer names the domain module, and no package `__init__.py` re-exports.**
  Ruled 2026-09-23 by the orchestrator on the owner's delegation, for E1 item 3. The step allowed
  either re-exporting packages or updating every importer, and asked for whichever keeps
  `tests/test_import_boundary.py` meaningful. That gate reads import edges from source. With
  direct imports each edge names the module a name is defined in, so which domain of `_private`
  a `_core` capability depends on stays readable from the edges, and a later rule such as "a
  domain module imports only `common`" can be written against them. Re-exports would collapse
  every edge onto the package and make each `__init__.py` a second list of names to keep in
  step. The cost was mechanical: 40 importers across `dumpstagram/`, `tests/` and `probes/`, and
  one gate, `test_every_query_on_the_graphql_query_path_names_its_root_field`, which walked
  `vars(documents)` and now walks every module of the `documents` package with
  `pkgutil.iter_modules`, the same set of queries as before.
- **W16. What goes where, where no W1 namespace fits.** Ruled 2026-09-23 for E1 item 3. Likes and
  comments are `media`, since they act on a post, and follows are `social`. Modules exist only for
  domains with code today, so there is no `stories`, `search` or `account` module yet. Shared
  helpers are `common.py` in each package: `build_graphql_request` and the id patterns two
  domains share in `requests/`, the required and optional readers in `parse/`, `PersistedQuery`
  and both paths in `documents/`, and in `_cli/commands/` the `Client` protocol, the session path
  and the request options. Three modules are named for what they are because they belong to no
  domain: `page_load.py` in `documents/` and `requests/` for the page load companions and the
  cookie sync's `fr` exchange, mirroring `_core/page_load.py`, and `session.py` and `events.py`
  in `_cli/commands/` and `_cli/render/`. `build_parser` stays in `_cli/main.py` and calls one
  registrar per command group in the order the commands were always added, so `dumpsta --help`
  lists them as before, and `main` keeps the dispatch.
- **W17. Gates changed only to follow the move, each one checked.** Ruled 2026-09-23 for E1
  item 3. Every harness anchor that pointed into a split file now names the new file, 186
  mutations in 17 harnesses, each found exactly once there, the replacement text unchanged but for what follows. Five
  replacements named something their old module had in scope and their new one does not, which
  would have turned the gate red through a `NameError` rather than through the defect, so each
  gained what brings the name back, an import edit beside it in `verify_notes_gates.py` (three)
  and `verify_inbox_gates.py` (one), and a local import inside the replacement in
  `verify_feed_gates.py`, whose harness takes one edit per mutation. A check that applied every
  moved mutation to its old and new file found the same undefined names before and after, none
  added. `tests/test_cli.py::test_the_cli_reaches_no_capability_module_directly` read `_cli/`
  with a flat glob, which the commands moving into `_cli/commands/` would have silently escaped:
  a `_private` import planted in `_cli/commands/media.py` passed under the flat glob and failed
  under the recursive one, which it now uses. `check_provenance.py` compared a query's `url`
  only against constants of its own module, so `HOME_TIMELINE_FEED` and `PROFILE_POSTS` naming
  `GRAPHQL_QUERY_URL` from `documents/common.py` reported `mismatch on url`. It now also resolves
  a constant imported by name from another scanned module, one level, with an import fixture in
  its positive control, two scanner mutations and one injection in
  `verify_provenance_controls.py`, which also now refuses an injection into a file that does
  not exist, since two of its injections named `parse.py` and would otherwise have created it.
  One weakness predates the split and is left for the owner: `verify_feed_gates.py`'s
  length-heuristic mutation names `FEED_PAGE_SIZE_GUESS`, which no module defines, so its gate
  goes red on a `NameError`, before the split as after.
- **W18. `aio.py` stays whole until item 4.** Ruled 2026-09-23 for E1 item 3. The step named four
  files, and `_cli/render.py` at 561 lines was split with them because the stop condition allows
  no module over about 500 lines where a domain split is possible. `aio.py` at 817 lines is the
  one left: it is the public facade, and item 4's namespace objects are where its per-domain
  split belongs, so doing it here would be done twice.
- **W19. Two W1 names were taken, so the timelines are `client.feeds` and the notes live on
  `client.direct`.** Ruled 2026-09-23 by the orchestrator on the owner's delegation, for E1
  item 4. `feed` and `notes` are flat methods of `1.0.0`, and their lines
  `def dumpstagram.aio.AsyncClient.feed(...)` and `...notes(...)` are in the Phase 3 baseline, so
  a namespace property under either name would change a frozen line, which ADR-0011 forbids.
  The timelines take the plural, `client.feeds`, the way `profiles` already is. The notes join
  `client.direct` rather than take a second invented name, because the web client shows the tray
  on the direct inbox and a reply to a note arrives as a direct message. The shipped namespaces
  are therefore `direct`, `feeds`, `media`, `profiles` and `social`. Inside a namespace a name
  drops the word the namespace already says (`direct.send`, not `direct.send_message`), keeps the
  object where it is not the domain (`media.delete_comment`, `direct.set_note`), and a read keyed
  on a lookup value is `by_<key>`. `post` became `media.by_code`, because `media.post` reads as
  publishing, which E1 item 9 adds. Every alias takes exactly its flat twin's parameters, same
  names, order, kinds and defaults, and returns the same type. The whole table:

  | Flat method, both clients | Namespace alias |
  |---|---|
  | `thread_messages(thread_fbid, *, after, newer_than_message_id)` | `direct.messages` |
  | `send_message(thread_fbid, text)` | `direct.send` |
  | `unsend_message(thread_fbid, message_id)` | `direct.unsend` |
  | `notes()` | `direct.notes` |
  | `set_note(text, *, audience)` | `direct.set_note` |
  | `delete_note(note_id)` | `direct.delete_note` |
  | `feed(*, after)` | `feeds.home` |
  | `post(code)` | `media.by_code` |
  | `like(post_pk)` | `media.like` |
  | `unlike(post_pk)` | `media.unlike` |
  | `comments(post_pk, *, after)` | `media.comments` |
  | `comment(post_pk, text)` | `media.comment` |
  | `delete_comment(post_pk, comment_id)` | `media.delete_comment` |
  | `profile(username)` | `profiles.by_username` |
  | `profile_by_id(user_id)` | `profiles.by_id` |
  | `follow(user_id)` | `social.follow` |
  | `unfollow(user_id)` | `social.unfollow` |

- **W20. No empty namespace ships, and `events` stays on the client.** Ruled 2026-09-23 for E1
  item 4. `stories`, `search` and `account` have no capability yet, and each arrives with its
  first method. An empty public class is a snapshot line whose shape, and whose name, nothing
  has tested yet: W13 already found that a planned account action belongs to a second account,
  and a renamed namespace after it shipped would be a removal. `events` gets no alias. It is the
  account's one event stream under ADR-0006, whose kinds are expected to grow past direct
  messages when push arrives, and a listener is a lifetime rather than a read of one domain.
- **W21. The namespace is where a capability lives, and the flat method answers through it.**
  Ruled 2026-09-23 for E1 item 4. The plan's 24 counted every `async def` in `aio.py`, which
  includes `aclose`, `__aenter__`, `__aexit__`, `events` and two private helpers. The flat
  capabilities are 17, and each has one alias. Each namespace method holds the full docstring
  and the one `_core` call, and each flat method is a one-line delegation to its alias with a
  short docstring naming it. The two flat docstrings a gate holds, `set_note` and `comment`, keep
  the reconciling read and `OutcomeUnknown`. `aio.py` went from 817 lines to 479, which closes
  W18. The classes live in `dumpstagram/namespaces/<domain>.py`, the awaitable one beside its
  blocking twin, and are built by a private `_of` with an `__init__` that raises, as
  `EventListener` is. Each property builds a fresh namespace object on access, which holds only
  its client, so a client from `with_behavior` needs nothing copied. Nothing is re-exported from
  `dumpstagram.namespaces` or the root, and a root export can be added later without removing
  anything. One consequence shaped the gates. Since a flat method answers through its alias, an
  alias that reaches the wrong `_core` function makes both answer the same wrong way, and the
  flat-against-alias gate cannot see it. So `tests/test_facade_parity.py` also holds each
  namespace method to the `_core` function a table in the file names.
- **W22. Gates followed the move, and two were strengthened.** Ruled 2026-09-23 for E1 item 4.
  Twelve anchors in eight harnesses pointed at `aio.py` text that moved to a namespace module,
  and each now names that module, found exactly once, with the replacement text changed only
  from `self.` to `client.` where the moved code changed it: `verify_cookie_sync_gates.py` (1),
  `verify_feed_first_page_gates.py` (2), `verify_page_load_gates.py` (2),
  `verify_profile_page_gates.py` (1), `verify_thread_route_gates.py` (1),
  `verify_phase2_gates.py` (1, lengthened by one line, because the shorter text now occurs twice
  in `namespaces/direct.py`), `verify_notes_gates.py` (2) and `verify_comments_gates.py` (2).
  `tests/test_direct.py` spied on `aio.read_thread_messages` in three gates, and now spies on
  `dumpstagram.namespaces.direct.read_thread_messages`, the one module that calls it. The
  `set_note` and `comment` docstring gates now hold the flat method and the alias both, each
  with a new mutation on the flat docstring. The length-heuristic mutation in
  `verify_feed_gates.py` that W17 left named `FEED_PAGE_SIZE_GUESS`, which no module defines,
  and turned its gate red on a `NameError`. It now compares against a literal 12, and the gate
  goes red on `AssertionError: assert False is True` for `has_next_page`, seen before and after
  the fix.
- **W23. An iterator's `limit` is required, counts items, and `None` is the explicit way to read
  to the end.** Ruled 2026-09-23 by the orchestrator on the owner's delegation, for E1 item 5.
  Every `iter_*` takes `limit: int | None` keyword-only with no default. A default of `None`
  would make the home timeline, which has never been seen to end, a request loop by omission,
  and a default number would truncate silently, the defect the pagination invariant exists to
  prevent, so the caller writes the choice down. It counts items, not pages, because a page's
  length is the upstream's decision (feed pages of 14, 12 and 5 for the same request) and a
  page count would hand back an unpredictable number of items. Counting items also bounds the
  cost: the walk stops as soon as the limit-th item is yielded and never reads a page it would
  not use, so `limit=0` reads nothing. A caller who thinks in pages has the page method.
  A negative limit raises `ValueError` and a non-integer `TypeError`, both when the iterator is
  made rather than on the first item. Each iterator also takes its read's other parameters with
  the same defaults, so `after` starts a walk from a cursor and `iter_messages` sends
  `newer_than_message_id` on every page, as the poller does under W10. A page that says more
  exist with no cursor raises `SchemaChanged` rather than ending the walk or asking for the
  first page again. Not guarded: a cursor the upstream repeats while `has_next_page` stays true
  would be followed until the limit, and a `None` limit would not stop it. It has not been
  observed, and guarding it would be a terminator other than `has_next_page`.
- **W24. The iterators live on the namespaces only, one per paged read.** Ruled 2026-09-23 for
  E1 item 5. W1 puts new capabilities on the namespaces, and a flat `iter_thread_messages` beside
  `client.direct.iter_messages` would be two new names for one thing, each a frozen snapshot
  line, so no flat `iter_*` ships and one can be added later without removing anything. The
  three paged reads are `direct.messages`, `feeds.home` and `media.comments`, found by a gate
  that lists every namespace read returning a `Page`, so the companions are
  `direct.iter_messages`, `feeds.iter_home` and `media.iter_comments`. `notes` is a tuple and not
  a `Page`. The awaitable iterator is a plain method returning an `AsyncIterator`, not a
  coroutine and not an async generator function, so `async for` takes it without `await` and the
  limit is checked at the call. The blocking one is a generator that runs each page read on the
  loop thread with a seam note naming the iterator, and reads nothing ahead, so closing it early
  leaves no task on the loop and nothing to cancel. The walk itself is `PageWalk` in
  `_core/paging.py`, shared by both surfaces, and each page goes through the namespace's own
  page read, so it is paced, bootstrapped, checkpoint-watched and companion-carrying exactly as a
  single read is. No CLI flag was added, because `--pages` already walks a read from the command
  line.
- **W25. The parity gates split on the `iter_` prefix, and the discovery control grew.** Ruled
  2026-09-23 for E1 item 5. `tests/test_facade_parity.py` held every namespace method to being a
  coroutine, which an iterator is not. The coroutine gates now walk the namespace methods whose
  name does not start with `iter_`, so a page read that stopped being a coroutine still fails,
  and new gates hold the rest against `PAGE_METHOD_FOR_ITERATOR`. The discovery control now
  compares every namespace method against the snapshot, iterators included, demands at least one
  iterator, and demands the two sets cover the whole, so it checks strictly more than before.
  No existing gate was loosened, and the iterator mutations live in the new
  `scripts/verify_iterator_gates.py`.
- **W26. A CDN fetch takes no pacer slot, and one download is one fetch.** Ruled 2026-09-23 by
  the orchestrator on the owner's delegation, for E1 item 6. ADR-0001 names media and CDN
  fetches as not API traffic and not subject to the API pacer, and nothing in the engine's
  documents says a CDN fetch must be paced, so `client.media.download` sends through a pool of
  its own and never asks the account's pacer for a slot. The pacer's numbers were measured on
  the API gateway, and a browser fetches a page's media from the CDN in parallel with its API
  calls, so pacing a download would make the engine slower than the browser it imitates and
  would serialize downloads behind reads for nothing. Concurrency is bounded instead by the
  pool: four connections per client, the concurrency the prior project's browser script used.
  A gate holds a download to never touching the pacer. The risk left open is recorded in
  [rate-limiting-and-safety.md](rate-limiting-and-safety.md): whether CDN bursts far past a
  browser's are scored against an account is unmeasured.
- **W27. The CDN pin is the `cdninstagram.com` family over `https`, and the provenance gate
  backs a family by an observed host under it.** Ruled 2026-09-23 for E1 item 6. Every rendition
  URL on seven feed pages and two post reads sat on a subdomain of `cdninstagram.com`, one host
  per point of presence (`scontent-lga3-1`, `-2` and `-3` were fetched), so no single host can be
  pinned. `HttpxTransport` gained `allowed_host_family`, a second hook beside the one-host pin
  rather than a loosening of it: a host passes only as a subdomain at a label boundary and only
  over `https`, a transport takes one pin or the other, and the one-host pin's code and gates
  are unchanged. `fbcdn.net` appeared only as music cover artwork, 6 URLs in all, and was never
  fetched, so it is not in the pin. `check_provenance.py` compared a host literal only against a
  finding's exact host, which a family literal can never equal. It now also backs a literal that
  an observed host of a verified finding sits under at a label boundary, so `"cdninstagram.com"`
  is backed by `scontent-lga3-3.cdninstagram.com` and `"ninstagram.com"` is not. That widens
  what the gate accepts, and only to domains with a verified observation under them. Its host
  fixture gained a backed family and an unbacked partial label, and
  `verify_provenance_controls.py` gained two scanner mutations (no label boundary, no family
  backing) and two injections (an unobserved family, a partial label of the observed one), all
  of which fired. `skills/` is local, so this change is not in the repository.
- **W28. The media model follows the payload, and names what it does not carry.** Ruled
  2026-09-23 for E1 item 6, from `probes/media_shape.py`: eleven reels, seven carousels and
  thirty-one slides counted over seven timeline page reads, the first page read twice so a node
  may be counted twice, and one reel and one carousel read again through the post
  query. Renditions are `Post.videos`, beside `images`, as `VideoRendition` with the upstream's
  `type` passed through as `version_type`, because the three per reel share one size and nothing
  says which is better. The payload has no duration field, so `video_duration` is read from the
  `mediaPresentationDuration` on the root of `video_dash_manifest`, with a pattern over the root
  tag rather than an XML parser, and a video without it raises `SchemaChanged`. The manifest
  itself is not exposed. Audio is `MediaAudio` from whichever of `music_info` and
  `original_sound_info` is filled; both filled raises, both null is `None`, unobserved. There is
  no audio download, because the track is inside the video. Slides are `CarouselChild` with
  their own kind, and read no `has_audio`, because the post query's slides do not carry the key.
  `PostDetail` gained the same five fields, because the post query's item carried the same keys
  on both reads. Music cover artwork and an original sound's account picture are dropped. Every
  field is additive with a default, and the snapshot grew from 473 lines to 520, none removed or
  changed.
  One existing mutation anchor followed the code: `verify_feed_gates.py`'s keep-one-crop
  mutation named the end of `_images` by the `_post_author` definition after it, which the new
  mappers now separate, so it names `MANIFEST_ROOT` instead, found once, the replacement
  unchanged but for that line.
- **W29. A download is atomic, refuses to overwrite, checks the length it was told, and never
  follows a redirect.** Ruled 2026-09-23 for E1 item 6.
  `client.media.download(rendition, path, *, overwrite=False) -> Path`, on the namespace only
  (W1, W24). The body streams undecoded to a `mkstemp` file beside the destination and is hard
  linked into place, so a name taken while the body arrived is not replaced, with a rename after
  a second check on a file system without hard links. `overwrite=True` renames over. A
  `content-length` is compared with the bytes received where one is sent, and one live fetch sent
  none, so its absence is accepted. A `content-encoding` other than identity, a body over 2 GiB,
  and a status other than 200 are refused: a 4xx as `NotFound`, since a signed URL is expected to
  expire (INFERENCE), and anything else as `TransportFailure`. Local file errors are the builtin
  `OSError` family, `FileExistsError` for a refused overwrite, because they concern the caller's
  disk. The destination is the caller's full path, not a name derived from upstream data, so the
  path rule in `engineering/08-security-and-trust-boundaries.md` has nothing to resolve.
- **W30. A second person for direct messages and follows, named by the owner.** Ruled by the
  owner on 2026-09-23, recorded by the orchestrator. The owner named one further account as a
  test partner for direct messages, follows and similar two-person tests. It is read from
  `IG_BUDDY_TARGET` in the root `.env` and is never named in a committed file, a log or a
  commit message, like the ruling 30 target. It is another person, not an account the owner
  controls, and he replies to messages sent to him, sometimes late. This widens W8: from E4 on,
  message kinds, reactions, edits and unsends may run in a one-to-one thread with him, a new
  one-to-one thread may be opened with him from his profile, and a follow and unfollow may run
  on his account, each restored in the same run under ruling 24. No acceptance may depend on a
  timely reply. Events only he can cause, such as his reply, reaction or seen state, are
  observed when they arrive, in a later run if need be, and an item whose acceptance needs him to
  act on cue, such as accepting a follow request, stays in E6. Group threads still need a third
  account under W9.
- **W31. The canary reads doc_ids from the bundles the page documents name, over plain HTTP.** Ruled
  2026-09-23 by the orchestrator on the owner's delegation, for E1 item 7. ADR-0003 rules out the
  browser the census used, so `dumpsta doctor` loads the two documents the engine already loads, the
  inbox page the bootstrap reads and home, and collects every `.js` bundle on
  `static.cdninstagram.com` they name, plainly in script and preload tags and with escaped slashes
  in the bootloader's `rsrcMap` (541 on the home document of 2026-09-23, of which a cold load
  fetched 66). Each bundle is read for the module `<Operation>_instagramRelayOperation`, whose body
  exports the operation's `doc_id`, and nothing is evaluated. The scan runs in document order and
  stops as soon as every stored operation is found, capped at 1000 bundles unless `--bundle-limit`
  says fewer. Bundles are static, public and immutable, so they go through a third cookieless
  transport pinned to that host and, like a CDN download under W26, take no pacer slot. Per
  operation the verdict is `ok` when the bundles compile exactly the stored id, `drift` with every
  compiled id when they compile another, and `missing` when no scanned bundle compiles it. Missing
  is not drift: the census found five engine operations only in lazy chunks, which no document
  names, so they will read `missing` on every run. The command exits 12 on any drift, 13 when
  nothing drifted but a replay failed, and 0 otherwise. The host literal is backed by the finding
  `static-js-bundle-fetch`, verified twice from the two recorded browser captures of 2026-09-23 as
  browser observations, not replays, the precedent the cookie sync findings set;
  `probes/doctor_bundle_host.py` made the first engine fetch on 2026-09-24, verifying the finding a
  third time. The module shape rests
  on one id module recorded whole and two artifacts, recorded as the pattern
  `a-bundle-exports-each-operation-s-doc-id-from-its-own-module`. `skills/` is local, so neither is
  in the repository.
- **W32. The canary replays the ten capability reads once each, and sends nothing else.** Ruled
  2026-09-23 by the orchestrator on the owner's delegation, for E1 item 7. "Each verified read
  finding" is read as the ten queries whose answers a capability reads: the inbox listing, the notes
  tray, the thread open, both thread page queries, the timeline, the post, its comment page, the
  profile by id and the profile posts. Each is built with its capability's own request builder and
  read with its own mapper, so a replay passes only when the capability would still get an answer it
  can map. Arguments come from earlier replays, never from the caller: the first inbox thread, the
  first timeline post, the viewer's own `ds_user_id` and the username its profile carries, and a
  read whose argument never turned up is `skipped` and not sent. The ten page load and profile
  companions, whose answers nothing reads, and the ten writes are compared with the bundle only. A
  write is never built, and a gate fails on any write reaching the fake site. Every replay is one
  paced send, with no retry and no token recovery, so a run costs the two documents and at most ten
  reads. A checkpoint ends the run at once, and any other classified failure is reported with its
  class and code while the run goes on. The command is a dry run by default that prints what it
  would send and opens nothing, and `--live` prints the same count on stderr before the first
  request.
- **W33. The canary is private, reached through one assembly function, and no gate moved.** Ruled
  2026-09-23 by the orchestrator on the owner's delegation, for E1 item 7. It reads the private
  query registry, and ADR-0007 keeps GraphQL shapes off the public surface, so it is not a client
  method and the snapshot is unchanged. The logic is `RotationDoctor` in `_core/doctor.py`, the
  surface knowledge is in `_private/web/bundles.py` and `_private/web/canary.py`, and
  `_private/web/documents/catalog.py` sorts the thirty registry queries into reads, companions and
  writes. `tests/test_cli.py` holds the command to importing nothing from `_core` or `_private` but
  redaction, and `tests/test_import_boundary.py` lets only `aio.py` import `_private` from outside
  `_core`, so the command reaches the canary through `_rotation_doctor` and `_rotation_doctor_plan`
  in `aio.py`, which also builds the bundle transport, and neither gate was changed. A gate holds
  the catalog to every `PersistedQuery` in the domain modules exactly once, so a query added by
  posting cannot go unchecked by omission. `tests/test_doctor.py` holds 17 gates, 21 cases, and each
  but the positive control for drift and missing was seen red under the 24 mutations of
  `scripts/verify_doctor_gates.py`, then green.
- **W34. The pacing ledger sits beside the session file and only a file-built client keeps
  one.** Ruled 2026-09-23 by the orchestrator on the owner's delegation, for E1 item 8.
  `from_session_file(path)` on both clients keeps the write budget and the write stop in
  `<path>.ledger`, locked through `<path>.ledger.lock`. A client built over a bare `Session`
  keeps them in memory as before, because it has no file to sit beside and the step asked for
  that. The session file's schema is unchanged, since a sibling file needs no migration and an
  older engine reading a newer session file would otherwise refuse it. No `Behavior` setting
  was added: persisting the record changes nothing the upstream sees, so it is not an ADR-0013
  departure, and a caller who wants a private budget builds the client over a `Session`. The
  ledger lives in `_core/ledger.py`, and W36 adds the one public name. The file holds the
  wall clock instants of the last hour's write departures, `writes_stopped` and `stopped_at`,
  and nothing else, so no credential, id or content. Wall clock because a monotonic reading
  means nothing to another process. A memory ledger stays on the pacer's clock, which is what
  the fake clock in the tests drives. Write spacing, read spacing and throttle holds stay per
  process, so two processes can write closer together than the write floor, and the budget
  still bounds them.
- **W35. Every access is locked, atomic and read afresh, and an unreadable ledger refuses
  writes.** Ruled 2026-09-23 for E1 item 8. Each read and write holds an exclusive `flock` on
  the lock file from the read to the rename, and the record is written to a temporary file,
  synced and renamed over the old one, so a crash leaves one whole record. The lock file is
  separate because a rename replaces the inode another process would be holding a lock on.
  `fcntl` is POSIX, so Windows is out of scope under ADR-0010. A write judges the record twice,
  both times read afresh: before it waits out its spacing, and after, where the same locked
  update records its departure, so two processes cannot both take the last slot. File access
  goes through `asyncio.to_thread`, because the lock can wait on another process and the loop
  must not. A ledger that is not JSON, not a write record, or of another `schema_version`
  refuses every write with `UpstreamRejected(code="writes_stopped")` and is never rewritten,
  because a reset would forget a stop it may hold. A stop is written as soon as the rejection is
  recorded. If that write fails the stop still holds in the process and a warning is logged.
- **W36. Only a person lifts a stop, and lifting it keeps the budget.** Ruled 2026-09-23 for E1
  item 8. The stop never lapses with the window or with a restart. `dumpsta session
  --clear-write-stop` clears it and keeps the hour's departures, so lifting a stop never also
  hands back an hour's writes, and on an unreadable ledger it changes nothing and exits 8,
  `SchemaChanged`. Deleting the ledger lifts the stop and forgets the departures, which is the
  recovery for an unreadable one. The flag sits on the existing `session` command rather than a
  new command, so the CLI gains no command. The CLI may not reach `_core`, a gate in
  `tests/test_cli.py`, and the Swift app must never learn the ledger's format, so the lift is
  public: `dumpstagram.session.clear_write_stop(path) -> bool`, one snapshot line, a plain
  function because it needs no client, no loop and no request. It is not re-exported from the
  package root, which keeps `dumpstagram/__init__.py` out of this change. Its docstring says it
  is a person's decision after looking at the account. The gates are fourteen in `tests/test_pacing_ledger.py`, six of them
  across real interpreters, each red under one of the 16 mutations of the new
  `scripts/verify_ledger_gates.py`. Two write safety anchors followed the code:
  `_refuse_past_the_budget` now takes the record and the instant, and the stop check reads
  `account_is_stopped`.
- **W37. Posting lives on `client.media` as three methods, and a publish returns what its
  answer carries.** Ruled 2026-09-23 by the orchestrator on the owner's delegation, for E1
  item 9. `media.publish_photo(image, *, caption="")`, `media.publish_carousel(images, *,
  caption="")` and `media.delete_post(post_pk, code)`, on both clients, with no flat twin (W1,
  W24). W19 kept `post` off the namespace because it reads as publishing, and `publish_` says it
  outright. A publish returns the new `PublishedPost` (`pk`, `id`, `code`, `taken_at`,
  `media_type`, `upload_ids`) rather than `PostDetail`, for the reason ruling 33 gave
  `SentMessage`: the answer is the private API's media object, another shape, and filling a
  `PostDetail` from it would be guessing. The read that confirms a post is up is `by_code`, and
  the `dumpsta` commands make it in the same process, so the capability stays one publish and a
  failed confirmation never hides a post that is up. `delete_post` takes the shortcode beside
  the `pk` because the delete is sent from the post's page, whose address is its referer, and it
  names the post as `<pk>_<viewer id>`, so only the viewer's own post can be named. An image is
  a JPEG as bytes or a path, read on a worker thread, and anything else is refused before a
  request, since only a JPEG upload was observed; converting is the caller's, which keeps an
  image library out of the package, and `pillow` is a dev dependency for the probes and gates
  only. The caption defaults to empty, nothing about location, tags, collaborators or sharing
  out is sent, a carousel needs two images, and its upper limit is left to the upstream,
  unobserved. The snapshot grew from 520 lines to 535, all additions.
- **W38. An upload is a write, and a half finished publish raises the original error with a
  note.** Ruled 2026-09-23 for E1 item 9. Each upload goes through `send_write` on a sender
  over a fourth pool pinned to `i.instagram.com`, carrying the account's cookies as the browser
  did, and sharing the account's pacer. So it is sent once, spaced by the write spacing, counted
  against the write budget and stopped by the write stop, like every write, and a photo costs two
  writes and a carousel of n costs n + 1. The browser sent a carousel's uploads at once and the
  publish 3.4 s later, and under `PARITY` the engine takes over a minute for two slides, a
  recorded departure that `FAST` removes. When an upload applied and a later write fails, the
  exception raised is the failing write's own, unwrapped, so `CheckpointRequired` and
  `OutcomeUnknown` stay what they are, with a note beginning `posting:` naming the half that
  failed and every orphaned upload id. That is Step 19's orphaned upload gate. Nothing is retried
  or reused, and what an orphan costs is UNRESOLVED. The CLI now prints every note an exception
  carries after its first line, for every command, which adds the loop-thread seam note to
  stderr where it was dropped before.
- **W39. One browser post, and the single photo publish identified from the bundle.** Ruled
  2026-09-23 for E1 item 9. The knowledge base held nothing on posting, so the browser posted
  once, as the owner's limits allow, and deleted in the same run: a carousel of two generated
  squares, chosen over a photo because it exercised two uploads, the JSON body and the delete in
  one post. The single photo `configure` was never sent by the browser. Its path and form came
  from the composer bundle, read at no request, and its first two observations were engine
  replays, which the skill accepts as an identification. Every literal reached `verify_count` 2
  before it entered `engine/dumpstagram`. A deleted post's read answered a generic query error,
  code `1675030`, on all five the engine read back, so `dumpsta delete-post` reports `gone` only
  on that code after a delete answered `did_delete` true, and a read refused any other way is
  reported unknown. That literal sits in `_cli/commands/posting.py`, outside the provenance
  gate's failure-code scope of `_private/web`, which the gate does not check, and is named here
  so it is not mistaken for a checked one. Live traffic for the item: 2 browser page loads, and 35
  engine requests (22 discovery, 13 acceptance), 7 of them uploads to `i.instagram.com`.
- **W40. The gates hold recorded shapes, and two shared gates grew.** Ruled 2026-09-23 for E1
  item 9. `tests/fixtures/posting/` holds the browser's upload, carousel publish and delete,
  pseudonymised from the capture, and the engine's verified photo form. The request gates compare
  header names in both directions, so a header the engine adds or drops fails, less the three the
  engine does not send (`content-length`, which `httpx` adds, and the two departures,
  `x-web-session-id` and `x-ig-max-touch-points`). `tests/test_facade_parity.py` gained the three
  methods in `CORE_FUNCTION_FOR_ALIAS` and three parameter values, which puts them under every
  namespace gate rather than loosening any. The CLI's `Client` protocol gained `media`, which
  `SyncClient` already satisfies. `scripts/verify_posting_gates.py` holds 40 mutations over 26
  gates in `tests/test_posting.py` and three parity gates, each seen red then green.
- **W41. E2 is prepared from compiled artifacts read without the session, and its contracts stay
  local.** Ruled 2026-09-23 by the orchestrator on the owner's delegation, for the E2
  preparation. The owner was asleep, so no request carrying the account's cookies was sent. The
  artifacts come from three sources that spend nothing on the account: the census scout's
  in-browser reading, the request bodies the skill's captures already keep, and cookieless
  fetches of static bundles through the doctor's host pin, capped at 80, at least 1 s apart,
  with no page document fetched, because the recorded home document names them. Its bootloader
  `compMap` names the chunks of lazily loaded dialogs, which is how the likers and activity
  feed queries were found without opening either. 78 fetches were spent, one of them a read
  stall. Every contract lands in the local knowledge base as a hypothesis finding with its
  replay template, and the `e2_*` probes read the `doc_id`, the path and the root field from
  there at run time, so no `doc_id` literal enters `engine/`, a probe included. The committed
  [e2-execution.md](e2-execution.md) names operations, variables and their sources, and holds no
  `doc_id` and no personal data.
- **W42. No other person's story is marked seen before the seen mutation is verified on the
  owner's own.** Ruled 2026-09-23 by the orchestrator on the owner's delegation, for E2. W6
  stands: a story read marks seen by default. The mutation is visible to the story's owner, so
  its live verification is an arranged run: the owner posts a story from his phone, the engine
  reads it and marks one item seen, a read confirms it, and the owner deletes the story. Until
  that run passes, `client.stories` does not ship. The read queries mark nothing (INFERENCE), so
  discovery reads the owner's own reel and highlights, and reads another account's reel only
  behind the probe's explicit `--third-party-reel` flag, as the read query alone. The W30
  partner's stories are never read or marked seen, since W30 admits him for direct messages and
  follows only.
- **W43. Reading other accounts' public content is not treated as visible to them, and three E2
  actions are.** Ruled 2026-09-23 by the orchestrator on the owner's delegation, for E2.
  Profiles, posts, comments and replies, likers, follower lists, explore, hashtag and location
  pages and search answer a read the other person cannot see (INFERENCE: no web surface lists
  who read them), so E2 acceptance may read them on public accounts the owner's timeline or
  explore shows. Three E2 actions are visible and are never run on another person in E1 to E5:
  marking a story seen (W42), opening a message request thread, which marks it seen to its
  sender (INFERENCE), and marking a thread read. Two E2 side effects change only the owner's own
  state, `news/inbox_seen` and the activity view's `mark_as_seen`; discovery sends neither, and
  the page model decides the default.
- **W44. A variable never observed is captured, not guessed, and an operation without a
  capability carries its reason.** Ruled 2026-09-23 by the orchestrator on the owner's
  delegation, for E2. Where the artifact names an object argument whose fields it does not
  carry, or an enum whose values it does not list (the reels feed's `data`, the personalised
  typeahead's `data`, the keyword grid's session ids, saved posts' `collection_types`, the
  activity view's request objects, the badge's `device_id`), no probe sends a plausible value;
  the batch waits for one browser capture night of about fifteen loads, listed in
  [e2-execution.md](e2-execution.md). A scalar whose value was not observed but whose meaning is
  plain, such as a page size, is sent at the value the neighbouring verified query uses and
  named as unobserved in its finding. Every E2 census operation that will not back a capability
  is given a reason there: professional accounts only, ads, generated text, machine
  translation, a player's thumbnails, an alternate compiled route of an action with a chosen
  route, or chrome. Items whose non-empty answer needs another person's action, incoming follow
  requests and the blocked list, are verified empty in E2 and non-empty in E6.

- **W45. The inbox reads are `direct.inbox`, `iter_inbox`, `message_requests` and
  `unread_counts`, and the row is a `DirectThread`.** Ruled 2026-09-24 by the orchestrator on the
  owner's delegation, for E2 batch 1. The plan's `threads` became `inbox`, because a row of the
  message requests is a thread too and the read is of one folder, the one the website calls the
  inbox. `requests` became `message_requests`, because in a library that sends requests the bare
  word reads as HTTP. The model is `DirectThread` rather than `Thread`, which would shadow
  `threading.Thread` in any caller that imports both and sits beside the private `InboxThread` the
  poller reads. Each lives on `client.direct` only, with no flat twin, under W1 and W24, and
  `iter_inbox` is the one iterator, since `message_requests` is not a `Page`: no query that reads
  a request folder past its first page has been observed, so `MessageRequests` holds two tuples
  and the upstream's `has_next_page` for each rather than a cursor nothing can follow.
  `ThreadParticipant` carries the account id, not the messaging id, so it feeds
  `profiles.by_id`. The surface grew from 536 lines to 580, 44 added and none removed or changed.
- **W46. The cursor `direct.inbox` hands out carries the mailbox id.** Ruled 2026-09-24 for E2
  batch 1. The next page query is keyed on the mailbox id beside the upstream's cursor, and only
  the first page's answer carries the id. So a page's `end_cursor` is `<mailbox id>:<upstream
  cursor>`, and `inbox(after=...)` splits it and refuses with `ValueError`, before anything is
  sent, any cursor it did not hand out. `Page.end_cursor` was already opaque, so no promise
  changes. Keeping the id on the client instead would be hidden state a second client could not
  resume from, against ADR-0004, and re-reading the first page for it would spend a request per
  page.
- **W47. The unread counts are counted by the engine, and two verified operations back no
  capability.** Ruled 2026-09-24 for E2 batch 1. Both unread queries answer a folder's first page
  of rows with their read receipts and no number, and the browser counts. `unread_counts` sends
  the inbox folder and then the pending one with one device id, as an inbox load does, and counts
  a row unread when it is marked unread or the viewer's receipt is older than its last activity
  or absent. The viewer is the mailbox id, the one value both answers carry that equals the
  viewer's messaging id, which the rows name in their receipts. The rule is an INFERENCE, since
  the browser's is not read, and one live unread row agreed across the listing and the count
  query. Muted threads count, and a folder with rows past its first page says so rather than
  being called whole. `IGDBadgeCountOffMsysQuery` backs no capability: it answers the inbox
  folder's rows with no folder argument, which `unread_counts` already reads, and it stays the
  page-load companion it was. `IGDInboxInfoOffMsysQuery` backs none either: it answers admin ids,
  two capability bitmasks and the members, with no activity and no receipts, nothing a
  `DirectThread` lacks. A message request row has not been observed, since both folders were
  empty on every read; it is mapped as an inbox row and raises `SchemaChanged` where it differs,
  and its non-empty check waits for E6 under W44, which needs a second account to send one.
- **W48. The canary replays thirteen reads, and four doctor gates followed.** Ruled 2026-09-24
  for E2 batch 1. The three new queries are in `READ_QUERIES`, so the catalog gate holds them and
  the doctor replays each once: the next page on the cursor the listing step learns, skipped when
  the first page is the last, and the requests and the inbox folder's unread rows keyed on
  nothing learned. That takes a live doctor run from at most 12 paced requests to at most 15.
  `tests/test_doctor.py` followed in three literals, each checked red before the edit and green
  after it: the registry count, 30 to 33, the stated plan, 10 reads to 13, and the dry run's
  paced total, 12 to 15. The skip gate was strengthened to require the next page skipped too
  when the inbox lists nothing, four reads rather than three, and a new gate holds every read to
  replaying ok against an answer its mapper accepts, which no gate did before. The parity tables
  gained the three methods and the iterator, which puts them under every namespace gate. The gate
  fixtures are the recorded answers, pseudonymised by `scripts/build_direct_read_fixtures.py`,
  and `scripts/verify_direct_read_gates.py` holds 34 mutations, each seen red then green. Live
  traffic: 9 probe requests and 5 through `dumpsta`, 14 of the 25 the batch allowed, and no
  browser page load.
- **W49. Account B is the second account, and it is the owner's to spend.** Ruled by the owner on
  2026-09-27, recorded by the orchestrator. The owner made a new account for the engine's tests,
  called account B here. Its cookies are in `.env.account-b` at the repository root, gitignored,
  adopted into `engine/state/session-b.json`, and its username is never named in a committed file,
  a log or a commit message. A `profile --by-id` read as B answered on 2026-09-27: public, no
  posts, no followers. B is not another person under W8, W30 and W43, so a write whose effect lands
  on B is allowed, including making B private, B following the owner, and the owner blocking B,
  each restored in the same run under ruling 24. No password is kept anywhere. The engine adopts
  cookies (ADR-0008), and the one live login in E5 is started by the owner, who types B's password
  at run time.
- **W50. Account B ages before it sends its first engine write.** Ruled 2026-09-27 by the
  orchestrator on the owner's delegation. A new account is likely scored more strictly than an
  aged one (ASSUMPTION, the risk this plan already carried), and a restricted B would stop every
  two-account item at once. So reads as B run from 2026-09-27, and writes sent as B run from
  2026-09-30, while the owner uses B by hand meanwhile. Writes sent as the owner that land on B,
  such as a follow of B, are the owner's writes and run on the owner's schedule. Until
  2026-10-11 a client built on B's session halves `Behavior`'s write budget, a setting and not a
  code change. Instagram can link the two accounts through the shared device and network, so a
  restriction on one may reach the other. ASSUMPTION.
- **W51. The second-account items move into the phase they belong to, and E6 keeps what needs a
  third account.** Ruled 2026-09-27 by the orchestrator on the owner's delegation. The plan parked
  every two-account item in E6 only because no second account existed. With B, the reads that
  were verified empty (follow requests, message requests, the blocked list) are verified non-empty
  in E2, the relationship writes and the writes on another account's content join E3, the direct
  items and the events only the other side causes join E4, where B replaces the owner's hand as
  the other side of an arranged run, and the live login, the username change, log out and the
  live multi-account host join E5, all on B (W7). Group threads still need a third participant,
  so E6 keeps them under W9. The W30 partner is not borrowed for a group without the owner's word.
- **W52. A field error beside an answer is a partial answer, and the answer is returned.** Ruled
  2026-09-27 for E2 batch 2, and binding on every later batch. FACT: on 2026-09-27 the verified
  `PolarisProfilePostsQuery` answered the owner's grid whole, eight posts, beside an `errors` array
  of three entries, severity ERROR, each with a `path` of
  `xdt_api__v1__feed__user_timeline_graphql_connection.edges[n].node.location.profile_pic_url`, one
  per post carrying a location, and `classify` refused the page with `UpstreamRejected` code
  `errors`. `PolarisPostActionLoadPostQueryMediaIdQuery` answered once with twelve errors, severity
  UNSET, on fields under `xdt_api__v1__media__media_id_web_info.items[0]`, and its second replay
  had none. The rule, in `_private/web/classify.py`: an answer whose every error carries a `path`
  of two elements or more, the first a key of `data` whose value is present and not null, is a
  partial answer. It is returned as the upstream sent it, each errored field reading as the null
  the payload holds, and the mappers' own required and optional readers decide from there, so a
  required field that errored still raises `SchemaChanged`. Anything else with an `errors` array
  is refused as before: an error with no path, a path of one element, a path under a root that is
  null or absent, and a field error beside any of those. `classify_preloaded` reads the envelope
  through the same function, so a preloaded result follows the same rule. A partial answer is a
  payload and carries user content, so its body is not scanned for checkpoint markers, which the
  refused path still does. Effect on what shipped: `profiles.by_username` under the default page
  route was not broken, FACT from the code, because the grid query is one of the page's six and
  its answer is screened only for a checkpoint or a throttle, and a rejection there is dropped;
  that screen did scan the refused grid body for checkpoint markers, so a caption quoting
  `/challenge/` would have raised `CheckpointRequired`, never observed and now closed for partial
  answers. The username resolution of `ProfileRoute.QUERIES`, and the canary's replay of the same
  query, ask for one post, and the owner's newest post carries no location, so neither was broken
  on the owner's account, an INFERENCE: it assumes the one-post answer is the same newest post and
  that the error follows a post's location. Any account whose newest post carries such a location
  would have had its resolution refused. Five gates in `tests/test_classify.py`, one of them
  parametrised four ways, and six mutations in `scripts/verify_profile_tabs_gates.py`. Evidence:
  the captures `e2-profile-tabs-2026-09-27-*-03-posts-grid-first-page-rejected.json` and
  `e2-post-depth-2026-09-27-013544-08-post-by-media-pk-1-rejected.json`, each `debug_link`
  redacted, and the knowledge base pattern `field-errors-arrive-beside-a-full-answer`.
- **W53. The posts grid is `profiles.posts(username, *, after=None) -> Page[Post]` and
  `iter_posts`, and it returns the home timeline's `Post`.** Ruled 2026-09-27 for E2 batch 2. The
  parameter is a username, because the grid query is keyed on one; a caller holding a `Profile`
  passes its `username`, and a `str | Profile` union was not taken because a parameter's type is a
  snapshot line that could never be narrowed again. The first page is the verified
  `PolarisProfilePostsQuery` at the profile page's twelve, and every later page
  `PolarisProfilePostsTabContentQuery_connection` (finding `profile-posts-grid-next-page`,
  replayed twice on 2026-09-27 on a public account the owner's timeline shows, twelve edges and
  `has_next_page` true each time) with the first page's variables, the upstream's `end_cursor` as
  `after`, and `first` 12 and `include_multi_captions` true as the compiled artifact declares them.
  Both answer on `/graphql/query` under one root beside `xdt_viewer`, and `has_next_page` is the
  only terminator. A grid node is the home timeline's media node key for key, FACT over 32 grid
  nodes and the home page's six posts, with ten keys more that are dropped (`__typename`, `group`,
  `longform_title`, `media_cropping_info`, `photo_of_you`,
  `profile_grid_thumbnail_fitting_style`, `thumbnails`, `timeline_pinned_user_ids`, `title`,
  `upcoming_event`), two the home node has and the grid lacks (`brs_severity`,
  `view_state_item_type`, neither read), and `is_seen` null on every grid node where the home
  timeline sent a boolean. `Post.is_seen` is a required `bool` in the frozen snapshot, so the
  grid mapper reads that null as False, which carries no information and says so on `Post`, and
  the home timeline mapper still refuses a null. The per-edge `cursor` was null on every grid
  edge. Departure: a browser reads the first page inside the profile page load, beside the
  document and five other queries, and `posts` sends it alone; a later page is sent as a browser
  sends it when the grid is scrolled (INFERENCE, the scroll was not captured). An impossible
  username raises `NotFound` before anything is sent, as the page route does.
- **W54. The highlights tray is `profiles.highlights(user_id) -> HighlightTray`, its first page
  only.** Ruled 2026-09-27 for E2 batch 2. `ProfileStoryHighlightsTrayContentQuery_connection` was
  never answered, since the owner's tray holds one highlight and the public account's none, so no
  cursor is handed out and `HighlightTray` carries `highlights` and the upstream's
  `has_next_page` as `has_more`, the `MessageRequests` pattern of W45. No `iter_highlights` ships,
  since the read is not a `Page`. `Highlight` carries `id` (the upstream's `highlight:<number>`),
  `title`, `cover_url` from `cover_media.cropped_image_version.url`, and `owner_id` and
  `owner_username` from the node's `user`, every field observed on the one highlight read five
  times on 2026-09-27; `__typename` XDTReelDict is dropped. The query is the verified
  `PolarisProfileStoryHighlightsTrayContentQuery`, which moved from `COMPANION_QUERIES` to
  `READ_QUERIES` because a capability now reads it; the profile page still sends it among its six.
  Departures: it is sent alone, and with the site root as its referer rather than the profile
  page, because the method has an id and no username. The profile query's referer was not
  validated under ablation; this one's has not been tested, an ASSUMPTION the batch's live
  acceptance checks. A username raises `ValueError` before anything is sent.
- **W55. The suggested accounts are `profiles.suggested(user_id)` and
  `profiles.suggested_for_you()`, rows of a new `ProfileSummary`.** Ruled 2026-09-27 for E2 batch
  2. `suggested` sends `PolarisProfileSuggestedUsersWithLazyQueryQuery` (finding
  `profile-suggested-users-on-demand`, replayed twice, 17 to 19 rows each), the query a browser
  sends when the suggestions beside a profile are opened, with `module` profile and the account id
  as `target_id`, and returns `tuple[ProfileSummary, ...]`. `suggested_for_you` sends
  `PolarisSuggestedUserListQuery` (finding `home-suggested-accounts`, replayed twice, one group of
  five each) with the recorded browse's variables and returns `tuple[SuggestedAccount, ...]`,
  because each item carries the line the website shows under the account in `social_context`,
  content that a bare row would drop. Neither answer carried a cursor or a count, so each tuple is
  the list as sent. `ProfileSummary` is built for lists in general, since batch 3's followers
  will reuse it: `id` from `pk` (equal to `id` on all 138 rows), `username`, `full_name`,
  `is_verified`, `profile_pic_url`, and `is_private`, `hd_profile_pic_url` and
  `friendship_status` where the row carries them, `None` where it does not. No row of the
  suggested accounts list carried `is_private`, FACT. `FriendshipStatus` was not reused: every
  row's status lacked `muting` and `is_muting_reel`, which it requires, and filling them would
  be a guess. `ListFriendshipStatus` requires the six flags every row carried (`following`,
  `outgoing_request`, `incoming_request`, `is_bestie`, `is_feed_favorite`, `is_restricted`) and
  carries `followed_by` and `blocking` where a list sends them, since the `show_many` statuses
  batch 3 will read lack both (FACT from its capture of 2026-09-27). Departures: `suggested` is
  sent with the site root as referer, for W54's reason, where the replays sent the profile page;
  `suggested_for_you` is sent alone rather than inside the page that lists it.
- **W56. The canary replays seventeen reads, and three doctor literals followed.** Ruled 2026-09-27
  for E2 batch 2. `READ_QUERIES` gained the grid's next page, the highlights tray, and both
  suggested lists, so a live doctor run goes from at most 15 paced requests to at most 19. The
  `PolarisProfilePostsQuery` step now builds the grid's first page at twelve, the request `posts`
  sends, and reads it with both mappers the query feeds, the grid's and the username
  resolution's, learning the grid cursor when the page says more exist; the next page step is
  keyed on that cursor and skipped without one, which is what the owner's one-page grid gives.
  `tests/test_doctor.py` followed in three literals, each seen red before the edit and green
  after it: the registry count, 33 to 36 (`assert 36 == 33`), the dry run's paced total, 15 to 19
  (`assert 19 == 15`), and the stated plan, 13 reads to 17. Its answer for
  `PolarisProfilePostsQuery` moved from a one-post stub the grid mapper cannot read to the
  pseudonymised author grid, and the four new reads answer from the batch's fixtures. A new gate
  holds the next page to the first page's cursor and to being skipped on the owner's grid. The
  parity tables gained the four methods and the iterator. The gate fixtures are the recorded
  answers, pseudonymised by `scripts/build_profile_tabs_fixtures.py`, and
  `scripts/verify_profile_tabs_gates.py` holds 43 mutations, each seen red then green. Live
  traffic for the discovery: 8 requests on each of three runs of `probes/e2_profile_tabs.py`, 24,
  the first two stopped at the grid's field errors, and `probes/e2_next_pages.py`'s 10 requests,
  shared with batch 4, whose first six served this batch. The CLI acceptance,
  `probes/e2_profile_tabs_cli_acceptance.py`, ran with every step exit 0 and 7 requests, log
  `logs/e2-profile-tabs-cli-2026-09-27-022848.json`.

- **W57. A token the upstream asks to re-open the window for is a stale token.** Ruled
  2026-09-27 for E2 batch 2, after the batch's CLI acceptance stopped at its first step. The
  session file had last been bootstrapped on 2026-09-24, and `profile --by-id` on the owner drew
  HTTP 200 with a 249 byte `for (;;);` envelope, `error` 1357004, summary "Sorry, something went
  wrong", description asking for the browser window to be closed and re-opened, and a null
  payload. FACT, three identical answers, while the same read after a fresh bootstrap answered
  200 with data an hour earlier in every E2 probe. `_core/tokens.py` re-bootstrapped once only on
  the HTML shell, so every read on an aged session file failed with `UpstreamRejected` rather than
  fetching a token, a defect in every read since `1.0.0`. The code joins the shell in
  `STALE_TOKEN_CODES`, with the same once-only and not-just-fetched conditions, so a fresh token
  that is refused the same way still raises. INFERENCE: the envelope means an expired `fb_dtsg`,
  since the description asks for what a page reload does. A new gate in `tests/test_direct.py`
  was seen red before the change and green after. Live, the batch 2 acceptance's first step spent
  three requests, the refusal, one bootstrap and the read, and answered.

- **W58. The followers list is `profiles.followers(user_id, *, after=None) ->
  Page[ProfileSummary]` and `iter_followers`, over REST, ending on `has_more`.** Ruled 2026-09-27
  for E2 batch 3. The read is `GET /api/v1/friendships/<user id>/followers/` with `count` 12 and
  `search_surface` follow_list_page, the query the browser's follow list sent in the recorded
  browse of `run-2026-09-23-005544`, replayed six times on 2026-09-27 (finding
  `read-an-account-s-followers`, logs `logs/e2-follow-lists-2026-09-27-013523.json` and
  `-014452.json`). It is keyed on the numeric account id in the path, so a username raises
  `ValueError` before anything is sent, as `social.follow` refuses one. The next page carries
  `max_id` set to the previous page's `next_max_id`, a 120 character string; on both runs that
  page answered 7 new accounts with zero overlap with the first page's 12. FACT, twice, which
  meets the standing rule, so the read pages rather than shipping a first page only, and the
  cursor `Page.end_cursor` hands out is `next_max_id` unchanged. The terminator is `has_more`.
  No last page has been read: the owner's profile counts 82 followers, the walk stopped at 19,
  and the second page, 7 accounts where 12 were asked for, still said `has_more` true with a
  `next_max_id`. So a short page is not an end, FACT, and what the last page carries is not
  observed; `has_more` false ending the walk is an INFERENCE from its name, and `next_max_id` is
  read where the answer carries it and `None` where it is absent or null, so a last page that
  drops it maps rather than failing, and a page that says more exist with no cursor raises
  `SchemaChanged` in the walk (W23). The row is batch 2's `ProfileSummary` read by its mapper
  unchanged: every row of the four pages read carried `pk`, `id` and `pk_id` equal, `username`,
  `full_name`, `is_private`, `is_verified` and `profile_pic_url`, no high resolution picture and
  no relationship; `profile_pic_id` was absent on one row of each page and is not read. Dropped from
  the answer: `groups` and `more_groups_available`, two titled groups of two small pictures shown
  above the list, three of whose four accounts were on the same page, empty on one first page of
  four and absent from the next page, and seven flags, sizes and tokens that describe the list's chrome.
  A REST answer reports failure in `status`, which the classifier does not read, so the mapper
  refuses anything but `ok` with posting's check. The request is the first REST read on the web
  API: the posting publishes' header set with `x-ig-max-touch-points` 0 and `x-web-session-id`,
  a fresh three-group value per read, sent on both of that read's requests because the browser
  carried one value on every request of its page session. Departures: a browser loads the list's
  code chunk and opens it from the profile page, so its referer is that page; the engine sends
  the page alone with the site root as referer, because the method has an id and no username, an
  ASSUMPTION until the batch's live acceptance, which on 2026-09-27 read two pages that way with
  both steps exit 0, one observation.
  Following and mutual followers have no observed request and wait on the capture night (batch
  10); nothing for them ships.
- **W59. Each followers page is followed by the viewer's relationship to the accounts on it, as
  the browser's list does, and `Behavior.follow_list_statuses` is the departure.** Ruled
  2026-09-27 for E2 batch 3. FACT from the recorded browse: 455 ms after the one followers page it
  loaded, the list sent `POST /api/v1/friendships/show_many/` with `user_ids` the page's 11 ids
  in the page's order, then `jazoest` and `fb_dtsg`, with the same `x-web-session-id` and the
  three headers a form POST adds. The browse did not scroll, so a later page's statuses were not
  observed; that the list sends one per page is an INFERENCE from the list being paged and the
  statuses naming exactly one page's ids. The read was replayed four times (finding
  `friendship-statuses-for-many-accounts`), 11 statuses each. So under parity `followers` sends
  the page and then its statuses inside one action, one pacer slot, and fills each row's
  `friendship_status`, and `Behavior.follow_list_statuses` set to False leaves the second request
  out, one request a page, with every `friendship_status` `None`. A page that lists nobody sends
  no statuses, and a bootstrap is spent only when the statuses will be sent, because the page
  itself carries no page token. `show_many` is a POST that changes nothing, so it is a read and
  runs under the read retry policy. The statuses fold into batch 2's `ListFriendshipStatus`
  unchanged: all 44 statuses read carried its six required flags as booleans and neither
  `followed_by` nor `blocking`, which read `None`, the case W55 anticipated. `is_private`, which
  the row itself carries, and `text_post_app_pre_following`, a Threads app flag, are dropped.
  Statuses are matched to rows by account id, not position, and an account the answer does not
  name keeps `None`; none was missing on any answer read.
- **W60. The doctor does not replay the followers read, and `dumpsta followers` pages with
  `--pages` only.** Ruled 2026-09-27 for E2 batch 3. The canary exists to catch a persisted
  query's `doc_id` rotating (W31), and every `ReplayStep` is keyed on a `PersistedQuery` in
  `READ_QUERIES`. The followers page and the statuses are REST paths with no `doc_id` for a
  bundle to compile, so neither fits the W48 pattern, the canary is unchanged at seventeen reads,
  and no doctor gate moved. A path that stops answering would fail the read itself with
  `SchemaChanged` or `UpstreamRejected`. `dumpsta followers USER_ID` takes `--pages` (default 1)
  and `--after`, as `posts` and `inbox` do, and stops on the page's own `has_more`. No `--limit`
  was added: no existing paged command has one, and a limit that ended inside a page would print
  the page's cursor, which resumes after the accounts it cut. `tests/test_follow_lists.py` holds
  16 gates on the recorded answers, pseudonymised by `scripts/build_follow_lists_fixtures.py`,
  and `scripts/verify_follow_lists_gates.py` holds 31 mutations, each seen red then green. The
  parity tables gained `followers` and `iter_followers`. The surface grew from 631 lines to 636,
  five added and none removed or changed. Live traffic: `probes/e2_follow_lists.py` ran twice,
  7 requests each, 14; the CLI acceptance, `probes/e2_follow_lists_cli_acceptance.py`, is written
  and ran on 2026-09-27, 5 requests, both steps exit 0.

- **W61. The replies are `media.replies(post_pk, comment_id, *, after=None) -> Page[Comment]` and
  `iter_replies`, two queries, and a reply is a `Comment`.** Ruled 2026-09-27 for E2 batch 4. The
  first page is `PolarisPostChildCommentsQuery` (finding `read-comment-replies`, replayed three
  times on 2026-09-27) and every later page `PolarisPostCommentsChildrenPaginationtQuery` (finding
  `read-comment-replies-next-page`, replayed twice), both on `/api/graphql` under one root, with
  `media_id`, `parent_comment_id`, `is_chronological` true, `before` and `last` null and the
  logged-in provider, and `after` null or the previous page's `end_cursor`. FACT: `first` 3 drew
  9 replies with `has_next_page` false on a comment with 9, and 11 with a 90 character cursor on a
  comment with 52, and the next page with `first` 10 drew 12 new replies, none on the first page,
  with a cursor again. So the page's length is the upstream's and `has_next_page` is the only
  terminator. `first` 3 and 10 are the probe's values, never observed from a browser, an
  ASSUMPTION a fingerprint could read, named in `REPLIES_FIRST_PAGE_SIZE` and
  `REPLIES_NEXT_PAGE_SIZE`. A reply node is the comment page's node key for key, FACT over 32
  replies, except that `child_comment_count` was null on every one, so `parse_reply` reads it
  optional and `Comment.reply_count` is `None` on a reply, and `parent_comment_id`, a string on
  every reply, is required; no new model. Replies come oldest first (INFERENCE from their
  `created_at` over the two pages). No last page of a long thread has been read. Departure: a
  browser reads replies when "view replies" is opened on a post page; the engine sends each page
  alone with the site root as referer, because it is handed a pk and no shortcode. A `pk` in the
  id form or a comment id that is not digits raises `ValueError` before anything is sent.
- **W62. The likers are `media.likers(post_pk) -> tuple[ProfileSummary, ...]`, the list the
  upstream gives, which is a sample.** Ruled 2026-09-27 for E2 batch 4. `PolarisPostLikedByListDialogQuery`
  (finding `read-a-post-s-likers`, replayed twice) with `{"media_id": <pk>}`, root
  `fetch__XDTMediaDict`, whose `likers_connection` carried `nodes` and nothing else. FACT: 98
  accounts on both replays, for a post counting 193647 likes, so the list is bounded by the
  upstream and is not every liker; no cursor, no count and no page info exist to go further, so
  the method returns a tuple and no iterator ships (W45). A node is batch 2's list row read by
  `parse_profile_summary` unchanged: `pk` equal to `id`, the names and pictures, a relationship
  with all eight flags, and no `is_private`, which reads `None`. The REST
  `/api/v1/media/<pk>/likers/` in the bundle was never observed and is not used. Departure: sent
  alone with the site root as referer, where the dialog opens from a post.
- **W63. `media.by_id(post_pk) -> PostDetail` leaves empty what its item does not carry.** Ruled
  2026-09-27 for E2 batch 4. `PolarisPostActionLoadPostQueryMediaIdQuery` (finding
  `read-a-post-by-media-id`, replayed twice) with `{"mediaId": <pk>}` on `/graphql/query`, root
  `xdt_api__v1__media__media_id_web_info.items`. The first replay answered beside twelve field
  errors under the item, on `ad_id`, `audience`, three slides' `organic_tracking_token`,
  `logging_info_token` and six flags of the author's relationship, none read, so under W52 it
  maps whole, and the second had none. FACT from the one post read twice, a carousel of three:
  the item is the post query's family with less in it. Its slides carry neither `media_type` nor
  `product_type`, which `CarouselChild` requires in the frozen snapshot, so `carousel_children` is
  empty while `carousel_media_count` counts them, rather than a slide kind guessed from its
  renditions; it carries no `accessibility_caption`, no `hd_profile_pic_url_info` on the author
  and no `coauthor_producers`, which read `None`; its tags carry no `position`. The shortcode read
  and the timeline still refuse an author without the picture key, which a gate holds. So a
  caller wanting slides reads `by_code` with the returned `code`, one request more, and the
  docstring says so. `PostDetail` rather than a new model, because every field it fills means
  what it means there. Departure: sent alone with the site root as referer. Extended the same day
  after the batch's live acceptance (log `logs/e2-post-depth-cli-stopped-2026-09-27-032646.json`)
  saw `post --by-id` exit 8 on a reel: FACT from `probes/e2_post_by_id_shape.py` (4 requests, log
  `logs/e2-post-by-id-shape-2026-09-27-032720.json`), of two reels read by media pk, one with
  both audio slots null mapped, and the other's `original_sound_info` carried `audio_asset_id`,
  `consumption_info`, `ig_artist`, `original_audio_title` and `should_mute_audio` and no
  `is_explicit`, which `MediaAudio` requires, with no `errors` array. Every other key the video
  and audio mappers require was present on both (`video_versions` entries of `url`, `width`,
  `height` and `type`, a manifest naming its duration, `has_audio`, `clips_metadata` with both
  slots, `ig_artist` with `id` and `username`). So on this read an original sound without the
  flag makes `audio` `None` rather than a flag guessed, and every other read still refuses it; a
  licensed song read by media pk has not been seen and is mapped strictly. The gate
  `test_a_reel_read_by_media_pk_maps_and_an_original_sound_without_its_flag_is_unknown` was seen
  red on the mapping before the change, `SchemaChanged: ...original_sound_info.is_explicit is
  missing from the payload`, and green after, on both bodies pseudonymised into
  `tests/fixtures/post_depth/`, and two mutations hold it.
- **W64. The strip under a post is `media.more_from_author(author_id) -> tuple[PostThumbnail,
  ...]`, keyed on the author only.** Ruled 2026-09-27 for E2 batch 4.
  `PolarisDesktopPostPageRelatedMediaGridQuery` (finding `read-more-posts-from-an-account`,
  replayed twice) with `media_owner_id`, `count` 6 and the short drama provider false, on
  `/graphql/query`, root `xdt_api__v1__profile_timeline`. The query takes no post, so the method
  takes none, rather than the plan's `(post_pk, author_id)`. `count` 6 is the probe's value, not
  observed from a browser, an ASSUMPTION named in `MORE_FROM_AUTHOR_COUNT`. FACT: six posts on
  both replays, the same six in the same order, none of them the post the author id came from.
  An item is thinner than any post read, with no `taken_at`, no viewer state, no video renditions
  and an author of `pk`, `id` and `username` only, so it cannot be a `Post` without guessing, and
  the new `PostThumbnail` carries `id`, `pk`, `code`, the author's id and username, `media_type`,
  `product_type`, the two counts, `like_and_view_counts_disabled`, `caption`,
  `carousel_media_count` and `images`, every one present on all six. Dropped: the slides, which
  carried an id and renditions and no kind, `num_results`, and fields null on all six or chrome,
  listed on the mapper. A username raises `ValueError` before anything is sent.
- **W65. Location, tagged accounts and collaborators are fields on the post, where `None` means
  the read does not carry them.** Ruled 2026-09-27 for E2 batch 4. `Post` and `PostDetail` gained
  `location: Location | None`, `user_tags: tuple[UserTag, ...] | None` and `collaborators:
  tuple[ProfileSummary, ...] | None`, and `CarouselChild` gained `user_tags`, all with a `None`
  default, additions only. Evidence, FACT over the 37 distinct posts of the home timeline and
  grid captures of 2026-09-27 and the post read by media pk: every timeline and grid post
  carried `location`, `usertags` and `coauthor_producers` keys, 5 had a location, 3 had tags and
  1 had a collaborator; the post query items of E1 item 6 carry the same three keys. A location
  carried `pk`, `name`, `lat` and `lng` on all 39 the E2 probes kept, with `pk` a string on the
  home timeline and a number on a grid and in the post query, so `Location.id` is its string
  form. A tag carried `user` and, except in the post read by media pk, a two-number `position`;
  every tag carried `id` and the home timeline's one slide tag carried no `pk`, so a tag's account
  is read by `id`, into `ProfileSummary` with no relationship. A collaborator carried a list row
  with all eight relationship flags and is read as one. A null `usertags` or `coauthor_producers`
  is an empty tuple, INFERENCE that null means none, and an absent key is `None`, so a caller can
  tell "none" from "this read does not say". `invited_coauthor_producers` was an empty list on
  every post and is not modelled. The CLI's post JSON gained `location`, `user_tags` and
  `collaborators`. One existing gate followed: `test_the_post_read_maps_has_liked_and_like_count_from_the_item`
  in `tests/test_likes.py` compares a whole `PostDetail` built from an item that carries a null
  `usertags` and an empty `coauthor_producers`, seen red (`user_tags: () != None`) before
  `user_tags=()` and `collaborators=()` were added to its expected value and green after, which
  asserts two fields more than before.
- **W66. The post modal's context backs no capability and is not sent.** Ruled 2026-09-27 for E2
  batch 4. `PolarisPostModalContextQuery` (finding `read-a-post-modal-context`, replayed twice,
  2339 bytes) answers the post's `pk`, `code`, kinds, the author with two relationship flags,
  `coauthor_producers` as `pk` and `id` only, `usertags` with positions, and a few sharing and
  grid flags. FACT from the two answers: nothing there is missing from `by_code` or the timeline,
  and its collaborators are ids without names. It is a companion of opening a post in a modal,
  whose burst has not been captured, so it is not registered and nothing sends it; once the
  capture night records that burst, it joins `by_id` or `by_code` as a companion under ADR-0013.
- **W67. The canary replays twenty-two reads, three doctor literals followed, and `post --by-id`
  follows `profile --by-id`.** Ruled 2026-09-27 for E2 batch 4. `READ_QUERIES` gained the five
  queries, so a live doctor run goes from at most 19 paced requests to at most 24. The comment
  page step now learns the first comment whose `reply_count` is above zero, the replies step is
  keyed on it and skipped without one, the replies' next page is keyed on the first page's cursor
  and skipped without one, the likers and the post by media pk are keyed on the timeline's first
  post, and the strip on that post's author, which the timeline step now learns. W48's pattern.
  `tests/test_doctor.py` followed in three literals, each seen red before the edit and green
  after: the registry count, 36 to 41 (`assert 41 == 36`), the dry run's paced total, 19 to 24
  (`assert 24 == 19`), and the stated plan, 17 reads to 22. Its comment page answer moved from an
  empty page to the recorded one, since an empty page now skips two reads, and the five new
  reads answer from the batch's fixtures. A new gate holds the replies to the first comment with
  replies on a page whose first comment has none, the next page to the first page's cursor, the
  strip to the timeline post's author, and both reply steps to being skipped when no comment has
  replies. The commands are `dumpsta replies PK COMMENT_ID` with `--pages` and `--after`,
  `likers PK` and `more-from-author AUTHOR_ID`, and `post --by-id PK`, a flag on the existing
  command as `profile --by-id` is, which refuses a shortcode with exit 2. The gate fixtures are
  the recorded answers, pseudonymised by `scripts/build_post_depth_fixtures.py`, with the home
  page trimmed to its six post edges. `tests/test_post_depth.py` holds 23 gates and
  `scripts/verify_post_depth_gates.py` 51 mutations, each seen red then green. Seven anchors in
  `verify_comments_gates.py` and `verify_likes_gates.py` that the new mappers and builders had
  made ambiguous were lengthened. The surface grew from 636 lines to 681, 45 added and none
  removed or changed. Live traffic for the discovery: `probes/e2_post_depth.py` 13 requests and
  the replies half of `probes/e2_next_pages.py`, 4 of its 10. The CLI acceptance,
  `probes/e2_post_depth_cli_acceptance.py`, ran on 2026-09-27 with every step exit 0 and 11 requests, after a first run stopped at `post --by-id` on a reel and led to W63's original sound gap: 94 likers, 1 reply on one page, the reel by pk with 2 user tags, and 6 posts from its author, log
  `logs/e2-post-depth-cli-2026-09-27-033207.json`, six of them `dumpsta feed` under parity.
- **W68. `client.stories` ships its reads now, without the seen mutation, amending W42.** Ruled
  2026-09-27 by the orchestrator on the owner's delegation, for E2 batch 5. W42 held the whole
  namespace until `PolarisStoriesV3SeenMutation` was verified on the owner's own story in an
  arranged run, which needs the owner to post a story from his phone. The read queries mark
  nothing (INFERENCE recorded in W42: the browser sends the seen mutation separately for each
  item it shows, which would be redundant if the read had marked it), so shipping the reads
  without the mutation cannot put the viewer in anyone's seen list, while holding them blocked
  the E2 stop condition's "a story" render. So the reads send no seen marking, a named departure
  from W6 until the arranged run of batch 12 verifies the mutation; `mark_seen` and
  `Behavior.mark_stories_seen` do not ship in this batch and arrive with that run, when the
  default becomes W6's parity. The docstrings on `client.stories`, `docs/public-api.md` and
  `docs/web-request-contract.md` say that reading a story through the engine today does not mark
  it seen. Nothing registers or sends `PolarisStoriesV3SeenMutation`,
  `PolarisAPIReelSeenMutation` or `PolarisAPIForceStorySeenMutation`, and
  `test_no_stories_method_sends_a_seen_mutation_and_the_registry_holds_none` holds it: every
  stories method sends only its read query, none named a mutation, and no registry name
  contains `Seen`, seen red under two mutations (a second request beside the reel's query, and
  a seen mutation registered among the writes). W42's rule about the W30 partner stands for
  acceptance runs: his stories are never read. **Closed 2026-09-27 by W93 and W94:** the
  mutation is verified, `mark_seen` and `Behavior.mark_stories_seen` ship, the default is W6's
  parity again, and the gate named above is retired for the W94 gates.
- **W69. The tray is `stories.tray() -> tuple[TrayReel, ...]`, a model of its own.** Ruled
  2026-09-27 for E2 batch 5. `PolarisStoriesV3TrayContainerQuery` (finding
  `page-load-stories-tray`, a verified companion, replayed in run `run-2026-09-27-014102` with
  roots `ayml`, `xdt_api__v1__feed__reels_tray` and `xdt_viewer`, 33 reels) with the variables
  every page load sends, on `/api/graphql`. FACT over the 33 rows: each carried `id`, equal to
  its owner's `pk` on all 33, `reel_type` `user_reel`, `latest_reel_media`, `expiring_at`
  exactly 86400 s later, `seen` (0 on 23), `ranked_position` 1 to 33, `muted`,
  `has_besties_media` and a `user` of `pk`, `id`, `username`, `profile_pic_url` and
  `hd_profile_pic_url_info`, and no items. So a row is `TrayReel` rather than a `StoryReel`
  with no items: `id`, `reel_type`, `owner` (`StoryOwner`, whose verified and private flags are
  `None` here because the row does not carry them), `latest_item_at`, `expiring_at`,
  `ranked_position`, `muted`, `has_close_friends_items` and `seen_at`, `None` where `seen` was
  0 (INFERENCE that 0 means nothing seen). Dropped, listed on the mapper:
  `latest_besties_reel_media`, which was a time on rows whose `has_besties_media` was false,
  the wearables fields, zero or empty on all 33, `seen_ranked_position`, equal to the rank on all
  33, the owner's repeats of the row, the empty `broadcasts`, and the `ayml` suggestions the
  variables ask to show none of. The tray has no cursor, so the tuple is the tray as sent.
  `STORIES_TRAY` moved from `COMPANION_QUERIES` to `READ_QUERIES`, as `PROFILE_HIGHLIGHTS` did in
  W54, and every non-home page load still sends it unread. Departure: sent alone, with the site
  root as referer, where a browser reads it inside a page load.
- **W70. One account's live stories are `stories.reel(user_id) -> StoryReel | None`, one
  highlight is `stories.highlight(highlight_id) -> StoryReel`, and a story item is `StoryItem`.**
  Ruled 2026-09-27 for E2 batch 5. Both send `PolarisStoriesV3ReelPageStandaloneQuery` (finding
  `read-one-account-s-stories-or-a-highlight`) on `/graphql/query` with root
  `xdt_api__v1__feed__reels_media`: a reel with `reel_ids_arr` of the account id and the
  community note provider true, a highlight with `reel_ids_arr` of its `highlight:<number>`,
  `is_highlight` true and the provider, the probe's variables. FACT: the owner's highlight
  answered one reel of 18 items twice, `reel_type` `highlight_reel`, and the owner's own reel
  answered an empty `reels_media` once, 333 bytes, because he had no live story. So `reel`
  returns `None` on an empty answer, `highlight` raises `NotFound` on one (INFERENCE, a missing
  highlight was never read), and more than one reel for one id raises `SchemaChanged`. A live
  story item was never observed; a highlight's items are story items, and a live reel's items
  are ASSUMED to share their shape, which the docstrings say, as is a live reel's `reel_type`
  `user_reel`, INFERENCE from the tray. `StoryReel` carries `id`, `reel_type`, `owner`
  (`StoryOwner` with `is_verified` and `is_private` and no high resolution picture, which the
  reel's user does not carry), `latest_item_at`, `can_reshare`, `items`, and `title` and
  `cover_url` where the reel carries them, as a highlight does; `seen` and `muted` were null and
  are not modelled. `StoryItem` carries, FACT over the 18 items: `id` as `<pk>_<owner id>`,
  `pk`, `code`, `owner_id` from the item's own `user`, `media_type` (17 videos, 1 photo),
  `product_type` `story`, `taken_at`, `expiring_at` (86400 s later on 17, 45 s on one),
  `original_width` and `original_height`, `can_reply`, `can_reshare`, `is_paid_partnership`,
  `is_story_edited`, `images` as E1's `MediaImage`, `videos`, `video_duration` read from the
  item's own float rather than a manifest, `has_audio` (null on the photo), `audience`
  (`besties` on 2, null otherwise), `mentions` from the four bloks stickers, each an
  `ig_mention` with `username` and `full_name` and a position and size of zero, so neither is
  modelled, and `music` from the eleven music stickers, each a title, a display artist and a
  mute flag. A story video rendition carried `url` and `type` and no width or height on all 51,
  so it is the new `StoryVideo(url, version_type)` rather than E1's `VideoRendition` with
  dimensions guessed; `media.download` is typed for `MediaImage | VideoRendition`, a frozen
  snapshot line, so a story image downloads through it and a story video has no typed download
  yet. Links, locations, hashtags, polls, questions, sliders, countdowns and the caption were
  null on every item, so none is modelled; `viewers` was an empty list on every item and is not
  modelled, since where it is not empty it lists other people. A username raises `ValueError`
  before anything is sent, and so does a highlight id not in the `highlight:<number>` form
  `Highlight.id` carries. Departure: each is sent alone with the site root as referer, where a
  browser opens the story viewer, and with no seen mutation after it (W68).
- **W71. The stories gallery backs no capability and is not sent.** Ruled 2026-09-27 for E2
  batch 5. `PolarisStoriesV3ReelPageGalleryQuery` (finding `read-the-stories-gallery`, replayed
  twice) with `reel_ids` of up to three of the owner's highlight ids, `initial_reel_id`,
  `first` 3, `last` 2 and `is_highlight` true answered on root
  `xdt_api__v1__feed__reels_media__connection` one edge whose node is the standalone query's
  reel key for key plus `__typename` and `unviewable_authors_infos`, with a null edge cursor and
  `has_next_page` false. FACT from the two answers: it carries nothing `highlight` does not, it
  was only read over highlights, never over several accounts' reels, and its next page query
  never answered, so a `stories.reels(user_ids)` built on it would rest on an unobserved shape
  and a pagination nothing verified. It is the story viewer's companion, whose burst has not
  been captured, so it is not registered and nothing sends it; it joins `reel` as a companion
  under ADR-0013 once the capture night records the viewer.
- **W72. The canary replays twenty-four reads, three doctor literals followed, and the commands
  are `stories-tray`, `story` and `highlight`.** Ruled 2026-09-27 for E2 batch 5. `READ_QUERIES`
  gained the tray, moved from the companions, and the reel query, so a live doctor run goes from
  at most 24 paced requests to at most 26, and the companions checked by artifact from 9 to 8.
  The highlights tray step now learns the viewer's first highlight, and the reel step reads that
  highlight, keyed on it and skipped without one, so the canary never reads another account's
  story. W48's pattern. `tests/test_doctor.py` followed in three literals, each seen red before
  the edit and green after: the registry count, 41 to 42 (`assert 42 == 41`), the dry run's paced
  total, 24 to 26 (`assert 26 == 24`), and the stated plan, 22 reads to 24. The two new reads
  answer from the batch's fixtures, and a new gate holds the reel step to the viewer's first
  highlight with the highlight flag and to being skipped without one. One anchor in
  `scripts/verify_profile_tabs_gates.py` followed the highlights step's mapper call into
  `_learn_first_highlight`, the same defect on the new line. `ARGUMENT_FOR_PARAMETER` in
  `tests/test_facade_parity.py` gained `highlight_id` and the core table the three methods. The
  commands are `dumpsta stories-tray`, `story USER_ID` and `highlight HIGHLIGHT_ID`, text and
  JSON: `story` names one account's live reel in the singular the website's "story" uses,
  `stories-tray` keeps the tray apart from `highlights`, the profile's highlights tray, and
  `highlight` reads one entry of that tray. `story` refuses a username and `highlight` a bare
  number, with exit 2. The gate fixtures are the recorded answers, pseudonymised by
  `scripts/build_stories_fixtures.py`, 436 values checked absent. `tests/test_stories.py` holds
  11 gates and `scripts/verify_stories_gates.py` 42 mutations, each seen red then green. The
  surface grew from 681 lines to 767, 86 added and none removed or changed. Live traffic for the
  discovery: `probes/e2_stories.py` 8 requests. The CLI acceptance,
  `probes/e2_stories_cli_acceptance.py`, reads the tray, the owner's own reel and his first
  highlight through `dumpsta highlights` then `highlight`, four requests, and no other account's
  reel; it ran on 2026-09-27 with every step exit 0 and 4 requests, each a read query and none a seen mutation: 33 tray reels, no live reel of the owner's, 1 highlight and its 18 items, log
  `logs/e2-stories-cli-2026-09-27-035531.json`.
- **W73. The pending follow requests are `account.follow_requests() -> FollowRequests`, the
  first page with the upstream's more flag, and they open the `account` namespace.** Ruled
  2026-09-27 for E2 batch 6. `GET https://www.instagram.com/api/v1/friendships/pending/` (finding
  `pending-follow-requests`, verified twice in run `run-2026-09-27-014102`) with the follow list's
  header set of W58 and the direct inbox as referer, as `probes/e2_own_account.py` sent it through
  `E2Replay.rest`. FACT over both answers: status `ok`, one user, and the keys `big_list` false,
  `page_size` 1, `next_max_id` null, `friend_requests` an empty object, `sections` and
  `global_blacklist_sample` null, `suggested_users` with no suggestion,
  `truncate_follow_requests_at_index` and `follow_ranking_token`. The list pages in the followers
  family's way, since it carries `next_max_id`, but no next page was observed, so under W45 it
  ships as the first page only: `FollowRequests(accounts, has_more)`, `has_more` true when
  `next_max_id` is present and not null (INFERENCE from the followers list, where a cursor came
  with every page that said more), rather than the plan's bare tuple, which could not say it was
  cut short. `big_list` is not the flag, since a big list and a further page are different claims.
  The row is batch 3's `ProfileSummary` through batch 3's mapper, except that `pk` is a number
  here where the followers list sends a string, so `parse_profile_summary` gained an `id_key`
  parameter and this read names `id`, the same value as a string on both rows. A row carries no
  relationship, so `friendship_status` is `None`. The GET carries no page token, so it spends no
  bootstrap, as the followers page does. The `account` namespace opens with this and W74's read
  on both clients with no flat twin, under W1 and W20. Departure: sent alone from no page, where
  the browser sent it inside its direct inbox load.
- **W74. The activity feed is `account.activity() -> ActivityFeed`, one read that marks nothing
  seen.** Ruled 2026-09-27 for E2 batch 6, the seen marking by the orchestrator on the owner's
  delegation. `POST https://www.instagram.com/api/v1/news/inbox/` (finding `activity-feed-inbox`,
  verified twice) with only `fb_dtsg` and `jazoest` in the body, in that order, as the replays
  sent it and as both answered; the browser's body was 110 bytes whose field names the capture
  did not keep. Headers are W73's with the three a form POST adds. FACT over both answers, 264 KB
  each: status `ok`, `new_stories` and `priority_stories` empty, 69 `old_stories`, newest first,
  `counts` of fifteen zero counters, `last_checked`, `is_last_page` true, `continuation_token` 0,
  `subscription` null, and `partition.time_bucket` pairing five headings with five indices. So
  the model is `ActivityFeed(new_items, earlier_items, priority_items, counts, sections,
  last_checked_at, is_last_page)` with an `items` property joining the three lists, priority, new
  and earlier, an ASSUMPTION about the page's order. New and priority items were never read and
  are ASSUMED to share the earlier items' shape, as W70 assumed of a live reel. No pagination
  ships, since no next page request was observed, and `is_last_page` is carried. An
  `ActivityItem` is built only from what the 69 carried: `pk` as `id`, `notif_name` as `kind`
  (nine kinds, 41 story likes, 9 post likes, 8 follows, 6 comment likes and one each of a
  follow request, a comment mention and three notices), `story_type`, `args.timestamp` as
  `created_at`, `args.text` as `text`, `args.links` as `ActivityLink(start, end, kind, id,
  username)`, where `text[start:end]` was the username on all 116 and `type` was `user` on
  every one, `args.media` as `ActivityMedia(id, shortcode, image_url)`, zero or one per item,
  and where carried the main account's id, username and picture (67), the second account's id
  and picture (50), the follow button's account as a `ProfileSummary` with its relationship (9),
  a `comment_id` (1) and the upstream's app route as `destination` (68). Dropped, listed on the
  mapper: `rich_text`, which is `text` with each link written in as markup on all 69, `images`,
  equal to `media` on all 69, `type`, one per `story_type`, the follow button's own three flags,
  which repeat the relationship, the menu of extra actions, the story ring, the icons, and the
  tracking fields. `ActivityCounts` names the fifteen counters; which event moves which was not
  observed, since all were zero. The seen marking: a browser's inbox load followed the feed with
  `POST https://www.instagram.com/api/v1/news/inbox_seen/` (finding `activity-feed-mark-seen`,
  hypothesis, observed once, empty body), which clears the viewer's own badge and nothing another
  person sees. It has never been sent or observed answering, so `account.activity()` reads
  without marking seen, a named departure from ADR-0013 parity until a verified finding exists,
  in the style of W68, and no `Behavior` setting for it ships yet. Nothing in the engine builds
  that request, and a gate holds `activity` to its one POST. INFERENCE: the read itself may
  record a check, since the second replay answered a `last_checked` falling on the first
  replay's send, inside the probe's 17 s run, where the first answered one 26 minutes older;
  nothing else is known to have been sent then. The feed's text names other accounts and quotes
  comments, so `scripts/build_account_fixtures.py` rebuilds each line from its links, the
  pseudonymous username inside each span and every other letter and digit masked, keeping every
  offset true. Departure: sent alone from no page with the inbox as referer, where the browser
  sent it inside its direct inbox load.
- **W75. Saved collections do not ship, and wait for a non-empty observation.** Ruled 2026-09-27
  for E2 batch 6 by the orchestrator on the owner's delegation. `PolarisSavedCollectionPickerQuery`
  (finding `read-saved-collections`) was verified twice with `first` 12 and `after` null, but the
  owner has no collection, so both answers were empty: root `viewer`, 230 bytes, no edge,
  `has_next_page` false. A collection row was never seen, and a model cannot be built from an
  empty list without guessing its fields, so neither `account.collections` nor its iterator
  ships. It waits for a read of a non-empty list, beside saved posts, the archive, the close
  friends and blocked lists and the notifications badge, which wait on the capture night, and the
  GraphQL activity view, which is lazy and capture first.
- **W76. The doctor does not replay the account reads, and the commands are `follow-requests` and
  `activity`.** Ruled 2026-09-27 for E2 batch 6. Neither read has a `doc_id`, so the canary does
  not replay them, W60's rule, and `REPLAY_STEPS`, `tests/test_doctor.py` and the doctor's counts
  are unchanged. The commands are `dumpsta follow-requests` and `activity`, text and JSON, both
  taking no argument since both read the viewer's own account. The gate fixtures are the recorded
  answers, pseudonymised by `scripts/build_account_fixtures.py`, 678 values checked absent.
  `tests/test_account.py` holds 17 gates and `scripts/verify_account_gates.py` 31 mutations, each
  seen red then green. `tests/test_facade_parity.py` gained the two methods in its core table.
  The surface grew from 767 lines to 850, 83 added and none removed or changed. Live traffic for
  the discovery: `probes/e2_own_account.py` 7 requests. The CLI acceptance,
  `probes/e2_own_account_cli_acceptance.py`, runs both commands on the owner's own account, two
  requests, four at most, and checks from the counter's log that each sent exactly one API
  request; it ran on 2026-09-27 with both steps exit 0 and one API request each, so no `news/inbox_seen` went out: 1 follow request, 69 activity items and `is_last_page` true, log
  `logs/e2-own-account-cli-2026-09-27-042111.json`.
- **W77. The explore grid is `feeds.explore() -> ExploreGrid`, the first page only, its posts
  read from the REST media shape.** Ruled 2026-09-27 for E2 batch 7. `GET
  https://www.instagram.com/api/v1/discover/web/explore_grid/` (finding `read-the-explore-grid`,
  verified twice in run `run-2026-09-27-014102`) with the five parameters of the recorded browse,
  `include_fixed_destinations` true, `is_nonpersonalized_explore` false, `is_prefetch` false,
  `module` `explore_popular` and `omit_cover_media` false, on W58's header set with `/explore/`
  as referer. It carries no page token, so it spends no bootstrap. FACT over both answers, 1.09 MB
  and 1.28 MB: status `ok`, `more_available` true, `next_max_id` `"0"`, a 276 character `max_id`
  and `session_paging_token`, a 36 character `rank_token`, one `explore_all` cluster, and four
  `sectional_items`, each with `feed_type` `clips`, a `layout_type` of `one_by_two_right` or
  `one_by_two_left`, and a `layout_content` of exactly two blocks, `one_by_two_item.clips` with
  one reel in `items` and four `fill_items`, so 20 posts per answer. No next page was asked for,
  so under W45 the read is the first page with `more_available` carried and no cursor. The
  parameters a next page sends are not observed; INFERENCE, `max_id`, `session_paging_token` and
  `rank_token` would go back, and nothing sends them. The model is `ExploreGrid(sections,
  more_available)` with a `posts` property, each section's featured posts first, and
  `ExploreSection(feed_type, featured, posts)`; the layout, the column counts and the large
  tile's cluster fields are presentation and are dropped. The posts are `Post`, since every item
  carries a full media node, but in the REST shape, which differs from the timeline's GraphQL
  node by leaving keys out where that node sends null. Over the 40 posts of both answers, 37
  reels, 2 photos and 1 carousel: `is_seen` was absent on all 40, `accessibility_caption` on the
  37 reels, `carousel_media` and `carousel_media_count` on the 39 that are not a carousel, and
  `clips_metadata`, `has_audio`, `video_versions` and `video_dash_manifest` on the 2 photos and
  the carousel, and each of the carousel's 16 photo slides lacked `video_versions` and
  `video_dash_manifest`. Those eight keys, `REST_KEYS_ABSENT_AS_NULL` in
  `parse/discovery.py`, read as null when absent, and any other key the post mapper needs still
  raises when it is missing. `is_seen` then reads False, W53's reasoning, since the grid is not a
  feed the viewer has seen things in. `location` and `usertags`, absent on 35 and 34, read as not
  carried, `None`, as on every post read; on this shape absence may mean none (INFERENCE). Every
  other key the mapper reads was present with the timeline's types, the author's `full_name` and
  high resolution picture included, and each reel's manifest duration matched the node's own
  `video_duration` to a tenth of a second, which a gate holds. A section carrying a block other
  than the two raises `SchemaChanged` rather than dropping its posts, the `FeedItemKind` rule, so
  a layout not yet seen fails the read (ASSUMPTION that other layouts exist; none appeared in
  eight sections). Departure: sent alone with `/explore/` as referer, where a browser reads it
  inside that page's load.
- **W78. A place's header is `feeds.place(location_id) -> Place`, and `search` does not open for
  it.** Ruled 2026-09-27 for E2 batch 7. `PolarisExploreLocationsContainerQuery` (finding
  `read-a-location-s-info`, replayed twice, 521 bytes each) with `location_id_str` and
  `show_nearby` false, on `/api/graphql` with the place's page, `/explore/locations/<pk>/`, as
  referer. FACT over both answers, the same place: root `xdt_location_get_web_info` whose
  `native_location_data.location_info` carried `name`, `phone`, `category`, `media_count`,
  `price_range`, `lat`, `lng`, `slug`, `location_id`, `location_address`, `location_city`,
  `location_zip`, `ig_business.profile` null and `hours.status` an empty string. The model is
  `Place(id, name, category, lat, lng, media_count, slug, address, city, zip_code, phone,
  price_range)`, the strings as sent, empty ones included (the city, zip code and phone were
  empty); `ig_business` and `hours` are dropped, since only their empty forms were seen. It is a
  new model rather than batch 4's `Location` extended: `Location` is a post's tag, four fields
  present on all 39 read, and the header carries eight that no post's location does, which would
  be `None` on every post. The plan named `search.place`. The header is not a search and is read
  from the same page as the grid, so both place reads sit on `feeds`, and `search` still opens
  with batch 8's first search under W20. The id is digits only, refused before sending. One place
  was read, a country-level one, so a business's `ig_business` and `hours` are unobserved.
- **W79. A place's grid is `feeds.location(location_id, *, tab=LocationTab.RANKED) ->
  LocationPosts`, the first page only, and its posts are `PostThumbnail`.** Ruled 2026-09-27 for
  E2 batch 7. `PolarisLocationPageTabContentQuery` (finding `read-a-location-page-tab`, replayed
  twice) on `/graphql/query` with `x-root-field-name` `xdt_location_get_web_info_tab`, variables
  `location_id`, `first` 12, `after` null, `tab` `ranked`, `page_size_override` null and the
  short drama provider false, the place's page as referer. FACT: 21 edges on both answers,
  `has_next_page` true and a 32 character cursor, a different cursor on each. The next page query,
  `PolarisLocationPageTabContentQuery_connection` (finding `read-a-location-page-tab-next-page`),
  was replayed twice on the first answer's cursor and answered twice with 24 edges and
  `has_next_page` true, but FACT: both times its `end_cursor` was the very cursor it was sent, the
  two answers held the same 24 posts, and 20 of those were already on the first page. So
  following it is not shown to read further, and a walk on it would send the same cursor for
  ever. The grid therefore ships as the first page, W45's pattern: `LocationPosts(posts,
  has_more)`, `has_more` the page's own `has_next_page`, with no cursor and no `iter_location`.
  `Page[PostThumbnail]` is not used, because it carries a cursor nothing can follow and the
  parity gate requires an iterator beside every `Page` read. The next page query is not
  registered and nothing sends it, which a gate holds. INFERENCE: the ranked grid's cursor is tied
  to a ranking session, and a browser's scroll sends something the replay did not; the capture
  night can observe it. The posts are W64's `PostThumbnail`: on all 90 nodes read, 25 distinct
  posts, the author carried no `full_name` and no `hd_profile_pic_url_info`, no node carried
  `is_seen`, and none of the 92 slides carried `product_type`, so a `Post` would need a guessed
  `PostAuthor.full_name`; `media.by_code` with the post's `code` reads the whole post. The edge
  `cursor` was null on every edge. The tab: the compiled artifact names `ranked` and `recent`,
  only `ranked` was sent, so `LocationTab` is an enum with the one member `RANKED`, which a
  verified `recent` joins as an added line, and any other value raises `ValueError` before
  sending. Departure: sent alone, where a browser reads it inside the place's page load.
- **W80. The new posts check is `feeds.has_new_posts() -> bool`.** Ruled 2026-09-27 for E2 batch 7.
  `PolarisAPICheckNewFeedPostsExistQuery` (finding `check-for-new-feed-posts`, replayed twice,
  199 bytes each) with no variables, on `/api/graphql` with the site root as referer. FACT: root
  `xdt_api__v1__new_feed_posts_exist` carrying only `new_feed_posts_exist`, false both times, so
  the method returns that flag and a true answer is unobserved. What turns it true is not
  observed; INFERENCE, a post newer than the viewer's last home load. Departure: asked alone,
  where a browser asks from the home page.
- **W81. The canary replays twenty-seven reads, three doctor literals followed, and the commands
  are `explore`, `place`, `location` and `new-posts`.** Ruled 2026-09-27 for E2 batch 7.
  `READ_QUERIES` gained the place's header, its grid and the new posts check, so a live doctor
  run goes from at most 26 paced requests to at most 29. The explore grid is REST and is not
  replayed, W60's rule. The two place steps are keyed on the first place a post names on the home
  timeline or, failing that, on the viewer's own grid, and are skipped without one; the new posts
  check needs nothing. W48's pattern. `tests/test_doctor.py` followed in three literals, each
  seen red before the edit and green after: the registry count, 42 to 45 (`assert 45 == 42`), the
  dry run's paced total, 26 to 29 (`assert 29 == 26`), and the stated plan, 24 reads to 27. The
  recorded grid the doctor's answers use carries no place, so its first post is tagged there at
  the batch's recorded place, and a new gate holds both place steps to that place and to being
  skipped without one. The commands are `dumpsta explore`, `place LOCATION_ID`, `location
  LOCATION_ID` and `new-posts`, text and JSON: `location` keeps the website's own name for the
  page, `/explore/locations/`, and `place` names the header, so neither shadows the other. Both
  refuse anything but digits with exit 2. `Client` in `_cli/commands/common.py` gained `feeds`.
  The gate fixtures are the recorded answers, pseudonymised by
  `scripts/build_discovery_fixtures.py`, the explore answers trimmed to their first section and to
  the carousel, the grid to its first four edges, 957 values checked absent.
  `tests/test_discovery.py` holds 13 gates and `scripts/verify_discovery_gates.py` 35 mutations,
  each seen red then green; one, the grid's text form dropping its first post, did not fire on
  the first run, and its gate was strengthened to check every line. `ARGUMENT_FOR_PARAMETER` in
  `tests/test_facade_parity.py` gained `location_id` and `tab` and the core table the four
  methods. The surface grew from 850 lines to 895, 45 added and none removed or changed. Live
  traffic for the discovery: `probes/e2_discovery_feeds.py` 11 requests. The CLI acceptance,
  `probes/e2_discovery_feeds_cli_acceptance.py`, reads the explore grid, then the header and grid
  of the first place a post on it is tagged at, or `IG_E2_LOCATION_ID`, then the new posts check,
  four requests, eight at most, and checks that no next page query went out; it ran on 2026-09-27, 4 requests, every step exit 0,
  log `logs/e2-discovery-feeds-cli-2026-09-27-045328.json`.
- **W82. The recent searches are `search.recent() -> tuple[RecentSearch, ...]`, each entry reduced
  to the one slot the upstream filled, and they open the `search` namespace.** Ruled 2026-09-27
  for E2 batch 8. `PolarisSearchNullStateQuery` (finding `read-recent-searches`, replayed twice
  in run `run-2026-09-27-014102` by `probes/e2_search.py`, 7335 bytes each) with no variables,
  on `/api/graphql` with the site root as referer. FACT over both answers: root
  `xig_recent_searches` carrying `recent_searches`, 15 entries, each an object with the four
  sibling slots `user`, `keyword`, `hashtag` and `place`, exactly one non-null on all 30. Four
  were accounts and eleven keywords, in the same order both times; `hashtag` and `place` were null
  on every entry. An account slot is a user row with `pk` and `id` equal strings, `username`,
  `full_name`, `is_verified`, `profile_pic_url` and `hd_profile_pic_url_info`, and no
  `is_private` and no relationship, so it is batch 2's `ProfileSummary` through batch 2's mapper,
  those two fields `None`. A keyword slot carried `name`, the text searched, and `id`, null on all
  22. The model follows the timeline's `FeedItem`: `RecentSearch(kind,
  account=None, keyword=None)` with `RecentSearchKind` naming all four slots the upstream declares,
  its values the slot names, so `ACCOUNT` is `"user"`. A hashtag or a place entry is carried by
  its kind with no payload rather than refused, because searching a tag or a place is an ordinary
  thing to have done and one such entry would otherwise fail the whole list, and its shape was
  never read, so a payload would be a guess; typed fields for it join as added lines once one is
  observed. An entry filling no slot or two, or a slot outside the four, raises `SchemaChanged`,
  as a timeline item does. Dropped: the row's `search_social_context` and its snippet type, a
  line of mutual followers the box prints (it names other accounts), `unseen_count`,
  `aigm_account_label_info`, `ai_agent_owner_username`, and the keyword's null `id`. The list is
  whole as sent, with no cursor or count, so there is no paging. The `search` namespace opens with
  this, W83's and W84's reads on both clients with no flat twin, under W1 and W20. Departure: sent
  alone with the site root as referer, where a browser reads it when its search panel opens.
- **W83. The non-personalised typeahead is `search.accounts(query) -> tuple[ProfileSummary,
  ...]`, accounts only, a named departure, and the personalised typeahead and keyword grid are not
  registered.** Ruled 2026-09-27 for E2 batch 8. `PolarisSearchBoxNonProfiledRefetchableQuery`
  (finding `search-typeahead-non-personalised`, replayed twice, 27538 bytes each) with `hasQuery`
  true and `query`, a nine character term, on `/api/graphql` with the site root as referer. FACT
  over both answers: root `xdt_api__v1__fbsearch__non_profiled_serp` carrying `users`, 18
  `XDTUserDict` rows with the recent searches' user keys plus `__typename`, the same accounts in
  the same order both times, and `inform_module`, null on both, and nothing else: no hashtags, no
  places, no cursor. So the execution list's `search.top(query) -> SearchResults` with accounts,
  hashtags and places does not ship, since two of its three kinds are not in this answer. The
  method is named for what it returns, `accounts`, and `top` stays free for the personalised
  typeahead, `PolarisSearchBoxContainerQuery`, whose `data` object was never observed and which
  the capture night records; its refetch and `PolarisKeywordSearchExplorePageRelayQuery`, the
  keyword grid that is also a hashtag page's grid, wait with it. None of the three is registered
  and nothing sends them, which a gate holds. The rows are `ProfileSummary` through the same
  mapper, `is_private` and `friendship_status` `None`; the row's `search_social_context` was a
  follower count string and is dropped as presentation. Departure: the census found the
  personalised query in the search box a signed-in load compiles, so INFERENCE: a signed-in
  browser typing sends the personalised query and not this one, which serves a viewer who turned
  personalisation off or is signed out. The engine sends the non-personalised one because it is
  the one verified, recorded in the namespace's docstring and in `web-request-contract.md` until
  the capture night observes what the box sends. An empty or blank query raises `ValueError`
  before sending, since what the typeahead answers for one is unobserved. INFERENCE, as the probe
  records it: a typed query is not added to the recent searches until a result is opened, and
  nothing is opened.
- **W84. A hashtag's header is `search.hashtag(tag) -> Hashtag`, and a tag with a `#` is
  refused.** Ruled 2026-09-27 for E2 batch 8. `PolarisHashtagHeaderActionButtonsQuery` (finding
  `read-a-hashtag-header`, replayed twice, 179 bytes each) with `tag_name`, on `/api/graphql` with
  the tag's page, `/explore/tags/<tag>/`, as referer. FACT: root `fetch__XDTTagInfo` carrying only
  `id`, a 17 digit string, the same both times. The query's name says it feeds the header's action
  buttons, but the answer carried no follow state, so `Hashtag(id, name)` carries the id and the
  tag that was asked for as `name`, which the answer does not echo; follow state and a post count
  join as added fields when a read carries them. A tag is refused with `ValueError` before sending
  unless it is one or more word characters (Python's `\w`, letters, digits and underscores in any
  script), so a leading `#` is refused rather than stripped: the tag a caller passes is the tag
  that is sent, and a `/` or `?` could not reach the referer's path. ASSUMPTION: that rule is what
  Instagram accepts as a tag; only a nine character ASCII tag was sent. The referer escapes the tag
  as an address bar does, so a non-ASCII tag is percent-encoded there and sent as is in the
  variables (INFERENCE from how browsers write a referer; no non-ASCII tag was sent). What a tag
  that does not exist answers is unobserved, and its null root would raise `SchemaChanged`, not
  `NotFound`. Departure: sent alone with the tag's page as referer, where a browser reads it inside
  that page's load, and the page's grid is not read (W83).
- **W85. The canary replays thirty reads, three doctor literals followed, and the commands are
  `recent-searches`, `search` and `hashtag`.** Ruled 2026-09-27 for E2 batch 8. `READ_QUERIES`
  gained the three search queries, so a live doctor run goes from at most 29 paced requests to at
  most 32. The recent searches need nothing. The typeahead is keyed on the viewer's own username,
  which the profile step already learns, W48's pattern, so the canary searches for nobody else.
  The hashtag header is the one step keyed on a constant, `CANARY_HASHTAG`, `instagram`, the tag
  its finding was verified with, because no earlier read yields a tag and parsing one out of a
  caption would be a guess; a constant the finding answered twice is not. `tests/test_doctor.py`
  followed in three literals, each seen red before the edit and green after: the registry count,
  45 to 48 (`assert 48 == 45`), the dry run's paced total, 29 to 32 (`assert 32 == 29`), and the
  stated plan, 27 reads to 30. A new gate holds the typeahead to the viewer's username and the
  header to the verified tag. The commands are `dumpsta recent-searches`, `search QUERY` and
  `hashtag TAG`, text and JSON; `hashtag` refuses a `#` or anything outside W84's rule and `search`
  a blank query, both with exit 2. `Client` in `_cli/commands/common.py` gained `search`. The gate
  fixtures are the recorded answers, pseudonymised by `scripts/build_search_fixtures.py`, every
  username, full name, keyword, social context line and id replaced, 141 values checked absent.
  `tests/test_search.py` holds 10 gates and `scripts/verify_search_gates.py` 33 mutations, each
  seen red then green. `ARGUMENT_FOR_PARAMETER` in `tests/test_facade_parity.py` gained `query` and
  `tag` and the core table the three methods. The surface grew from 895 lines to 927, 32 added and
  none removed or changed. Live traffic for the discovery: `probes/e2_search.py` 7 requests. The
  CLI acceptance, `probes/e2_search_cli_acceptance.py`, runs the three commands, three requests,
  six at most, and checks that each sent its own query and none an unobserved search query; it
  ran on 2026-09-27, 3 requests, every step exit 0, log `logs/e2-search-cli-2026-09-27-051346.json`.
- **W86. The inbox load ships in batch 9 and the post page does not; the post page's two
  companions are not registered yet.** Ruled 2026-09-27 for E2 batch 9, the orchestrator's ruling
  on the owner's delegation. The post page document has never been captured, and a model of its
  burst without its document would be half a page load, so the post page waits for the capture
  night (batch 10) and the post, like and comment departures of `1.0.0` stay open until then. Its
  two companions were verified today, each replayed twice in run `run-2026-09-27-014102` by
  `probes/e2_page_models.py`: `PolarisPostCommentsContainerQuery` (finding
  `read-a-post-page-first-comments`) and `PolarisLikedByTextDaisyReduxQuery` (finding
  `read-the-liked-by-line`), captures `skills/reverse-engineer/var/captures/e2-page-models-2026-09-27-*`,
  log `logs/e2-page-models-2026-09-27-013957.json`. They are not registered: the companion
  registry in `documents/page_load.py` and the catalog's `COMPANION_QUERIES` hold only what the
  engine sends, since the catalog's own rule is that a companion is sent because a page sends it,
  and nothing sends these before the post page is modelled. Live traffic for the batch:
  `probes/e2_page_models.py`, 10 requests.
- **W87. The inbox page load is the parity route of `notes()`, `direct.inbox()` and
  `direct.unread_counts()`, chosen by `Behavior.inbox_route`.** Ruled 2026-09-27 for E2 batch 9.
  `InboxRoute.PAGE`, the default in every preset, loads `https://www.instagram.com/direct/inbox/`
  as a navigation, writes its tokens onto the session, and sends the ten queries of the page's
  direct block together in one paced action, followed by the load's companions (W88) when
  `page_load_companions` is on, as the home and profile routes do; `InboxRoute.QUERIES` keeps the
  single-query route of each read as the named departure, in the style of `ProfileRoute`. The
  three reads share one load because the tray, the first page and both folders' unread rows are
  all in the block, so whichever is called the whole block goes out and only its answers are read;
  every other answer is screened for a checkpoint or a throttle and otherwise left alone. The
  block's order is the recorded one, FACT, identical in both full inbox cold loads,
  `run-2026-09-23-022159` (492.2 to 496.1 ms after the document) and `run-2026-09-23-045256`
  (532.1 to 535.8 ms): automatic previews, feature limits, the unread rows for `INBOX`, the
  listing, the unread rows for `PENDING`, presence setup, the inbox interstitial, the account
  switcher, viewer settings, the tray. The six queries with no variables were verified on
  2026-09-23 and are registered now as companions, which moved the registry from 48 to 54. The
  inbox document preloads none of the block, unlike the home document and its feed: FACT, neither
  stored document (199807 of about 822000 characters each) carried an `adp_` preloader, and both
  loads asked for the four answers over XHR; INFERENCE for the unstored rest. The listing, both
  unread queries and the badge count carry the document's `IGDMqttWebDeviceID`, as both loads did;
  a document without one gets one fresh uuid4 for the whole block, because the read is what the
  caller asked for and a replay with an id no page issued answered the same, and no badge count,
  as on the other routes. Later inbox pages and the message requests stay single requests under
  both routes, since a browser sends them when its list scrolls and its requests view opens. The
  cookie sync tail is scheduled for the inbox after a read that succeeded. The listener's polls
  are unchanged. Cost under parity: 31 requests per call with a full first page, where the
  departure costs one or two. Closes the notes departure of `1.0.0` and `1.1.0`. Those release
  notes describe their releases and are left as written; the `1.2.0` notes will list it closed.
- **W88. The inbox load's companions are the badge count, the stories tray, the login
  interstitial, the thread details and the two account reads; `news/inbox_seen` is never sent,
  and five queries the plan named are not sent.** Ruled 2026-09-27 for E2 batch 9. From the first
  load, in groups: the badge count at 518.7 ms, the stories tray at 642.2, the login interstitial
  quick promotion at 849.0, the fifteen thread details at 1038.5 to 1044.2 (W89), and the pending
  follow requests and the activity feed at 3686.9 and 3687.3, sent together with one
  `x-web-session-id` and their answers unread, batch 6's builders. The second load sent the same
  up to the details (564.4, 727.7, 897.0, 1050.6 to 1070.3) and no REST read. Left out and named:
  the feed timeline prefetch at 641.1, as the profile route leaves it out; `fxcal` at 545.0 and
  the manifest, no verified finding; `news/inbox_seen` at 3685.2, an unverified write that clears
  the viewer's own badge, W74. Sending the account reads on every load is an ASSUMPTION, since one
  of two loads sent them and what triggers them is unobserved. Not sent, against the execution
  list's companion list, because the recorded loads say so: the chat tabs jewel (and the omni
  picker), absent from both inbox loads and documented as a load that is not direct; the header,
  `IGDInboxHeaderOffMsysQuery`, which its finding records only on a thread page, beside the thread
  detail of the open thread; and `useIGDShouldShowAdResponsesTabQuery` (finding
  `read-whether-the-ad-responses-tab-shows`) and `IGDThreadlineContainerQuerySuggestedQuery`
  (finding `read-suggested-threads-reels`), verified twice today, which no inbox load sent: FACT,
  absent from the two full loads and from the three inbox captures of `run-2026-09-21-034918`,
  which recorded the direct block and the thread details. The census lists them as compiled on home, inbox and location, so
  INFERENCE: each is conditional, the suggested reels on an empty threadline and the ad responses
  tab on a professional account. Neither is registered; the capture night can show what sends
  them. `IGDChatTabsContentOffMsysQuery`, the floating chat tabs twelve non-direct captures carry,
  is a census entry (`39445397375059002`) with no finding, so it does not join the home and
  profile companions and waits on a finding.
- **W89. An inbox load prefetches the thread detail of every row of its first page, pinned
  threads first.** Ruled 2026-09-27 for E2 batch 9. FACT, both loads: fifteen `IGDThreadDetailQuery`
  requests, the set equal to the fifteen rows of the first page, each carrying the row's
  `thread_key` as `thread_fbid`, null `min_uq_seq_id`, the two providers a thread open sends, and
  the inbox as referer. The order was listing positions 2, 7, 0, 1, 3 to 6, 8 to 14 in the first
  load and 1, 0, 2 to 14 in the second, and each load's `pinned_threads_v2` listed exactly 2, 7
  and 1, 0: the pinned threads in that list's order, then the other rows in the listing's order,
  which `parse_thread_prefetch_keys` reads and which accounts for all 30 positions. A pinned thread
  is not sent twice. Whether a first page longer than fifteen rows prefetches all of them is
  unobserved, and the first page has been fifteen rows on every read. `build_thread_detail_request`
  gained a `referer` keyword for it, the thread's own page staying the default. A listing that is
  refused or unreadable keys no details rather than costing the read. None of it marks a thread
  seen, which a browser does over a socket.
- **W90. Gates, the two gates that followed, and what did not change.** Ruled 2026-09-27 for E2
  batch 9. `tests/test_page_models.py` holds 16 gates on batch 1's pseudonymised fixtures and a
  synthetic document, so no fixture builder was needed, and `scripts/verify_page_models_gates.py`
  29 mutations, each seen red then green. Two gates followed the deliberate change, the W48 way:
  the registry count in `tests/test_doctor.py`, 48 to 54, seen red as `assert 54 == 48` before
  the edit and green after; and the two inbox walk gates of `tests/test_direct_read.py`, which
  hold the step from the first page query to the next page query and went red with
  `AuthenticationFailed` once the default route loaded a document, and now run under
  `inbox_route=InboxRoute.QUERIES` in their scripted behavior, green, while the page route's walk
  is gated in the new file. `scripts/verify_direct_read_gates.py` had one anchor the new core made
  ambiguous, `folder=INBOX_FOLDER`, lengthened with the line before it; that harness, the page
  load, notes and behavior harnesses ran clean after, 34, 15, 43 and 9 mutations. The doctor's
  replay steps did not change, since no new capability read exists, and it now checks fourteen
  companions by artifact. The surface grew from 927 lines to 932, `InboxRoute` with its two
  members and `Behavior.inbox_route`, none removed or changed. No command was added; `note list`,
  `inbox` and `unread` read through the load under the default behavior and their help says so.
  The request counter in `probes/cli_request_counter/` records three REST paths whole, the two
  account reads and `news/inbox_seen`, so the acceptance can show the last never went out. The CLI
  acceptance, `probes/e2_page_models_cli_acceptance.py`, runs `note list`, `inbox --pages 2` and
  `unread`, 94 requests with full first pages, 110 at most, and checks each load's block, its
  thread details against the rows listed, and that no `news/inbox_seen` was sent. Its second run, after W91, passed with every step exit 0 and 94 requests, all 200: each of the three loads sent its whole block, 15 thread details and both account reads and no `news/inbox_seen`, 10 notes, 30 threads over two inbox pages, log
  `logs/e2-page-models-cli-2026-09-27-055040.json`.
- **W91. The notes tray holds kinds beside notes, and `notes()` returns the notes only.** Ruled
  2026-09-27 for E2 batch 9, the orchestrator's ruling on the owner's delegation, after the batch's
  CLI acceptance. That run sent the whole inbox page load, 31 requests, all 200, the block
  complete, 15 thread details and no `news/inbox_seen`, and then `note list` exited 8 with
  `SchemaChanged` at `data.response.inbox_tray_items[10].inbox_tray_item_type`, "is
  'ambient_data', not a note", log `logs/e2-page-models-cli-stopped-2026-09-27-054426.json`. The
  same refusal came on `InboxRoute.QUERIES`, so it is a defect in `direct.notes()` on every route
  since `1.0.0`, not in the page load. `probes/notes_tray_shape.py`, 2 requests, found FACT: 10
  `note` items and 1 `ambient_data` item carrying `inbox_tray_item_id`, `inbox_tray_item_type`,
  `note_dict` null, and `pog_info` with `pog_style` and one pictured account (id, username, full
  name, pictures, `interop_messaging_user_fbid`), capture
  `notes-tray-shape-2026-09-27-054515-02-notes-tray.json`. `parse_inbox_tray` now skips an item
  whose `inbox_tray_item_type` is a string other than `note` and whose `note_dict` is present and
  null, since it carries no note. An item typed `note` without a note, an item of another kind that
  does carry a `note_dict`, and an item with no type still raise `SchemaChanged`, and
  `parse_created_note` is unchanged. There is no public model for an ambient item: it is not a
  note, it was seen once, and what it means is UNRESOLVED. `find_own_note` works on the notes that
  remain, and `set_note` and `delete_note` read no tray, so their reconciling read is `notes()`
  with the skip. The fixture is the live tray, pseudonymised by `scripts/build_notes_tray_fixtures.py`
  into `tests/fixtures/notes/tray_with_ambient_item.json`, 86 values checked absent. Two gates in
  `tests/test_notes.py` hold it, the skip seen red on the code before the fix, and
  `scripts/verify_notes_gates.py` gained two mutations, the skip removed and the skip widened to
  items typed `note`, 45 of 45 fired.
- **W92. A profile's clips count may be null, and it reads as 0 on the frozen field and as `None`
  on a new one, `Profile.reported_clips_count`.** Ruled 2026-09-27, the orchestrator's ruling on
  the owner's delegation, for a defect shipped since Step 17. `dumpsta profile --by-id` on account
  B (W49), read as the owner, exited with `SchemaChanged: data.user.total_clips_count is not an
  integer`; the same read as B itself answered. B has no posts and no reels, so `profiles.by_id`
  failed on any other account with no reels. The exact value B's answer carried was not kept. It
  is INFERENCE that it was null: `_required_integer` says "is not an integer" for a present value
  of any other type, and "is missing from the payload" for an absent key, so the key was there,
  and null is the likeliest non-integer an account with nothing to count sends. The mapper now
  accepts null only: an absent key, a string, a float and a boolean still raise at
  `data.user.total_clips_count`. `Profile.total_clips_count` is a frozen `int` line, so it cannot
  become optional; it reads null as 0, the model-default precedent of the three null flags in
  Step 17, and the new `reported_clips_count: int | None = None` carries the count exactly as
  sent, `None` on null, so a caller can tell "no reels" from "no count given". Whether null
  means zero reels or a count withheld from other viewers is UNRESOLVED; one account was seen.
  The fixture is the existing synthetic other-account profile of `tests/test_follows.py` with
  `media_count` 0 and `total_clips_count` null. Three gates hold it, the first seen red on the
  code before the fix with the production text, `SchemaChanged: data.user.total_clips_count is
  not an integer`, and `scripts/verify_follows_gates.py` gained four mutations (the required
  reader restored, null read as 1, the new field left unfilled, any value accepted), 26 of 26
  fired. The surface grew from 932 lines to 933, the one new field, none removed or changed. No
  live request was sent for the fix.

- **W93. Marking a story item seen is `stories.mark_seen(item, *, reel) -> None`, one write through
  `send_write`.** Ruled 2026-09-27 for E2 batch 12, the orchestrator's ruling on the owner's
  delegation. Evidence: finding `mark-a-story-seen`, verified twice in run
  `run-2026-09-27-135628`. FACT: when the owner opened his own highlight the browser sent
  `PolarisStoriesV3SeenMutation` once, 1.3 s after the document, on `/api/graphql` with no root
  field header, carrying exactly `reelId` (the highlight's `highlight:<n>`), `reelMediaId` (the
  item pk, a string), `reelMediaOwnerId` (the item owner's pk, a string), `reelMediaTakenAt` and
  `viewSeenAt` (whole seconds, integers), and the highlight's page as referer; it answered 196
  bytes, `data.xdt_mark_story_reel_seen.__typename` `XDTMarkSeenResponse`. The engine replay by
  `probes/story_seen_own_highlight.py` on the highlight's second item got the same answer, log
  `logs/story-seen-own-highlight-2026-09-27-142451.json`. W42 asked for the arranged run on a live
  story the owner posts and deletes; the verification ran on his own highlight instead, content
  whose viewer list only he sees, so W42's purpose held and nobody else was shown a viewer, but a
  live reel's mutation stays unobserved: that its `reelId` is the reel's own id, the owner's
  account id, is INFERENCE from the finding's template and the tray's rows, and a live reel's
  items are still ASSUMED to share a highlight's shape (W70). The signature takes the item and
  the reel it was read in, because the mutation needs the reel's id, which `StoryItem` does not
  carry, and the owner, pk and time posted come from the item as mapped: an item that is not in
  `reel.items` raises `ValueError` before anything is sent, so a caller cannot pair one reel's id
  with another's item or owner. `viewSeenAt` is the clock when the write is built. The write is
  `mark_story_item_seen` in `_core/writes/stories.py`, through `send_write`, so it waits out the
  write spacing, counts against the write budget, is sent once and never retried, and a
  connection failure in flight raises `OutcomeUnknown`. The answer is the only confirmation,
  since a highlight read carries no seen state, so a null root raises `UpstreamRejected` with
  code `story_not_marked_seen`, never observed, and a missing root or another `__typename`
  raises `SchemaChanged`. A live reel's seen state is the tray row's `seen_at`, the reconciling
  read after `OutcomeUnknown`. `STORY_SEEN` is registered among `WRITE_QUERIES`, so the doctor
  checks it by artifact only, never sends it, and now checks eleven writes;
  `PolarisAPIReelSeenMutation` and `PolarisAPIForceStorySeenMutation`, which no browse sent, stay
  unregistered.
- **W94. Under the default behavior a reel or highlight read marks its first item seen, and
  `Behavior.mark_stories_seen = True` is the named departure.** Ruled 2026-09-27 for E2 batch
  12. W6 makes marking the default and ADR-0013 makes a read behave as a browser's view. A browser
  marks the item it shows, one at a time, and the one open recorded sent exactly one mutation
  for the page it opened; a read returns every item at once and shows none. Marking every item
  would claim the viewer watched the whole reel, which a person opening it does not, and would
  spend one write per item against a budget of 30 an hour; marking none would keep W68's
  departure. So a read marks the first item, the one the viewer shows on opening, and
  `stories.mark_seen` marks any other, which is how a caller walks a reel the way a person taps
  through it. A browser opening a partly seen live reel starts at the first unseen item, which
  the reel read does not say, so the engine marks the first item either way, a named difference.
  **This is visible to other people: reading another account's live reel, or its highlight,
  through the engine under the default puts the viewer in that item's seen list, exactly as
  opening it on the website does.** The docstrings of `stories.reel`, `stories.highlight` and
  `Behavior`, `docs/public-api.md` and `docs/cli.md` say so. The mark is sent after the read,
  outside the read's token recovery, so a write failure never resends the read and the read's
  recovery never resends the write. When the mark fails, over the budget, after a write stop or
  on an error answer, its error is raised and the reel is not returned, because returning it
  would tell the caller a story was read in parity when it was not; reading again with
  `mark_stories_seen=False` returns the reel alone. A reel with no items, and an account with no
  live story, mark nothing. `stories.tray()` marks nothing under any behavior, as a browser's
  tray does not. Reels read back to back are spaced by the write spacing, 30 s under the
  default, where a person is faster; that is the placeholder spacing of every write and is not
  changed here. W42's W30 rule stands: the partner's stories are never read in acceptance.
- **W95. `dumpsta story` and `highlight` mark the first item unless `--no-mark-seen`, and
  `dumpsta story-seen REEL_ID ITEM_PK` marks one item.** Ruled 2026-09-27 for E2 batch 12. The
  commands follow the library default rather than departing from it, so the CLI says what the
  website does, and `--no-mark-seen` reads through a client scoped with `with_behavior` and
  `mark_stories_seen=False`, closed after the read; the CLI's client protocol gained `behavior`
  and `with_behavior` for it, which `SyncClient` already had. Their JSON carries
  `marked_first_item_seen`. `story-seen` takes an account id or a `highlight:<number>` and an
  item pk, reads the reel with marking off so the read marks nothing of its own, and marks the
  named item, two requests; a reel with no live story or no such item exits 7, `NotFound`, and a
  pk that is not digits exits 2. `stories-tray` is unchanged. `probes/e2_stories_cli_acceptance.py`
  gained `--no-mark-seen` on its two reads so a rerun stays read only as it ran.
- **W96. Gates, the harness, the doctor and the surface for batch 12.** Ruled 2026-09-27.
  `tests/test_stories.py` retired the W68 gate and gained twelve: the five variables, path,
  document and referer on a highlight and on a live reel recast from the recorded highlight; the
  membership refusal; four answer checks (a null root raises `story_not_marked_seen`, a missing
  root, another type, a string root); the write slot; the budget; one departure after a rejection
  and after a connection failure; the default marking of the first item only on a reel and a
  highlight with the tray marking nothing; marking off and an empty reel sending no mutation; a
  refused mark raising rather than returning the reel; the registration; and two CLI gates. The
  file holds 22 gates, 25 cases, all green. `scripts/verify_stories_gates.py` dropped the two W68 rows and
  gained 31, 71 mutations, 71 of 71 fired. `tests/test_facade_parity.py` gained `item` and `reel`
  in `ARGUMENT_FOR_PARAMETER` and `stories.mark_seen` in the core table. One gate followed the
  deliberate change, the W48 way: the registry count in `tests/test_doctor.py`, 54 to 55, seen
  red as `assert 55 == 54` before the edit and green after. `scripts/verify_doctor_gates.py` had
  one anchor, `PROFILE_SCHOOL_BADGE,\n)\n`, that no longer matched since the batch 9 companions
  moved the end of `COMPANION_QUERIES`, so that harness could not start; it now removes
  `VIEWER_SETTINGS`, the list's last entry, the same mutation, and ran 24 of 24. The surface grew
  from 933 lines to 936, `Behavior.mark_stories_seen` and `mark_seen` on both namespaces, none
  removed or changed. `probes/e2_story_seen_cli_acceptance.py` is written and not run: on the
  owner's own highlight only, `highlights`, `highlight` with the default mark and `story-seen` on
  the second item, five requests of which two are seen mutations, eight at most. No live request
  was sent for the batch beyond the finding's two verifications.

- **W97. The reels tab is `profiles.reels(user_id) -> ProfileReels`, its first page only, of a new
  `ReelThumbnail`.** Ruled 2026-09-27 for E2 batch 11a, the orchestrator's delegation. Evidence:
  finding `read-a-profile-s-reels-tab`, `PolarisProfileReelsTabContentQuery`, observed once in the
  browser on clicking the owner's Reels tab (`run-2026-09-27-131354`, whose window closed before
  the answer, read by one in-page replay) and replayed twice by `probes/e2_capture_replays.py
  --stage profile` in `run-2026-09-27-151121`, log `logs/e2-capture-replays-2026-09-27-151227.json`,
  8679 bytes each. The query takes the numeric account id twice, as `data.target_user_id` and
  `user_id`, and no username, so the method takes `user_id` and refuses a username with
  `ValueError` before anything is sent, as `highlights` does (W54). It answers on
  `/graphql/query` under `fetch__XDTUserDict`, the account's user node, whose `clips_connection`
  holds the reels beside `xdt_viewer`. FACT: both answers held the owner's one reel, per-edge
  `cursor` null, `end_cursor` null and `has_next_page` false. No next page was observed or
  replayed, so under W45 the read is a first page: `ProfileReels` carries `reels` and the
  upstream's `has_next_page` as `has_more`, no cursor and no `iter_reels`. An item is
  `node.media`, of `__typename` XDTClipsItemDict, and carries `pk`, `id`, `code`, a `user` of
  `pk` and `id` only, `media_type`, `product_type`, `play_count`, `view_count` null,
  `like_count`, `comment_count`, `like_and_view_counts_disabled`, `original_width`,
  `original_height` and `image_versions2`, with no caption, no username and no time. So it is
  neither `Post` nor `PostThumbnail`, which requires `author_username`, without guessing, and the
  new `ReelThumbnail` carries exactly those fields. `play_count` was a number on the one reel and
  is `int | None`, null reading as `None`, because whether other viewers see it is unobserved;
  every other field is required, from one item, which is a narrow sample (FACT, one reel, two
  answers). Dropped fields are listed on the mapper. Departures: a browser sends the tab's query
  2 ms after `PolarisProfileSuggestedUsersWithPreloadableQuery` on the click, with a bootloader
  fetch and `/ajax/navigation/`, and the engine sends the tab's query alone, as `posts` does (W53);
  the referer is the site root rather than the profile page, for W54's reason, an ASSUMPTION until
  the live acceptance.
- **W98. The tagged tab is `profiles.tagged(user_id) -> TaggedPosts`, its first page only, of
  `PostThumbnail`.** Ruled 2026-09-27 for E2 batch 11a. Evidence: finding
  `read-a-profile-s-tagged-tab`, `PolarisProfileTaggedTabContentQuery`, observed once in the
  browser on clicking the owner's Tagged tab and replayed twice in `run-2026-09-27-151121`, 54342
  bytes each. Keyed on `user_id` with `count` 12, on `/graphql/query`, root
  `xdt_api__v1__usertags__user_id__feed_connection`. FACT: both answers held four posts by other
  accounts (a reel, a carousel of two, two photos), per-edge `cursor` null, `has_next_page` false
  and `end_cursor` the four character string `None`, not null, which is why no cursor is read from
  it. No next page was observed, so `TaggedPosts` carries `posts` and `has_more`, the
  `LocationPosts` pattern of W79, and no iterator. A node carries every key of the strip item W64
  mapped and ten more (`__typename` XDTMediaDict, the original size, `longform_title`,
  `coauthor_producers`, two internal flags, `longform_clip_metadata` and two AI fields), so it is
  read by the strip's own mapper into `PostThumbnail`, the ten dropped. Its author is the account
  that posted it, never the tab's owner, which a gate holds. Captions were null on all four, so
  the caption path is exercised only by the strip's fixtures. Departures as W97.
- **W99. The following list is `profiles.following(user_id, *, after=None) ->
  Page[ProfileSummary]` and `iter_following`, the followers list's twin, and one setting governs
  both lists' statuses.** Ruled 2026-09-27 for E2 batch 11a. Evidence: finding
  `read-an-account-s-following`, `GET /api/v1/friendships/<id>/following/`, the browser's first
  page twice and its page at `max_id` 24 once in `run-2026-09-27-131354`, each followed within 0.6
  to 0.7 s by `show_many` naming exactly that page's twelve ids with the same web session id, then
  four engine replays in `run-2026-09-27-151121`: the first page twice and the next page at the
  first page's `next_max_id` twice, zero overlap with the first page on both. That meets the
  standing rule, so the read pages. The request differs from the followers page only in its path
  and in sending `count` 12 without `search_surface`, as the browser did. `next_max_id` is a
  numeric offset as a string, `12` then `24`, handed out unchanged as `end_cursor` and sent back
  as `max_id`; the terminator is `has_more`, true on every page read, so as for followers no last
  page has been read and `has_more` false ending the walk is an INFERENCE (W58). The answer is the
  followers page's keys plus `hidden_following_account_count`, 0 on all four, and the rows fit
  `ProfileSummary` unchanged, so the page mapper and the action are shared code with the followers
  read, one private helper each, with the path label naming the list in a `SchemaChanged`. FACT:
  the two engine first pages about 3 s apart held 11 of the same 12 accounts with four positions
  different, and the browser's first page about 90 minutes earlier shared 11 of 12 with the engine's, so
  the list is ranked and an offset walk can meet an account twice or skip one; nothing
  deduplicates, since dropping a repeat would hide what the upstream sent, and the docstring says
  so. The setting: `Behavior.follow_list_statuses` now governs both lists rather than a second
  setting, because the browser sends the same `show_many` after a page of either list (FACT, three
  following pages and one followers page observed) and the field's name is the follow list's, not
  the followers'; the docstring was widened and no snapshot line changed. A caller who wants the
  statuses on one list and not the other builds a second client with `with_behavior`. Departures
  are the followers read's (W58, W59): the site root as referer where the browser sent the profile
  tab it was on, and the statuses sent as soon as the page is mapped. `dumpsta following USER_ID`
  shares `followers`' page loop, options and output with `"command": "following"`. Mutual
  followers were not captured, since both followed accounts the capture night opened showed a
  count of 0, and they still wait for an account with a non-zero line; nothing for them ships.
- **W100. Gates, the canary, the harness and the surface for batch 11a.** Ruled 2026-09-27. Both
  tab queries joined `READ_QUERIES`, and the canary replays them on the viewer's own id, like the
  highlights tray, so a live doctor run goes from at most 30 reads to 32 and from at most 32 paced
  requests to 34; the following read is REST and not replayed (W60). `tests/test_doctor.py`
  followed in three literals the W48 way, each seen red before the edit and green after: the
  registry count, `assert 57 == 55`, the dry run's paced total, `assert 34 == 32`, and the stated
  plan, `'2 documents and at most 30 reads' in '... at most 32 reads ...'`. It gained the two
  recorded answers and one gate holding both steps to the viewer's id. The new
  `tests/test_profile_tabs_more.py` holds 15 gates, 17 cases, on fixtures pseudonymised by
  `scripts/build_profile_tabs_more_fixtures.py` from the engine replays and, for the statuses, the
  browser's own first page and `show_many` pair, whose redacted `pk` the builder restores from the
  row's `id`, equal on every engine row. `scripts/verify_profile_tabs_more_gates.py` holds 31
  mutations, 31 of 31 fired. The shared follow list code moved three anchors: in
  `scripts/verify_follow_lists_gates.py` the terminator anchor now names the helper's path
  argument and the setting anchor is lengthened to the followers call, and in
  `scripts/verify_profile_tabs_gates.py` the tray's flag anchor is lengthened to its return,
  since the two tab mappers repeat its line; both harnesses were rerun, the
  follow lists one 31 of 31 and the profile tabs one 43 of 43, each exit 0. The parity tables gained `reels`, `tagged`, `following` and `iter_following`. The CLI
  commands are `following`, `profile-reels` and `tagged`; the reels tab's command is not `reels`,
  which stays free for the reels feed of the capture night's reels stage. The surface grew from
  936 lines to 970, 34 added and none removed or changed. Live traffic for the batch: the profile
  stage's 10 requests on 2026-09-27, the bootstrap and the owner's profile included, and no other;
  `probes/e2_profile_tabs_more_cli_acceptance.py` is written, six requests on the owner's own
  account, nine at most, and ran on 2026-09-27 with every step exit 0 and 6 requests, the site root referer answering all three reads: 1 reel, 4 tagged posts, 24 accounts followed over two pages with no overlap, log
  `logs/e2-profile-tabs-more-cli-2026-09-27-160153.json`.
- **W101. The reels feed is `feeds.reels(*, after=None) -> Page[Post]` and `iter_reels`, its
  cursor carries the reels its page showed, and no view report or ads pool is sent.** Ruled
  2026-09-27 for E2 batch 11b, the orchestrator's delegation. Evidence: findings
  `read-the-reels-tab-first-page` (`PolarisClipsTabDesktopContainerQuery`) and
  `read-the-reels-tab-next-page` (`PolarisClipsTabDesktopPaginationQuery`), both on
  `/graphql/query` under root `xdt_api__v1__clips__home__connection_v2`, each observed once in the
  browser in `run-2026-09-27-131354` and replayed twice by `probes/e2_capture_replays.py --stage
  reels` in `run-2026-09-27-151121`, log `logs/e2-capture-replays-2026-09-27-151307.json`. That
  meets the standing rule for both pages, so the read pages. The first page sends
  `data.container_module` `clips_tab_desktop_page`, `first` 2, `useChannelsPagination` false and
  two provider flags false, all constants; the next page sends `after`, the previous page's
  `end_cursor`, `before` and `last` null, `first` 10, and `data.seen_reels`, a JSON string, not an
  object, of `{"id": <pk>}` entries. FACT: the two first pages answered 1 and 2 reels, each with
  `has_next_page` true and a cursor; both next pages, sent on the first answer's cursor naming its
  one reel, answered 4 reels, none on the first page, 3 of 4 shared between them in a different
  order, so the feed is ranked. The terminator is `has_next_page`, true on all four, so no last
  page has been read and `has_next_page` false ending a walk is an INFERENCE. **The cursor.** The
  next page needs `seen_reels`, which only the caller's previous page knows, so a page's
  `end_cursor` is `<pk>,<pk>,...:<upstream cursor>`, the pks of every reel on that page joined by
  commas, and `reels(after=...)` splits it and refuses with `ValueError`, before anything is sent,
  anything else, as W46 joined the mailbox id into the inbox cursor; `Page.end_cursor` was already
  opaque. Which reels to name is a ruling: the browser named the reels it had played, the first
  reel only when it fetched the next page with the second in view (FACT, one observation, and the
  replay named the one reel of its first page). A caller handed a page has been shown all of it,
  so every reel of the page before is named, and only that page's, so the cursor stays bounded;
  whether the browser's list grows across pages is unobserved (INFERENCE both ways). A page of no
  reels hands a cursor naming none, sent as `[]`, unobserved. **The model.** A reel node is the
  timeline's media node with keys left out and two in another shape, so each reel is a `Post`
  through the timeline's mapper after `_reel_feed_node` states the difference: `is_seen`,
  `accessibility_caption` absent on all 11 reels read as null, so `is_seen` is False as a grid's is
  under W53; `is_paid_partnership`, absent on all 11, reads False where absent and is read where
  sent, carrying no information here; the author has `profile_pic_url_hd` rather than
  `hd_profile_pic_url_info`, so `hd_profile_pic_url` is `None`; `coauthor_producers` carried `pk`
  and `id` only on the one reel with one, so `collaborators` is `None`, not carried; and an
  original sound carried no `should_mute_audio` on any of the 8 read, so W63's rule applies and that
  reel's `audio` is `None`, where the 3 songs carried the flag and are read. `ReelThumbnail` is not
  used, because the feed's reel carries the username, caption, renditions and time it lacks.
  **Departures.** A browser on `/reels/` plays each reel and posts `/video/unified_cvc/` per played
  reel (`report-a-reel-video-view`) and asks `PolarisClipsAdsPoolQuery` for ads to place
  (`read-the-reels-ads-pool`), and loads the tab with `/ajax/navigation/` and a quick promotion
  query. The engine plays nothing, so it reports no view and asks for no ads; neither has a
  `Behavior` setting, since a view report for a reel nobody watched would be a false signal. Both
  pages send `/reels/` as referer where the browser's next page sent the reel in view,
  `/reels/<code>/`. `PolarisClipsHomeRootQuery`, the census's guess, was not sent and is not
  registered. `dumpsta reels [--pages N] [--after CURSOR]` reads pages until the terminator.
- **W102. The personalised typeahead is the default route of a search: `search.top(query) ->
  SearchResults` is new, `search.accounts` sends it too, and `Behavior.typeahead_route` keeps the
  non-profiled query as the departure.** Ruled 2026-09-27 for E2 batch 11b. Evidence: finding
  `search-typeahead-personalised-as-sent`, `PolarisSearchBoxRefetchableQuery` on `/api/graphql`,
  observed once in the browser in `run-2026-09-27-131354`, where typing into the signed-in search
  panel sent this query 630 ms after the recent searches and did not send
  `PolarisSearchBoxContainerQuery`, then replayed twice in `run-2026-09-27-151121`, 7822 bytes
  each, log `logs/e2-capture-replays-2026-09-27-151138.json`. The variables are `data` with
  `context` blended, `include_reel` the string `true`, `query`, `rank_token` empty,
  `search_session_id` a client made lowercase uuid4 and `search_surface` `web_top_search`, and
  `hasQuery` true. Each call is the first query of a search session of its own: a fresh uuid4 and
  an empty rank token, as the browser's first query after the panel opened. The answer's
  `rank_token` is what a later query of the same session would send back (INFERENCE), and since a
  typed session of several queries is not modelled it is dropped. **The model.** FACT over both
  answers: root `xdt_api__v1__fbsearch__topsearch_connection` carrying `users`, 5 rows of
  `position` and `user`, `hashtags` and `places`, empty lists, `see_more` with `preview_number` 5
  and `list`, one row of `position` and `keyword` (`name`, a numeric `id`), `inform_module` null
  and `rank_token`. So `SearchResults(results)` holds `SearchResult(kind, position, account,
  keyword)`, `SearchResultKind` naming the four lists, ordered by the upstream's `position`, 0 for
  the keyword and 1 to 5 for the accounts on both answers (INFERENCE that the box shows that order),
  then hashtag and place rows by kind alone with no position or payload, because neither shape has
  been read, the W82 rule. A null `see_more` reads as no keywords (INFERENCE, unobserved). **The
  route.** ADR-0013 makes the browser's behavior the default, and W83 named the non-profiled query
  a departure until the box was observed; it now has been. So `search.accounts(query)` sends the
  personalised query by default and returns its accounts in the box's order, and the new
  `TypeaheadRoute` with `Behavior.typeahead_route`, `PERSONALISED` by default, keeps
  `NON_PERSONALISED`, the query `accounts` sent before, as the named departure; `top` follows the
  same setting, answering accounts with no position on the departure. The surface is additions
  only: `accounts` keeps its signature and return type. What changed for a caller is the default
  answer: one measured personalised query answered 5 accounts where the non-profiled one answered
  18 for the same length of query, and a caller who wants the old list sets the route. The
  non-profiled query stays registered and replayed. The container query stays unregistered, which
  the W83 gate now holds alone. **Gates that followed** the W48 way, each seen red after the code
  change and green after the edit: in `tests/test_search.py`, `UNOBSERVED_SEARCH_QUERIES` lost the
  refetchable query and the keyword grid, and the W83 gate and the blocking twins gate now build
  their client on `NON_PERSONALISED`, the route they check (red: the personalised default sent the
  refetchable query against the non-profiled fixture); in `tests/test_facade_parity.py` the core
  table's `search.accounts` line names `read_typeahead_accounts` rather than
  `read_non_personalised_typeahead` (red: `assert ['dumpstagram...ead_accounts'] ==
  ['dumpstagram...ed_typeahead']`). **CLI.** `dumpsta search QUERY` keeps its output and reads
  `search.accounts`, now on the default route; `dumpsta search-top QUERY` prints the blended rows;
  both take `--non-personalised`. `search` was not repurposed for the top results because its JSON
  form is a contract scripts read. `probes/e2_search_cli_acceptance.py` now passes
  `--non-personalised` to its `search` step, the route it was written to check. Departures: the
  site root as referer where the browser's panel sent the page it was opened over, and one query
  per call where a person typing sends one per pause in one session.
- **W103. The keyword grid is `search.keyword(query) -> KeywordResults`, its first page only, of a
  new `SearchPost`, and it is also a hashtag's grid.** Ruled 2026-09-27 for E2 batch 11b.
  Evidence: finding `read-keyword-search-results`, `PolarisKeywordSearchExplorePageRelayQuery` on
  `/api/graphql`, observed twice in the browser in `run-2026-09-27-131354`, on
  `/explore/search/keyword/?q=<text>` and on `/explore/tags/<tag>/`, which landed on the keyword page
  for `#<tag>` and sent this query with `query` `#<tag>`, then replayed twice with the plain text in
  `run-2026-09-27-151121`, 1386918 and 1235532 bytes. The variables are `query`, and one client
  made uuid4 sent as both `search_session_id` and `serp_session_id`, with no `first` and no
  `after`; the referer is the keyword page with its query escaped, a `#` as `%23`. FACT over both
  answers: root `xdt_fbsearch__top_serp_graphql` beside `xdt_viewer`, 11 edges each, 2
  `XDTTopSerpHeaderUnit` and 1 `XDTTopSerpAccountsHCMUnit` carrying nothing but `__typename`, and 8
  `XDTTopSerpMediaGridUnit` of 3 posts each, 24 posts, `has_next_page` true, the last edge alone
  carrying a cursor. The page was not scrolled, so no next page was observed, and under W45 the
  read is a first page: `KeywordResults(posts, has_more)`, no cursor and no `iter_keyword`. A grid
  row's posts are read in order; a header or accounts row carrying anything, or a row of another
  kind, raises `SchemaChanged`, since a post it held would otherwise go missing unseen. A post
  carries `id`, `pk`, `code`, `taken_at`, an author of `pk`, `id`, `username`, `full_name`,
  `profile_pic_url`, `is_verified` and `is_private`, `media_type` (1, 2 and 8 seen), the counts,
  `like_and_view_counts_disabled`, the caption, the original size, `carousel_media_count`, the
  renditions and the DASH manifest, `has_audio` and `view_count` (set on 4 of 48), and no
  `product_type`, no `has_liked`, no `is_seen`, no audio track, no location and no tags, and its
  slides carry no kind. So it is neither `Post` nor `PostThumbnail`, which both require a
  `product_type`, without a guess, and `SearchPost` carries exactly what the grid sends, the
  author a `PostAuthor` with its picture, following and favourite fields `None`. **The hashtag.**
  The hashtag page's grid is this read with the `#`: `search.keyword("#" + tag)`, and
  `search.hashtag(tag)` stays the header, unchanged. No second method was added for the tag's grid,
  because it would be the same request under another name, and `hashtag` did not gain the grid,
  because that would change what an existing method sends. FACT that the browser sent the `#`
  form; the engine has replayed only the plain text, so the `#` form's answer shape is an
  ASSUMPTION until the live acceptance, which reads it. Departures: the grid is sent alone, where
  the keyword page's load also sends `PolarisHashtagHeaderActionButtonsQuery` 1 ms after it
  (`tag_name` empty on a keyword, the tag on a hashtag) and the page's companions; `dumpsta
  keyword QUERY` reads it.
- **W104. Gates, the canary, the harness and the surface for batch 11b.** Ruled 2026-09-27. The four
  queries joined `READ_QUERIES` and the canary replays each: the reels first page on nothing, its
  next page on the first page's upstream cursor and reels, skipped when the first page is the last,
  the personalised typeahead on the viewer's own username as the non-profiled one is (W85), and
  the keyword grid on `CANARY_KEYWORD`, `instagram`, the text its finding was verified with, the
  probe's default, since no `IG_E2_SEARCH_QUERY` was set; no earlier read yields a keyword. A live
  doctor run goes from at most 32 reads to 36 and from at most 34 paced requests to 38.
  `tests/test_doctor.py` followed in three literals the W48 way, each seen red before the edit and
  green after: the registry count, `assert 61 == 57`, the dry run's paced total, `assert 38 ==
  34`, and the stated plan, `'2 documents and at most 32 reads' in '... at most 36 reads ...'`. It
  gained the four recorded answers and one gate on the four steps' arguments. The new
  `tests/test_discovery_search.py` holds 16 gates, 23 cases, on fixtures pseudonymised by
  `scripts/build_discovery_search_fixtures.py` from the engine replays, 763 values checked absent.
  `scripts/verify_discovery_search_gates.py` holds 50 mutations, 50 of 50 fired; its first run
  had one that did not fire, a song dropped only on the reels whose sound lacked the flag, which no
  input reaches, replaced by one dropping every reel's track. Five anchors of two older harnesses
  moved: in `scripts/verify_discovery_gates.py` the absent-as-null and first edge anchors were
  lengthened, since the reels mapper repeats both shorter lines, and in
  `scripts/verify_search_gates.py` the `ACCOUNT = "user"` anchor was lengthened to its enum, which
  `SearchResultKind` repeats, and the command and namespace anchors follow the new calls; both
  were rerun, 35 of 35 and 33 of 33, exit 0, and `scripts/check_harness_exits.py` passed. The
  parity tables gained `feeds.reels`, `feeds.iter_reels`, `search.top` and `search.keyword`. The
  commands are `reels`, `search-top` and `keyword`, and `search` and `search-top` take
  `--non-personalised`. The surface grew from 970 lines to 1028, 58 added and none removed or
  changed. Live traffic for the batch: the search and reels stages' 10 requests on 2026-09-27;
  `probes/e2_discovery_search_cli_acceptance.py`, planned at seven requests and nine at most, ran on 2026-09-27, 7 requests, every step exit 0, log `logs/e2-discovery-search-cli-2026-09-27-163749.json`.

## Standing rules for every phase

- Every capability starts with a `reverse-engineer` run and a verified finding, per the
  provenance gate. Reads are replayed twice before entering the package, writes once per state
  they can leave.
- Every write ships with the read that confirms it and, where one exists, its reversal, and its
  live acceptance restores the starting state (ruling 24).
- Every new public name is a snapshot diff a human reads. Nothing is removed or changed.
- Discovery is budgeted. A phase's live request budget is set when it opens, and a night's
  browser discovery stops at the ruling 23 cap. Counts below are HYPOTHESIS until each run
  measures them.
- An item that turns out to need another account during discovery moves to E6 rather than
  borrowing one.

## E1, 1.1.0: foundations for breadth, then posting

The owner ruled on 2026-09-23 (ruling 8) that posting ships as `1.1.0`. E1 keeps that and puts the
structural work before it, since posting is the first capability that needs the media model and
the per-domain layout.

1. **Debt first.** Remove the `bootstrap.py:134` comment (W4). Move the poller onto
   `newer_than_message_id`, which Step 21 found honoured on a live base. Done 2026-09-23:
   the comment is removed (W4, W11) and the poller sends the base on every page of a known
   thread's read back (W10), gated by three new gates in `tests/test_poller.py` under four new
   mutations in `scripts/verify_poller_gates.py`.
2. **Operation census.** Run `driver/scout_operations.py` on each page type the website has (home,
   explore, reels, profile, post, stories, direct inbox, thread, notifications, search, saved,
   settings, hashtag, location, audio). It fires nothing and lists every compiled operation with
   its `doc_id`. The output is `knowledge/census.md`: every operation, the user action it belongs
   to, its engine status, and whether it needs a second account. This is the denominator for 1:1,
   and every later phase is scoped from it. Cost is about 15 page loads of browser traffic.
   Done 2026-09-23 in `run-2026-09-23-190729`, 13 page loads and 0 engine requests: 265
   operations, 20 of them backing a capability, 7.5 percent, with the counts in
   [coverage.md](coverage.md) (W12, W14). Logging out moved to E6 (W13).
3. **Per-domain layout.** Split `requests.py`, `parse.py`, `documents.py` and `_cli/main.py` into
   one module per domain, matching the W1 namespaces. Private only, no surface change. The
   mutation harness anchors move with the code, and every harness is rerun red then green.
   Done 2026-09-23, 0 live requests: `_private/web/documents/`, `requests/` and `parse/`,
   `_cli/commands/` and `_cli/render/` are packages of `direct`, `feed`, `media`, `profiles`,
   `social` and `notes` modules plus a `common.py`, with `page_load`, `session` and `events` where
   W16 says, and no module over 483 lines outside `aio.py` (W18). Every importer names the domain
   module (W15). `tests/public_surface.txt` is unchanged, the suite is still 685 passed, and all
   28 harnesses exit 0 with 464 of 464 mutations red then green, 186 of them on anchors that
   moved (W17). Log `engine/logs/harness-sweep-2026-09-23-194421.txt`.
4. **Namespaces.** The W1 namespace objects on both facades, with aliases for the 24 existing
   methods, and the parity gate extended to walk them.
   Done 2026-09-23, 0 live requests and 0 page loads: `client.direct`, `client.feeds`,
   `client.media`, `client.profiles` and `client.social` on both clients, with an alias for each
   of the 17 flat capabilities (W19, W20, W21), from `dumpstagram/namespaces/`. The snapshot grew
   from 397 lines to 467, 70 added and none removed or changed. `tests/test_facade_parity.py`
   walks the namespaces and holds every flat method and its alias to the same requests and the
   same outcome on a recording transport, on both surfaces, and each alias to its `_core`
   function; `verify_parity_gates.py` grew from 13 mutations to 26, all red then green (W22).
5. **Pagination iterators.** `iter_*` companions over every `Page` read, terminating only on
   `has_next_page`, paced like any read, with an explicit `limit`.
   Done 2026-09-23: `client.direct.iter_messages`, `client.feeds.iter_home` and
   `client.media.iter_comments` on both clients, with a required item `limit` (W23), on the
   namespaces only (W24). The snapshot grew from 467 lines to 473, 6 added and none removed or
   changed. `tests/test_iterators.py` and five new gates in `tests/test_facade_parity.py` (W25)
   were each seen red under the 20 mutations of `scripts/verify_iterator_gates.py`, then green.
   Live check `probes/iter_home_two_pages.py`, 2 engine requests and 0 page loads: `limit=16`
   read a first page of 15 items and a second page by a 1188 character cursor 3.7 s later, and
   stopped at the sixteenth item without a third read. Log
   `engine/logs/iter-home-two-pages-2026-09-23-210259.json`.
6. **Complete media model.** Video renditions, carousel children, audio, dimensions and durations,
   plus `client.media.download(rendition, path)` over the CDN. CDN fetches may run concurrently
   under the existing ADR-0001 exception. Needs one feed shape probe that lands on a reel and a
   carousel.
   Done 2026-09-23: `VideoRendition`, `MediaAudio`, `AudioKind` and `CarouselChild`, five new
   fields on `Post` and `PostDetail`, and `client.media.download` on both clients (W26 to W29).
   Evidence, 0 browser page loads: `probes/media_shape.py`, three runs, 10 API reads and 3 CDN
   fetches, logs `engine/logs/media-shape-2026-09-23-212358.json`, `-212550.json` and
   `media-shape-post-detail-2026-09-23-212705.json`; the live acceptance
   `probes/media_download_live.py`, two runs of 1 API read and 1 CDN fetch each, logs
   `engine/logs/media-download-live-2026-09-23-214329.json` and `-214350.json`. In all 12 API
   reads and 5 CDN fetches. Finding `cdn-media-rendition-download`, verified 4 times. The snapshot
   grew from 473 lines to 520, all additions. `tests/test_media_model.py` and
   `tests/test_downloads.py` were each seen red under the 43 mutations of
   `scripts/verify_media_gates.py`, then green. No video slide in a carousel was seen, so that
   case rests on a fixture built from a live reel.
7. **Rotation canary.** `dumpsta doctor` replays each verified read finding once, compares the
   `doc_id` the current bundle compiles against the stored one, and reports drift. Writes are
   checked by artifact only, never fired. Runs on demand, never in the suite.
   Built and gated offline 2026-09-23, 0 live requests: `dumpsta doctor`, a dry run unless
   `--live`, loads the inbox and home documents, reads the bundles they name on
   `static.cdninstagram.com` for each operation's `doc_id`, replays the ten capability reads once,
   and checks the ten companions and ten writes by artifact only (W31 to W33). Exit 12 on drift,
   13 on a failed replay. `tests/test_doctor.py`, 17 gates, every one but a positive control red
   under the 24 mutations of `scripts/verify_doctor_gates.py`, then green.
   Run live 2026-09-24, 18 requests carrying the session, 152 cookieless bundle fetches and 0 page
   loads. `probes/doctor_bundle_host.py`, 1 document and 2 bundles: the home document named 556
   bundles, both fetched 200 with no cookie sent and none set, and the finding
   `static-js-bundle-fetch` gained its first engine verification. Log
   `engine/logs/doctor-bundle-host-2026-09-24-001812.json`. Then `dumpsta --json doctor --live
   --bundle-limit 150`, exit 12: 2 documents, 682 bundles named, 150 fetched and 0 failed, all 10
   reads replayed ok. Of 30 operations 14 read `ok`, 14 `missing` and 2 `drift`, both reads:
   `PolarisFeedRootPaginationCachedQuery_subscribe` and `PolarisProfilePostsQuery` compiled new
   ids while the stored ones still answered, and E2 preparation's bundle read at 23:14 the night
   before had still compiled the stored ones. Output
   `engine/logs/doctor-live-2026-09-24-001836.json`. Both reads moved to the compiled ids after two
   engine replays each through their own builders and mappers, `probes/doctor_drift_replay.py`,
   5 requests, the feed on a first page and the page after it, the profile posts query at count
   1 and 12, each resolving the viewer. Log `engine/logs/doctor-drift-replay-2026-09-24-002208.json`.
   Findings `home-timeline-feed-page` and `resolve-a-username-to-a-user-id` verified twice on
   the new ids. None of the 14 `missing` operations had its artifact seen
   in the first 150 bundles either; which of them the default cap of 1000 finds is unknown. After
   the move, `dumpsta --json doctor --live --bundle-limit 150` ran again on the existing session
   file, 12 requests carrying the session and 150 cookieless bundle fetches: drift 0,
   replay_failed 0, all 10 reads replayed ok, 14 `missing` as before, and both moved reads `ok` on
   their new ids. Output `engine/logs/doctor-live-2026-09-24-003205.json`, landed with `f6ae9c5`.
8. **Durable pacing ledger.** The pacer's write budget and write stop persist beside the session
   file, so separate processes on one account share them. Closes the 1.0.0 limitation.
   Done 2026-09-23, 0 live requests: `from_session_file` keeps both in `<path>.ledger` under a
   `flock`, a bare `Session` keeps them in memory (W34), an unreadable ledger refuses writes
   (W35), and `dumpsta session --clear-write-stop` is how a person lifts a stop (W36). The
   snapshot grew from 473 lines to 474, `dumpstagram.session.clear_write_stop`, none removed or
   changed. `tests/test_pacing_ledger.py` holds fourteen gates, each
   seen red under the 16 mutations of `scripts/verify_ledger_gates.py`, then green. The
   cross-process gates run two interpreters over the engine's own write path, `send_write`
   through a pacer on the ledger beside one session file, with a fake wire, and a separate
   gate holds both clients' `from_session_file` to that ledger. No gate runs the `dumpsta`
   write commands themselves in two processes.
9. **Posting.** Photo upload, publish, delete, and carousel, per build plan Step 19 as already
   written, including the orphaned upload gate. The upload host must pass the provenance host
   check.
   Done 2026-09-23: `client.media.publish_photo`, `publish_carousel` and `delete_post` on both
   clients, returning the new `PublishedPost` (W37), and `dumpsta publish-photo`,
   `publish-carousel` and `delete-post`, each confirming itself with a read. Uploads go to
   `i.instagram.com`, backed by finding `upload-a-photo-for-a-post`, so the host passes the
   provenance host check, and each upload is a write (W38). Findings `upload-a-photo-for-a-post`,
   `publish-a-photo-post`, `publish-a-carousel-post` and `delete-my-own-post`, verified 5, 3, 3
   and 5 times (W39). Snapshot 520 to 535 lines, all additions. 40 mutations red then green in
   `scripts/verify_posting_gates.py` (W40). Live: 2 browser page loads, one carousel posted and
   deleted from the browser; 35 engine requests, three photos and two carousels posted, read
   back and deleted. The stop condition part held in `probes/posting_cli_acceptance.py`, 13
   requests from `dumpsta`, `media_count` 8 before and after. Log
   `engine/logs/posting-cli-acceptance-2026-09-23-233411.json`.

**Stop condition.** The census exists and covers every page type above. A photo and a two item
carousel are posted, read back, and deleted from `dumpsta` in one run. `dumpsta doctor` reports
zero drift on a fresh session. Every harness exits 0 after the split. Two `dumpsta` processes on
one account share one write budget, gated offline. The 24 flat methods and their namespace
aliases answer identically, gated offline.

**Done 2026-09-24, released as `1.1.0`, prepared and not published.** Each part, with its evidence,
is in [releases/1.1.0.md](releases/1.1.0.md) and the notes in
[releases/1.1.0-notes.md](releases/1.1.0-notes.md). The census covers all fifteen page types as a
lower bound (`e683c29`). One `dumpsta` run posted, read back and deleted a photo and a two item
carousel with `media_count` 8 before and after (`44faf04`). `dumpsta doctor --live` reported drift
0 and replay_failed 0 with 14 `missing` (`f6ae9c5`), on the existing session file rather than a
freshly adopted one. All 33 harnesses exit 0, 622 mutations red then green, rerun for the release.
The ledger's cross-process gates and the facade parity gates pass offline. The 24 counted every
`async def` in `aio.py`, and the flat capabilities are 17, each with its alias (W21). The public
surface grew from 397 lines at `v1.0.0` to 536, all additions.

## E2, 1.2.0: read everything a signed-in user can see

Reads come before writes in every category, and a read-only clone is the first useful milestone
for a clone site. All of it runs on the owner's account.

- **Profile tabs:** posts grid, reels, tagged, highlights tray and highlight contents, followers,
  following, mutual followers, suggested accounts.
- **Post depth:** likers, comment replies (threaded), carousel children through the E1 model,
  user tags, location, collaborators.
- **Stories:** the tray, one account's reel of stories, highlights, marking seen per W6.
- **Discovery:** explore grid, reels feed, search across accounts, hashtags and places, recent
  searches, hashtag pages, location pages, audio pages.
- **Own account:** saved posts and collections, archive, the activity feed and pending follow
  requests (both hypotheses already in the knowledge base), close friends list, blocked list.
- **Direct, read side:** the inbox listing made public with its pagination, pending message
  requests, unread counts and badges.
- **Page models:** the inbox load and the post page document, which close the notes, post and
  comment parity departures recorded in `1.0.0-notes.md`.
- **With account B (W51):** the follow request list, the message request folder and a message
  request row read non-empty once B has sent them (writes as B from 2026-09-30, W50), and B's
  profile, posts, stories and highlights read as another account's.

Estimated at 20 to 25 new read capabilities and about 4 discovery nights. HYPOTHESIS.

Prepared offline 2026-09-23 with no request carrying the session: nine batches with a probe
each, one capture night and one arranged story run, in [e2-execution.md](e2-execution.md)
(W41 to W44).

**Stop condition.** Every read in the census that belongs to a page listed above is either a
public capability or has a recorded reason it is not. `dumpsta` can render, as text, each page a
signed-in user sees on the website: home, explore, reels, a profile with each tab, a post with
threaded comments, a story, search results, notifications, saved, and the inbox with requests.

## E3, 1.3.0: own-account writes and content management

Only writes whose effect lands on the owner's account or content, each with its reversal.

- **Private to the viewer:** save and unsave, collections create, rename and delete, mute and
  unmute posts and stories of accounts already followed, hidden words.
- **On the owner's own posts:** comment reply, comment like, pin a comment, edit caption, archive
  and unarchive, hide like count, turn comments off and on, alt text, user tags and location on
  publish.
- **Reels:** upload with cover frame and audio, read back with its video rendition, download,
  delete.
- **Stories:** post a story if the census shows the web client can, delete it. Highlights create,
  edit and delete from the owner's own archived stories.
- **Follow a public account and unfollow it,** already shipped, extended with favorites add and
  remove, which is private to the viewer.
- **Relationships with account B (W51):** follow B while B is private and cancel the pending
  request, accept and deny B's request to follow the owner, remove B as a follower, block and
  unblock, restrict and unrestrict, close friends add and remove, mute and unmute, and approve a
  restricted account's comment.
- **B's content (W51):** like and reply to a comment on B's post, story like, story reply and
  reaction, note reply.

Estimated at 40 to 45 new writes. HYPOTHESIS.

**Stop condition.** Every E3 write has run once live from `dumpsta`, confirmed by an E2 read in the
same run and reversed where a reversal exists, and every write that lands on B is also confirmed by
a read as B. A reel is published, read back with its video rendition, downloaded, and deleted.

## E4, 1.4.0: direct messaging with account B, and push transport

This absorbs roadmap Phase 6 (W3). Every message runs in a one-to-one thread between the owner and
account B (W51). The engine drives both sides, so an event the other side has to cause is caused
by a second client on B's session in the same run, and no arranged run needs the owner's hand. The
ruling 30 thread and the W30 partner stay available and no acceptance depends on them.

- **Messages:** photo, video and voice send, reactions, replies, edit, unsend of media, the like
  heart, forward, share a post into the thread, message search.
- **Threads:** mark seen at parity (W6), typing indicator, mute, pin, vanish mode, and delete the
  thread from the owner's inbox, since B can send into a new one.
- **Two sides (W51):** a message request from B accepted and declined, a new one-to-one thread
  opened from a profile, and the events only the other side causes: B's reaction, typing, seen,
  edit and unsend.
- **Push transport.** Discover the realtime socket the web inbox holds, replace the poller behind
  `events()`, and keep polling as a named fallback `Behavior` setting.
- **Event kinds,** additive to the `Event` hierarchy: reaction, unsend, edit, seen, typing, thread
  update, and the notification kinds from the activity feed. Each is gated offline on recorded
  frames and seen live as caused by B.

**Stop condition.** Every E4 message kind and reaction is sent and reversed from `dumpsta` in the
thread with B. `dumpsta events` on push prints each new event kind within 5 s of B causing it, on
both facades, and survives a dropped socket by reconnecting, gated offline. The polling fallback
still passes the Phase 4 stop condition.

## E5, 1.5.0: settings, login offline, multi-account host offline, parity closure

- **Settings on the owner's account,** each reversible and restored in the same run: name, bio,
  links, gender, avatar, activity status, story and message controls, notification settings, and
  read-only account data such as login activity where the web surface exposes it. The private
  account toggle is included, since it is reversible, and restored within the run.
- **Login.** Password, two factor, and a checkpoint surfaced as `CheckpointRequired` with its
  required action, never solved or retried. Discovery reads the login page's compiled operations
  with `scout_operations.py`, which fires nothing, and it is gated offline on recorded answers. The
  live login runs on account B from a fresh process with no cookies, started by the owner, who
  types B's password (W7, W49).
- **Account B's lifecycle (W51):** a username change and its restore, and log out followed by a
  fresh session adopted from the browser, all on B, since W7 keeps each of them off the owner's
  only other session.
- **Multi-account host.** Many `Session`s in one process with one pacer per account, a shared loop
  thread and per-account event fan-out, gated offline for isolation: no state, cookie or budget
  crosses accounts. Live, the owner and B run for an hour in one process with events flowing on
  both and no cross-account request.
- **Parity closure.** Every departure in the release notes is closed or re-recorded with the reason
  it cannot close. Human timing is resampled on at least three further days.
- **Coverage report.** `census.md` regenerated against the current bundle, with the share of web
  actions covered stated as a number, and every remaining gap marked either E6 or excluded.

**Stop condition.** Every E5 setting is changed and restored live from `dumpsta` on the owner's
account. Login and the multi-account host pass their offline gates against recorded answers, the
live login on B succeeds once, and the hour on both accounts sends no cross-account request. The
census shows every web action two accounts can reach as a capability or a recorded exclusion.

## E6, 1.6.0: group threads and a third account

Opens when the owner has a third account, since a group needs three participants (W9, W51). Every
other item this phase once held moved into E2 to E5 with account B.

- **Group threads:** create, rename, add and remove members, leave, admin actions, and group
  events, run with the owner, B and the third account.
- Anything discovery shows needs a third participant, moved here under the standing rule.

**Stop condition.** Every E6 item has run once live from `dumpsta`, confirmed by a read and reversed
where a reversal exists. The census shows every in-scope web action as a capability or a recorded
exclusion, with no item left marked E6.

## Order and rough cost

| Phase | Release | New capabilities, HYPOTHESIS | Needs from the owner |
|---|---|---|---|
| E1 | 1.1.0 | about 6 plus infrastructure | Nothing |
| E2 | 1.2.0 | 20 to 25 reads | Using B by hand until its writes open on 2026-09-30 |
| E3 | 1.3.0 | 40 to 45 writes | Nothing |
| E4 | 1.4.0 | 25 to 30 plus push | Nothing, B is the other side |
| E5 | 1.5.0 | 20 to 25 plus login and host | Typing B's password once for the live login |
| E6 | 1.6.0 | group threads | A third account |

## Risks

- Every added operation is one more `doc_id` to rotate. Without the E1 canary, E3 and later
  become upkeep rather than growth.
- Putting E1 to E5 on the owner's only account concentrates the checkpoint risk there. W7 moves the
  riskiest items off it, but posting, reels and settings changes still run on it.
- The web client changes weekly. A capability verified in E2 may need repair by E4. Repairs are
  patch releases and do not touch the surface.
- Account B is new and may be treated more strictly than an aged one, so a result on B may not
  carry back to the owner's account, and a restriction on B may reach the owner's through the
  shared device and network (W50). ASSUMPTION.
- The Swift app and this plan compete for the same live request budget and the same account.
