# Tests

Gates, and only gates. Everything `uv run pytest` collects lives here, and nothing that is not a gate
does.

Probes moved to [../probes/](../probes/README.md) and run logs to [../logs/](../logs/README.md) on
2026-09-20, so that `testpaths = ["tests"]` cannot reach a script that spends live requests, and so
that "run the tests" has exactly one meaning. A probe is not a gate and must never be collectable as
one.

## Current state

Five modules of gates, `63 passed in 0.11s` on 2026-09-21: `test_errors.py` for the exception
hierarchy and the retry tuple, `test_session.py` for the session and its on-disk form,
`test_transport.py` for the HTTP boundary, `test_classify.py` for response classification, and
`test_pacer.py`. Every one of them was seen to fail against a deliberate mutation before it counted.

`conftest.py` is not a module of gates but a precondition on the run itself. It refuses to collect
when the interpreter sits inside the sync-managed `~/Documents` tree, or when any `.pth` in the
environment's site-packages carries the macOS hidden flag, because that combination silently drops
the editable install off `sys.path` and surfaces as `ModuleNotFoundError: No module named
'dumpstagram'`. Both branches were seen red on 2026-09-21, exit 4 each, and the run is green at
`63 passed` with neither condition present. Background and the permanent fix are in
[../docs/engineering/project-profile.md](../docs/engineering/project-profile.md).

## Target shape

```
tests/
   public_surface.txt        the committed public API contract, generated and diffed
   fixtures/                 recorded responses, one per shape and per failure envelope
                             plus the captured oracle
```

`fixtures/thread_oracle/` exists as of 2026-09-22, is generated, never hand edited, and is
gitignored because it is the shape of a private conversation with a third party. Without it
`test_thread_oracle.py` skips with a reason. It comes
from `../scripts/build_thread_oracle.py`, which reads a raw capture under the gitignored
`../exports/` and the prior project's `ghost` export, pseudonymises both with one mapping, and
refuses to write anything its leak scan finds a real value in.

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
