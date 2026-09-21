# Overview

## Purpose

Dumpsta-App is a custom Instagram client for macOS, written in Swift, that uses
Dumpsta-Engine to do everything the official app and website can do, and more.

It has two jobs, and the second one shapes the code as much as the first.

**Job one, be a good client.** A person should prefer it to the official clients for
the things it covers.

**Job two, be the reference implementation.** The app is open source and is meant to
be a heavily developed demonstration of how to consume Dumpsta-Engine at a high level.
Other people will read this code and copy from it.

The second job has practical consequences. A shortcut taken here propagates into other
people's projects. Concurrency handling around the Python bridge, error surfacing, and
the treatment of challenge states are the three places where a bad example does the
most damage, because each one is easy to get subtly wrong.

## What the app owns

- User interface and interaction.
- Application state, including what is currently displayed and what is cached for the
  session.
- Account selection, when multiple accounts arrive.
- Orchestration, deciding which engine calls to make and in what order.
- Presentation of challenge and checkpoint states as something a person can act on.
- Persistence of session files on disk.

## What the app does not own

- Any knowledge of Instagram. No endpoints, no headers, no signing, no cursor formats, no
  identifier resolution.
- Rate limiting and pacing. That lives in the engine, deliberately. See
  [../../engine/docs/rate-limiting-and-safety.md](../../engine/docs/rate-limiting-and-safety.md).
- Retry policy for upstream failures, and in particular any decision about whether something is
  retryable. Checkpoints are never retried, and that rule is enforced in the engine.
- Interpreting whether a response succeeded. HTTP 200 is not a success signal on this API, and
  classification happens in the engine.
- Session identity management beyond handing the engine a file path.

The dividing rule is simple and worth applying literally. If Swift needs to know something about
how Instagram works, the engine's public API has a gap. The fix goes in the engine.

## Visual fidelity, and the measurements that already exist

The app aims to be a client a person prefers to the official ones. That makes visual fidelity a
real requirement rather than a polish item, and some of the work is already done.

`dumpsta-js/dumpsta-vis/docs/instagram-tokens.md` holds CSS design tokens measured off a live
Instagram direct-thread page on 2026-09-20: full dark and light palettes, the type scale, page
and chrome dimensions, message-bubble styling including the outgoing indigo `rgb(74,93,249)`,
bubble grouping and corner-collapse rules, day separators, reply-quote treatment, media sizing,
timestamps, modal tokens, and motion timings. Alongside it,
`dumpsta-js/dumpsta-vis/docs/design-gaps.md` records 48 measured divergences between an
implementation and those tokens, tiered by visibility.

Two things make this worth reading before building any UI here.

It is measured, not guessed. The values were read with `getComputedStyle` off Instagram's own
custom properties, and the light palette was captured by swapping the theme class in the DOM and
restoring it, changing nothing on the account.

Its conclusions are transferable even though the implementation is CSS and this app is SwiftUI.
The most useful one is that the font stack is not the biggest tell, since both stacks resolve to
San Francisco on macOS. The real gap is metrics: fixed line heights rather than multipliers,
off-scale sizes, and letter spacing. A SwiftUI implementation can get the palette right and
still look wrong for exactly those reasons.

Treat those two files as a specification to translate, not as code to port. See
[../../docs/knowledge/prior-art-dumpsta-js.md](../../docs/knowledge/prior-art-dumpsta-js.md).

## Platform

macOS. This is the working assumption throughout the bridge design, which embeds
CPython in-process.

**macOS only, and iOS is out of scope.** Ruled 2026-09-20. Embedding CPython on iOS is a
materially different problem rather than a port, so nothing in this corpus should be read as
iOS-ready.

**Intel Macs are a target and the App Store is not.** The app ships as a universal binary,
signed with Developer ID and notarized, carrying one CPython runtime per architecture. No
sandbox entitlement, so arbitrary proxy configuration stays permissible. See
[../../docs/decisions/ADR-0010-distribution-targets.md](../../docs/decisions/ADR-0010-distribution-targets.md).

## Relationship to the engine

The app embeds a relocatable CPython and drives the engine in-process through
PythonKit, which gives it the same access a Python program would have. The alternatives
and the reasoning are in
[ADR-0002](../../docs/decisions/ADR-0002-embedded-python-pythonkit.md).

In development, `engine/src` is on `sys.path` directly, so editing Python takes effect
without an Xcode rebuild.
