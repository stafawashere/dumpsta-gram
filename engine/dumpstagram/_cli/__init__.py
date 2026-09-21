"""The `dumpsta` command line, private by layout and stable by entry point.

Nothing under here carries the stability promise in `docs/public-api.md`. The installed
console script is the contract, and `dumpstagram._cli.main` is how it is reached.
"""

from dumpstagram._cli.main import main

__all__ = ["main"]
