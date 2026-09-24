# Web parity plan, 1.1.0 to 1.6.0

Written 2026-09-23, after `1.0.0` was cut. Approved the same day: the owner delegated every open
decision, and the rulings are in the Decisions section below. It plans the engine phases whose
end state is an engine that can back a site behaving like instagram.com for a signed-in user.
[roadmap.md](roadmap.md) stays the canonical definition of Phases 1 to 6, and nothing here
reopens a locked decision.

The phases are named E1 to E6 so they do not collide with the roadmap's Phase 5 (the Swift app)
and Phase 6 (push transport). E4 absorbs Phase 6. E1 to E5 need only the owner's account and the
direct message target already named in ruling 30. Everything that needs a second account the
owner controls waits in E6, which opens once that account exists. Each phase ships as one
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

**Stop condition.** The census exists and covers every page type above. A photo and a two item
carousel are posted, read back, and deleted from `dumpsta` in one run. `dumpsta doctor` reports
zero drift on a fresh session. Every harness exits 0 after the split. Two `dumpsta` processes on
one account share one write budget, gated offline. The 24 flat methods and their namespace
aliases answer identically, gated offline.

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

Estimated at 20 to 25 new read capabilities and about 4 discovery nights. HYPOTHESIS.

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

Estimated at 25 to 30 new writes. HYPOTHESIS.

**Stop condition.** Every E3 write has run once live from `dumpsta`, confirmed by an E2 read in the
same run and reversed where a reversal exists. A reel is published, read back with its video
rendition, downloaded, and deleted.

## E4, 1.4.0: direct messaging in the existing thread, and push transport

This absorbs roadmap Phase 6 (W3). Every message runs in the ruling 30 one-to-one thread (W8), and
every event the other side would have to cause is either produced by the owner from another
device, as Phase 4's arranged send was, or deferred to E6.

- **Messages:** photo, video and voice send, reactions, replies, edit, unsend of media, the like
  heart, forward, share a post into the thread, message search.
- **Threads:** mark seen at parity (W6), typing indicator, mute, pin, vanish mode, delete the
  thread from the owner's inbox only if the census shows it is recoverable, otherwise E6.
- **Push transport.** Discover the realtime socket the web inbox holds, replace the poller behind
  `events()`, and keep polling as a named fallback `Behavior` setting.
- **Event kinds,** additive to the `Event` hierarchy: reaction, unsend, edit, seen, typing, thread
  update, and the notification kinds from the activity feed. Each is gated offline on recorded
  frames and seen live from the owner's own second device.

**Stop condition.** Every E4 message kind and reaction is sent and reversed from `dumpsta` in the
existing thread. `dumpsta events` on push prints each new event kind the owner can cause alone
within 5 s of the action on both facades, and survives a dropped socket by reconnecting, gated
offline. The polling fallback still passes the Phase 4 stop condition.

## E5, 1.5.0: settings, login offline, multi-account host offline, parity closure

- **Settings on the owner's account,** each reversible and restored in the same run: name, bio,
  links, gender, avatar, activity status, story and message controls, notification settings, and
  read-only account data such as login activity where the web surface exposes it. The private
  account toggle is included, since it is reversible, and restored within the run.
- **Login, built and gated offline.** Password, two factor, and a checkpoint surfaced as
  `CheckpointRequired` with its required action, never solved or retried. Discovery reads the login
  page's compiled operations with `scout_operations.py`, which fires nothing. The live login runs
  in E6 on the second account (W7).
- **Multi-account host, built and gated offline.** Many `Session`s in one process with one pacer
  per account, a shared loop thread and per-account event fan-out, gated for isolation: no state,
  cookie or budget crosses accounts. Its live run is in E6.
- **Parity closure.** Every departure in the release notes is closed or re-recorded with the reason
  it cannot close. Human timing is resampled on at least three further days.
- **Coverage report.** `census.md` regenerated against the current bundle, with the share of web
  actions covered stated as a number, and every remaining gap marked either E6 or excluded.

**Stop condition.** Every E5 setting is changed and restored live from `dumpsta` on the owner's
account. Login and the multi-account host pass their offline gates against recorded answers. The
census shows every single-account web action as a capability or a recorded exclusion.

## E6, 1.6.0: everything that needs a second account

Opens when the owner has created a second account, and a third for group threads (W9). Suggested
setup: a new account on the same residential network, aged a few days with ordinary browsing
before any engine write, following and followed by the owner.

- **Relationships:** follow a private account and cancel the pending request, accept and deny an
  incoming follow request, remove a follower, block and unblock, restrict and unrestrict, close
  friends add and remove, mute a messaged account, approve a restricted account's comment.
- **Interaction with another person's content:** like and reply to a comment on another account's
  post, story like, story reply and reaction, note reply.
- **Direct:** message requests accepted and declined, a new one-to-one thread created from a
  profile, thread delete, and the event kinds only the other side can cause (their reaction, their
  typing, their seen).
- **Group threads:** create, rename, add and remove members, leave, admin actions, and group
  events. Needs the third account.
- **Login live:** the E5 login on the second account, from a fresh process with no cookies,
  including its two factor path.
- **Username change** on the second account, and restored.
- **Log out** on the second account, then sign it back in, since ending the only account's
  session is the lockout W7 keeps off it (W13).
- **Multi-account host live:** the owner and the second account run for an hour in one process with
  events flowing on both and no cross-account request.

**Stop condition.** Every E6 item has run once live from `dumpsta`, confirmed by a read and reversed
where a reversal exists. The census shows every in-scope web action as a capability or a recorded
exclusion, with no item left marked E6.

## Order and rough cost

| Phase | Release | New capabilities, HYPOTHESIS | Needs from the owner |
|---|---|---|---|
| E1 | 1.1.0 | about 6 plus infrastructure | Nothing |
| E2 | 1.2.0 | 20 to 25 reads | Nothing |
| E3 | 1.3.0 | 25 to 30 writes | Nothing |
| E4 | 1.4.0 | 20 to 25 plus push | Sending from another device during arranged runs |
| E5 | 1.5.0 | 15 to 20 plus login and host, offline | Nothing |
| E6 | 1.6.0 | 25 to 30 plus live login and host | A second account, and a third for groups |

## Risks

- Every added operation is one more `doc_id` to rotate. Without the E1 canary, E3 and later
  become upkeep rather than growth.
- Putting E1 to E5 on the owner's only account concentrates the checkpoint risk there. W7 moves the
  riskiest items off it, but posting, reels and settings changes still run on it.
- The web client changes weekly. A capability verified in E2 may need repair by E4. Repairs are
  patch releases and do not touch the surface.
- A new second account may be treated more strictly than an aged one, so E6 results may not carry
  back to the owner's account. ASSUMPTION.
- The Swift app and this plan compete for the same live request budget and the same account.
