# Tests

Gates, and only gates. Everything `uv run pytest` collects lives here, and nothing that is not a gate
does.

Probes moved to [../probes/](../probes/README.md) and run logs to [../logs/](../logs/README.md) on
2026-09-20, so that `testpaths = ["tests"]` cannot reach a script that spends live requests, and so
that "run the tests" has exactly one meaning. A probe is not a gate and must never be collectable as
one.

## Current state

Empty. `uv run pytest` collects zero items and exits 5, verified 2026-09-20. The first gates arrive
in Phase 2 of [../docs/roadmap.md](../docs/roadmap.md), with the first real public API.

## Target shape

```
tests/
   public_surface.txt        the committed public API contract, generated and diffed
   fixtures/                 recorded responses, one per shape and per failure envelope
                             plus the captured oracle
```

## Rules

- **A gate is never loosened to reach green.** Strengthening is allowed. Loosening, widening a
  tolerance, skipping, deleting, or regenerating a snapshot to silence a diff is the project owner's
  decision alone.
- **A gate does not count until it has been seen to fail.** Break the source it protects, watch it go
  red, restore, and report both states.
- **A check that asserts an absence needs a positive control** in the same artifact, proving the
  check can fire.
- **Nothing here touches the network.** A network test is a flake and a risk to the account it
  authenticates as. Live verification is a probe.
- **A fixture is evidence that mapping logic works**, not evidence that the library currently works
  against Instagram. See the fixture hazard in [../docs/conventions.md](../docs/conventions.md).

Full inventory of intended gates, what each proves, and the mutation that must turn it red:
[../docs/engineering/gates.md](../docs/engineering/gates.md). Testing practice:
[../docs/engineering/07-testing-practices.md](../docs/engineering/07-testing-practices.md).
