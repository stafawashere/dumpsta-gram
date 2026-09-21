# Session archive, 2026-09-21, build plan steps 5 and 6

Provenance record for the implementation session that added the pacer and the web request
layer. It covers one session. Earlier sessions the same day produced `errors.py`, `session.py`,
`_private/transport.py`, `_private/web/classify.py`, the environment relocation, and the
`engine/docs/build-plan.md` research pass, and they left no archive of their own.

Companion to [session-archive-2026-09-20.md](session-archive-2026-09-20.md), which records the
design conversation that produced the corpus before any code existed.

## Chronology

**1. Orientation, and the plan's own checklist was stale.**
The build plan's execution checklist showed Steps 0 to 1 done and everything after unchecked,
while the tree already held `session.py`, `transport.py`, `classify.py`, and their gates. The
full suite was green at 51 passed. The checklist had simply not been updated by the sessions
that did the work.

**2. Step 5 turned out to be blocked, and Step 6 was not.**
Step 5 needed `https://www.instagram.com/api/graphql` and `doc_id` `27502152406082940` as
literals in code. `skills/reverse-engineer/knowledge/INDEX.md` held zero findings, so
`check_provenance.py` would reject both. The 2026-09-20 live reproduction had observed all of
it, but predates the knowledge base. Step 6, the pacer, needs no literal at all, so it was done
first and Step 5 was raised to the user as a decision rather than resolved quietly.

**3. Step 6, the pacer.**
`_core/pacer.py` plus thirteen gates. Three of the gates survived their mutations on the first
attempt and had to be rewritten. See [Negative knowledge](#negative-knowledge) below.

**4. The user chose Step 5.**
Which authorised the live replay the finding needed.

**5. The replay, and a broken probe.**
`engine/probes/live_repro_bootstrap_page.py` failed immediately on a path that had been wrong
since the `module/` to `engine/` rename. Fixed, rerun, two live requests, both clean. Recorded
in [live-reproduction-2026-09-21.md](live-reproduction-2026-09-21.md).

**6. Findings written back.**
`bootstrap-web-tokens` and `direct-thread-message-page`, both `verified`, which took
`check_provenance.py` from zero backed literals to two URL shapes and one `doc_id`.

**7. Step 5, the web request layer.**
`documents.py`, `bootstrap.py`, `requests.py`, plus nineteen gates and thirteen mutations.
Documented in [../../engine/docs/web-request-contract.md](../../engine/docs/web-request-contract.md).

## What was verified by running a command

Every claim below was produced in this session and its output quoted at the time. Nothing here
is inherited.

| Fact | How |
|---|---|
| Full gate suite green after both steps | `uv run ruff format --check` 21 files, `uv run ruff check` all passed, `uv run mypy` 12 source files, `uv run pytest` 83 passed in 0.20s. Log `engine/logs/gates-2026-09-21-013754.txt` |
| The provenance gate fires on an unbacked `doc_id` | Rotated one digit, exit 1 naming `documents.py:37`. Restored, exit 0 |
| Every new gate can fail | Thirteen mutations against the pacer, thirteen against the web layer, each red then restored green |
| The probe runs live from this repository | Two requests, both 200, values in [live-reproduction-2026-09-21.md](live-reproduction-2026-09-21.md) |
| `doc_id` `27502152406082940` was still served on 2026-09-21 | The replay returned 20 edges and a 132-character cursor |

## A parallel session ran Step 7 at the same time

Noted because it affects how this archive should be read. While this session was writing
documentation, another session implemented build plan Step 7: `_core/loop_thread.py`,
`_core/redaction.py`, `tests/test_loop_thread.py`, and `tests/test_redaction.py`. The suite went
from `83 passed` to `105 passed` between two runs in this session, and the gate inventory rows
for that work were written by that session, not this one.

Consequence for provenance. Everything in this archive describes Steps 5 and 6. The loop thread
and redaction gates are recorded in
[../../engine/docs/engineering/gates.md](../../engine/docs/engineering/gates.md) with their own
mutations, and this session did not observe those mutations run. Two sessions editing the same
documents concurrently is also why a few state claims here were written stale and corrected
within the same pass.

## Sub-agent and external sources

No sub-agents were spawned. No web searches were performed. No external documentation was
fetched. No repository other than this one was inspected.

The only external system consulted was Instagram itself, through two live HTTP requests, and
its answers are recorded in the log and in the two findings.

There are therefore no cross-agent agreements or disagreements to record.

## Decisions that came from the user directly

- **Do Step 5**, given in full knowledge that it required a live replay against their own
  account. That is the authorisation the replay ran under.

Everything else in this session was a routine implementation choice resolved in session, which
is what [AGENTS.md](../../AGENTS.md) asks for.

## Decisions taken in session

Each one is a choice that a future session could reasonably have made differently.

### The `Session` file gained two fields rather than the request sending two empty ones

**Problem.** `requests.py` needs `__hs` and `__hsi`. `Session` stored neither, so a session
reloaded from disk would send both empty.

**Options.** Persist them on `Session`; carry them only in memory on a `BootstrapTokens` value
and send empty strings after a reload; or omit the two fields entirely after a reload.

**Decision.** Persist. `hsi` and `haste_session` joined the serialised session at
`schema_version` 1, and the documented key-set gate now asserts them.

**Reasoning.** A reloaded session should reproduce the observed request exactly. Sending two
empty fields, or omitting them, is a difference from what a browser sends, and the whole
argument for sending 38 items when 3 are checked is that differences are fingerprints.

**Why the version was not bumped.** The format already ignores unknown keys on read and
defaults missing ones, so both directions tolerate the change, and nothing has been released
that could hold a file without them.

**Remaining risk.** This edits a gate, which is normally the user's call alone. It is recorded
as a schema change the gate tracks, not as a gate loosened to reach green, and both new keys
are assertions added rather than removed. Flagged to the user in session; a version bump is
available if they prefer it.

### The prior day's run was recorded as the second verification

**Problem.** `capability_brief.py` refuses a finding with `verify_count` below 2. Today's
replay gave 1.

**Options.** Pass `--allow-single`, which the script offers as a deliberate override; spend two
more live requests on a second replay; or record the independent 2026-09-20 run as the second
verification.

**Decision.** Record the 2026-09-20 run, with its provenance written into the finding's
verification history naming `docs/knowledge/live-reproduction-2026-09-20.md`.

**Reasoning.** Two independent live observations of the same contract on two different days
genuinely exist. `--allow-single` would assert less than the truth, and a third request would
buy nothing.

### `hold` and `hold_for` were split

Driven by a gate that could not be made to fail. Recorded under
[Negative knowledge](#negative-knowledge) because the test came first and the design followed.

### The two URLs were written as literals rather than built from `ORIGIN`

**Problem.** `BOOTSTRAP_URL` and `GRAPHQL_URL` were f-strings over an `ORIGIN` constant, so the
provenance scanner saw only the bare origin and never checked either endpoint.

**Decision.** Write both as full literals. `ORIGIN` stays for the `origin` and `referer`
headers and carries `# provenance: ignore`, with a reason, because an origin is not an
endpoint. `DEFAULT_APP_ID` carries the same marker because `936619743392459` is fifteen digits
and matches the `doc_id` pattern while being an `x-ig-app-id` value.

**Reasoning.** A gate that cannot see the thing it is supposed to check is decoration. This is
the general hazard with the scanner: it matches literals, so any construction hides the value
from it.

## Negative knowledge

Preserved because these are the failures most likely to be repeated.

### Three pacer gates passed their own mutations

All three were written, run green, and then found to be worthless when the code they protected
was broken and they stayed green.

**The spacing gate read its own threshold off the policy.** It asserted
`gap >= pacer.pacing.floor_seconds`. Setting `floor_seconds` to `0.0` lowered the assertion in
the same motion. Fixed by asserting the literal `2.5`.

Generalised rule: **a gate must not derive its expected value from the thing it is gating.**

**The atomicity gate asserted spacing, which the lock does not provide.** `_wait_until_allowed`
rechecks the earliest-departure instant after every sleep, so unlocked tasks still come out
correctly spaced. Removing the `asyncio.Lock` changed nothing the test could see. Rewritten to
assert that no two slot bodies overlap, which is what the lock uniquely buys. That version goes
red the moment the lock is removed.

Generalised rule: **name what the mechanism uniquely provides, then assert that, not a
consequence that something else also produces.**

**The account-wide hold gate could not distinguish the two cases on a shared fake clock.**
`hold_for` recorded the hold and then slept. On a fake clock where sleeping advances shared
time, the hold duration passes whether or not the record was written, so a waiting task departs
at the right moment either way. Two rewrites failed before the cause was understood.

The fix was a design change, not a test change: `hold(seconds)` records the account-wide stop
and does not sleep, `hold_for(seconds)` records and sleeps. The gate now calls `hold` from a
task that does no waiting at all, so the record is the only thing that can delay the next
departure. `run_with_retries` keeps using `hold_for`, so an operation that never reaches a slot
still pays its backoff rather than spinning through the budget.

Generalised rule: **when a property cannot be isolated by a test, the two responsibilities are
probably fused in the code.**

### Stale bytecode made a restored mutation look still-broken

After restoring `documents.py` from a copy, the `doc_id` gate stayed red. The file on disk was
correct and byte-identical to the backup. `__pycache__` held the mutated module. Clearing it
returned the suite to green.

Worth knowing because the symptom reads exactly like a bad restore, and the instinct is to
suspect the restore rather than the cache.

### `uv sync` was run before `UV_PROJECT_ENVIRONMENT` was exported

Which recreated `engine/.venv` inside the file-provider-managed `~/Documents` tree, the exact
condition the environment guard exists to prevent. The guard caught it on the next `uv run`:

```
ERROR: environment /Users/mahfujm/Documents/dumpsta-gram/engine/.venv is inside the
sync-managed tree /Users/mahfujm/Documents. Export
UV_PROJECT_ENVIRONMENT=/Users/mahfujm/venvs/dumpstagram-engine and rerun.
```

The in-tree environment was deleted and the sync rerun against the correct location. The gate
worked exactly as designed, and the lesson is that the export has to come before the *first*
uv command of a session, not before the first one that matters.

### The probe had been broken for a day without anyone knowing

Root cause and fix in
[live-reproduction-2026-09-21.md](live-reproduction-2026-09-21.md#the-probe-was-broken-and-nobody-knew).
The general form: a script kept in the repository so that the next session reruns it instead of
rewriting it only pays off if something actually reruns it. Nothing does, today.

## Lessons carried into the gate inventory

Two of the three pacer failures generalise beyond this session, and both are now recorded in
[../../engine/docs/engineering/gates.md](../../engine/docs/engineering/gates.md) under the laws
that apply to every gate:

- A gate must not derive its expected value from the source it is gating.
- A gate must assert what its mechanism uniquely provides.

These sit alongside the existing law that a gate does not count until it has been seen to fail.
This session is the second time that law has caught a worthless test; the prior project's run
caught one too, which is recorded in the same document.
