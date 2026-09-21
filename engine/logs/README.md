# Logs

Every run that produces output worth reading lands here, as a file. This includes live probes
against Instagram, test runs, benchmark runs, and any ad hoc script a session writes.

Logs live at `engine/logs/` rather than under `engine/tests/`, moved 2026-09-20 alongside
`engine/probes/`, so that `tests/` holds gates and only gates.

## Rules

- **One file per run.** Name it `<kind>-<YYYY-MM-DD>-<HHMMSS>.<ext>`, for example
  `live-repro-2026-09-20-181203.json` or `pytest-2026-09-20-181455.log`.
- **Write the file even when the run succeeds.** A log that only exists on failure cannot be
  diffed against the run before it.
- **Never write credentials.** No `sessionid`, no `csrftoken`, no `fb_dtsg`, no `lsd`, no
  cookie jar dump. Record lengths and presence flags instead of values. A log holding a
  `sessionid` is an account takeover token sitting in a repository.
- **Never write message bodies or third-party names** from a live account. Record counts, ids,
  sizes and timings.
- **The script that produced the log lives in `../probes/`**, not in a scratch directory. A log
  whose script is gone cannot be reproduced.
- Logs are build products. They are gitignored and they are not test fixtures. If a run's
  output must be asserted against, copy the sanitised part into a fixture deliberately.

## Index

| File | What it is |
|---|---|
| `live-repro-2026-09-20-json.log` | First live two-request run from this repository. Written up in [docs/knowledge/live-reproduction-2026-09-20.md](../../docs/knowledge/live-reproduction-2026-09-20.md). |
