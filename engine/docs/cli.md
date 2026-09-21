# The `dumpsta` command

The engine's first consumer, and the acceptance harness for the Phase 2 stop condition.
[ADR-0005](../../docs/decisions/ADR-0005-engine-first-build-order.md) makes it a real
consumer rather than a demo: every capability it reaches, it reaches through `SyncClient`, so
anything awkward to do from the command line is a gap in the public API rather than something
the command works around.

It lives at `dumpstagram/_cli/`. The installed console script is the contract and the module
layout behind it is not, which is why `_cli` is private and why nothing about the command
appears in `tests/public_surface.txt`.

The command is stdlib only. The `cli` extra in `pyproject.toml` stays empty and reserves the
name for a dependency that earns its place later.

## Invoking it

From the checkout:

```bash
uv run dumpsta --help
```

From an installed wheel, which is how a consumer gets it:

```bash
uv run --no-project --with dist/dumpstagram-0.0.0-py3-none-any.whl -- dumpsta --help
```

Every command needs a session file. There is no default path, because a session file holds a
`sessionid`, and guessing a location for one is how a tool writes an account token somewhere
its owner did not choose. Pass `--session PATH`, or set `DUMPSTAGRAM_SESSION`.

## Commands

| Command | Live requests | What it does |
|---|---|---|
| `adopt` | 0 | Builds a session from cookie material and saves it |
| `session` | 0 | Prints what the saved session holds, redacted |
| `thread FBID` | 1 per page, plus 1 if the session has no token yet | Reads pages of one direct thread |

`--json` on any command emits the machine-readable form instead of text. That form is a
contract: a key that moves breaks whatever scripts the command.

### `adopt`

Cookie material is read from the process environment, or from `--cookies-file PATH`, which is
a file of `KEY=value` lines. It is never read from the command line. `argv` is readable by
every process on the machine through `ps` and it lands in shell history, and a `sessionid` is
a full account takeover token with no second factor. A gate asserts the parser defines no
option that takes one.

Required keys are `IG_SESSIONID`, `IG_DS_USER_ID` and `IG_CSRFTOKEN`. `IG_MID` is sent as a
cookie when it is present, because the request builders reproduce a full browser request and a
minimal request is a fingerprint. All missing keys are named at once, so pasting three cookies
is one run rather than three.

Adoption spends no live request. That is deliberate: a check that costs a request cannot be
used to check credentials.

```bash
IG_SESSIONID=... IG_DS_USER_ID=... IG_CSRFTOKEN=... \
  uv run dumpsta --session state/session.json adopt
```

### `session`

Prints the account id, whether the session carries tokens, the checkpoint flag and whether a
proxy is configured. It prints no credential, and a gate holds that with the file itself as
the positive control.

### `thread`

```bash
DUMPSTAGRAM_SESSION=state/session.json uv run dumpsta --json thread 17945046917948992 --pages 2
```

`FBID` is the thread's `fbid`, which is one of the three identifiers the same thread has. The
other two answer with nothing rather than with an error.

- `--pages N` reads at most `N` pages, default 1. There is no `--all`: an unbounded read is an
  unbounded number of live requests, and the pacer spaces them 2.5 s apart.
- `--after CURSOR` continues from an `end_cursor` an earlier run printed.
- `--since MESSAGE_ID` reads only what arrived after a message already seen, and it is applied
  to the first page only. Sending a cursor and a marker together is a combination nobody has
  measured.
- `--user-agent STRING` changes what every request claims to be, which is a fingerprint
  decision rather than a cosmetic one.
- `--no-session-writeback` keeps tokens harvested during the run out of the session file.

Pagination stops on the page's own `has_next_page` and never on how many messages arrived.
`more_available` in the JSON form is that boolean, so a caller can continue without guessing.

Tokens harvested during a read are written back to the session file by default. Without it
every invocation pays a bootstrap request the previous one already paid for.

## Exit codes

A harness cannot branch on prose, so every deliberate failure has its own number. The mapping
is exhaustive over the public exception hierarchy and a gate asserts that, so adding a public
error class without a code fails the suite rather than quietly arriving as the generic one.
The numbers are permanent, and reordering them breaks anything that scripts the command.

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | `DumpstagramError`, or any failure with no more specific code |
| 2 | Usage: a bad command line, a missing session path, an unreadable session file |
| 3 | `AuthenticationFailed` |
| 4 | `CheckpointRequired` |
| 5 | `RateLimited` |
| 6 | `UpstreamRejected` |
| 7 | `NotFound` |
| 8 | `SchemaChanged` |
| 9 | `TransportFailure` |
| 10 | `OperationCancelled` |

Failure text goes to stderr through the library's redaction, which is the one place a cookie
reaches output with nobody having written it there.

## What it does not cover yet

The Phase 2 stop condition in [roadmap.md](roadmap.md) asks for a profile, a feed page with
working pagination, and a direct thread. Only the thread exists, because `thread_messages` is
the only capability the engine carries. The profile and feed commands arrive with the
capabilities behind them, and each is one subparser plus one renderer.

## Verification

Twenty-three gates in `tests/test_cli.py`, all offline, driven through the `Client` protocol
with a fake. `scripts/verify_cli_gates.py` breaks the source once per gate and reports red
then green. The live acceptance run is recorded in `logs/cli-acceptance-2026-09-21-025734.json`:
three requests, one page of 20 messages, then two pages of 40 distinct messages in 3394 ms,
which is the pacer's floor showing up as wall time.
