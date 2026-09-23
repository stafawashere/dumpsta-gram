"""Exit codes, which are the machine-readable half of the CLI's contract.

A harness cannot read prose off stderr, so every deliberate failure this library raises has
its own number. The mapping is exhaustive over the public exception hierarchy and a gate
asserts that, so adding a public error class without a code fails the suite rather than
quietly arriving as the generic one.

The numbers themselves are arbitrary and permanent. Reordering them is a breaking change for
anything that scripts this command.
"""

from __future__ import annotations

from collections.abc import Mapping

from dumpstagram.errors import (
   AuthenticationFailed,
   CheckpointRequired,
   DumpstagramError,
   NotFound,
   OperationCancelled,
   OutcomeUnknown,
   RateLimited,
   SchemaChanged,
   TransportFailure,
   UpstreamRejected,
)

__all__ = ["EXIT_BY_ERROR", "EXIT_OK", "EXIT_USAGE", "exit_code_for"]

EXIT_OK = 0
EXIT_USAGE = 2
"""What `argparse` already exits with on a bad command line, restated so nothing shadows it."""

EXIT_BY_ERROR: Mapping[type[DumpstagramError], int] = {
   DumpstagramError: 1,
   AuthenticationFailed: 3,
   CheckpointRequired: 4,
   RateLimited: 5,
   UpstreamRejected: 6,
   NotFound: 7,
   SchemaChanged: 8,
   TransportFailure: 9,
   OperationCancelled: 10,
   OutcomeUnknown: 11,
}


def exit_code_for(failure: BaseException) -> int:
   """The exit code for ``failure``, resolved along its own inheritance chain.

   Walking the chain rather than reading the exact type means a subclass a caller defines
   still exits as the closest public ancestor instead of as a crash.
   """

   for ancestor in type(failure).__mro__:
      if ancestor in EXIT_BY_ERROR:
         return EXIT_BY_ERROR[ancestor]

   return 1
