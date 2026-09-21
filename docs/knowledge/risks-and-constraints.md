# Risks and constraints

Standing conditions that shape engineering decisions across both products. These are
not problems to be solved. They are facts of the environment that the design must
absorb.

## Legal and terms of service

Dumpsta-Module targets an undocumented, unofficial API. That is against Instagram's
terms of service. This was raised explicitly during design and accepted by the user as
a known cost rather than a blocker. It occupies the same territory as existing
open-source clients in this space, `instagrapi` being the commonly cited example.
That project is prior art worth studying for the shape of the problem, not a
dependency and not a design template. Nothing in this repository has been compared
against it.

Three consequences follow, and all three are engineering requirements, not
disclaimers.

**Users can have accounts restricted or banned.** This is the reason pacing lives in
the module and defaults conservative. An open-source client that ships fast defaults
harms its users.

**Endpoints break without notice.** The upstream API is not versioned for third
parties and carries no compatibility promise. This is the reason for the hard split
between a stable public surface and a churning `_private` layer, and the reason
typed models sit at the boundary. See
[../decisions/ADR-0003](../decisions/ADR-0003-no-browser-driver.md).

**Open-sourcing creates a support surface.** Every upstream break becomes an issue
queue. Honest documentation of the risk, and of the pacing defaults, reduces both the
harm and the support load.

## Operational risks

Severity and mitigation are unchanged. The evidence column now distinguishes what has been
observed from what is reasoned. Source for measured entries:
[prior-art-dumpsta-js.md](prior-art-dumpsta-js.md).

| Risk | Impact | Mitigation | Evidence |
|---|---|---|---|
| Persisted query identifier rotates | Feature stops working | Loud failure by design, known recovery procedure | INFERENCE. Stable across one session of roughly 650 requests |
| Token extraction breaks on a bundle change | Authentication stops working | Raise rather than proceed with a null token | FACT that extraction is regex against a minified bundle |
| Response field rename inside a node | Records degrade silently, the worst case | Comparison against a recorded oracle | Rated worst case by the prior project |
| Detection through request volume or timing | Account restriction | Per-account pacer, defaults anchored to measured real-client traffic | FACT for read traffic at 0.351 req/s |
| Detection through a minimal request shape | Account restriction | Send the full client-shaped request even where fields are provably ignored | FACT that 19 body fields and 8 headers are ignored |
| Listener traffic competing with user traffic | Budget exhaustion | Pacer treats listener polling as first-class traffic | Design |
| Frequent re-authentication as a risk signal | Account restriction | Session persistence is the Phase 1 stop condition | ASSUMPTION |
| Checkpoint treated as a retryable error | Escalation from soft block to locked account | Structurally non-retryable in code | Design, verified by mutation testing in the prior project |
| False positive in the checkpoint classifier | Operation becomes permanently unfinishable | Classify on the response URL, and on the body only when it is not a success payload | FACT that the naive version scanned user content |
| Write operations scored differently from reads | Unknown | None yet | Entirely unmeasured. The prior project was read-only |
| Non-residential IP treated differently | The "not blocked" finding may not hold | None yet | UNRESOLVED. All measurements from one residential connection |

## Technical constraints

**In-process embedding means a Python crash kills the app.** Accepted in
[ADR-0002](../decisions/ADR-0002-embedded-python-pythonkit.md). The remedy for one
unstable dependency is to isolate that call path in a subprocess, not to change the
architecture.

**The GIL makes concurrency a correctness problem in Swift.** Rules in
[../bridge/threading-and-gil.md](../bridge/threading-and-gil.md).

**Signing scales with dependency count.** Every `.so` and `.dylib` is signed
individually. A large dependency tree makes every build slower and every notarization
riskier. A practical reason to keep dependencies lean.

**Wheels must match the shipped interpreter's architecture.** Mismatches surface at
runtime, not at build time. The app targets Intel as well as Apple Silicon, so this now applies
twice, once per bundled runtime. Populating one architecture's `site-packages` with the other
architecture's interpreter is the easy version of this mistake. See
[../decisions/ADR-0010-distribution-targets.md](../decisions/ADR-0010-distribution-targets.md).

**Intel support is decided, unverified, and scheduled last.** No Intel Mac is known to be
available here, so the second slice may build, sign, and notarize and still fail at first
import with nobody noticing. ASSUMPTION until an Intel machine runs it. Sequencing it as the
project's final step keeps it out of every earlier build, and concentrates the risk at the
point where a first release is expected.

**Dependencies are vendored at build time**, resolved from `module/uv.lock`. Installing
packages into the bundle at runtime was never acceptable, and leaving the App Store does not
make it acceptable, because it makes the shipped artifact non-deterministic. See
[../decisions/ADR-0009-uv-toolchain-python-floor.md](../decisions/ADR-0009-uv-toolchain-python-floor.md).

## Handling user data

Added 2026-09-20. The corpus had no data policy until a review of the prior project showed
exactly why one is needed.

That project produced two 17.4 MB exports and a 60 MB archive containing real private messages
and named third parties, and it kept a live unredacted session cookie in a plaintext local file.
Neither was a mistake in itself, and both are the normal by-products of building this kind of
client. Left undesigned, they become a leak.

Three rules, all of which the prior project arrived at and two of which it learned by finding a
real leak.

**A session credential is a full account takeover token with no second factor.** It lives in a
file with restrictive permissions, never in the repository, never in a log, never in an export,
and never pasted into a chat, an issue, or a bug report. The prior project's own remediation
after a credential reached a transcript was to rotate the session by logging it out, and that is
the correct remedy here too.

**Redaction is verified by scanning with a positive control, not by reading the code.** Grep for
the live values across logs, state, exports, and documentation. Zero hits only means something
if the same grep demonstrably finds those values where they are known to be.

**User content is data the project is holding on someone else's behalf.** The prior project's
credential audit incidentally caught a diagnostic tool writing real message bodies into a
directory its ignore file did not cover. Error envelopes were kept verbatim, since they contain
no user content, and message bodies were sanitised. Any diagnostic, probe, fixture, or captured
oracle this project produces needs the same treatment before it is written anywhere durable.

This applies with more force here than it did there, because Dumpsta-App is open source and its
contributors will produce captures on their own accounts.

## Constraints the project imposes on itself

These are self-imposed and exist to protect the stability goal.

- No Instagram logic in Swift, ever.
- No raw JSON dicts across the public boundary.
- No module-level mutable state.
- No rate limiting in the app.
- No browser automation anywhere.
- Read-only capabilities land before write capabilities, so that the destructive
  surface is exercised only once the session layer is proven.

## Risk this documentation carries

Revised 2026-09-20. This used to say that every claim about Instagram's internals was
ASSUMPTION. That is no longer true, and the new risk is subtler.

Part of this corpus now rests on real measurement, inherited from
[prior-art-dumpsta-js.md](prior-art-dumpsta-js.md). Those claims are tagged FACT. The hazard is
that inherited facts are easy to over-generalise. Every one of them was measured:

- against the **web GraphQL surface**, not the mobile private API;
- for **read** operations only;
- on **one account**, **one thread**, **one day**, from **one residential IP**;
- by a **different project in a different language**.

A claim tagged FACT here means somebody observed it once, under those conditions. It does not
mean it holds for writes, for other surfaces, for other accounts, or next month.

The remaining claims are still ASSUMPTION, and the mobile-API assumptions in particular gained
nothing from the prior project, because it never touched that surface.

Reproducing a bootstrap plus one page inside this repository costs two requests and would
convert the most important inherited facts into locally verified ones. Until that happens, no
command in this project has ever been run against Instagram.

See [assumptions-and-open-questions.md](assumptions-and-open-questions.md) for the full tag
inventory.
