# Legal and safety

## Terms of service

Dumpsta-Engine targets an undocumented, unofficial Instagram API. Using it is against Instagram's
terms of use. The project accepts that as a known cost, and so does anyone who uses it. Nothing
here is legal advice.

## What can happen to your account

The account you use can be restricted, sent to a checkpoint, or banned. Use the engine only with
an account you own and can afford to lose. Every measurement behind the defaults was taken on one
account from one residential network. Traffic from a data center or a shared proxy may be treated
differently, and nothing has measured how.

## What the defaults do to protect it

Pacing lives in the library, so every consumer inherits it without opting in. By default:

- each request waits 1.3 s to 5.3 s after the previous one, fitted to a person browsing;
- every write waits at least 30 s after the previous write, and no more than 30 writes leave in
  any rolling hour;
- a write is sent once and never retried, and an ambiguous result raises `OutcomeUnknown` rather
  than risking a duplicate;
- an unrecognised rejection of a write stops further writes for the life of the client;
- a checkpoint is never retried, under any setting;
- a client built from a session file keeps the write budget and the stop beside that file, so
  every process on the account shares them, and the stop stays until a person lifts it.

Faster presets exist. Nothing has measured how Instagram treats them, and choosing one is a
decision about your own account. See [Rate limiting and safety](rate-limiting-and-safety.md) for
the numbers and where they come from.

## It will break

The upstream API carries no compatibility promise. A query id can rotate overnight and a response
field can be renamed. The engine fails loudly when it notices, and `dumpsta doctor` compares the
query ids it stores against the ones the website currently uses. A method that works today may
not work tomorrow.

## Protect the session

A `sessionid` cookie is enough to take over the account. Keep the cookie file and the session
file readable only by you, never pass cookies on the command line, and never commit either file.
See [Session and authentication](session-and-auth.md).
