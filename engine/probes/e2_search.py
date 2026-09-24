"""Read only. Not yet run. Seven requests, and up to three more, conditional.

E2 batch 8, search, the parts whose variables are fully known: the recent searches, the
non-personalised typeahead, and a hashtag page's header. The personalised typeahead and the
keyword results grid carry an object or two session ids that were never observed, and wait for
the browser capture the execution list names.

   1  the inbox document, for fresh tokens (the bootstrap)
   2  the recent searches, PolarisSearchNullStateQuery, twice
   4  the non-personalised typeahead, PolarisSearchBoxNonProfiledRefetchableQuery, twice
   6  a hashtag page's header, PolarisHashtagHeaderActionButtonsQuery, twice

Conditional: each query's first replay sent once more on the other GraphQL path when every
root is null, three at most.

The query text and the hashtag come from ``IG_E2_SEARCH_QUERY`` and ``IG_E2_HASHTAG`` in the
root ``.env``, both ``instagram`` when absent, and neither is logged. A typed query is not added
to the recent searches (INFERENCE: the web client registers a recent search when a result is
clicked, and nothing is clicked here), and no search is visible to another person.

Run it from `engine/` with:

   uv run python probes/e2_search.py
"""

from __future__ import annotations

import asyncio
import sys

from _e2_support import E2Replay, dig, run_probe
from _probe_support import load_env

from dumpstagram._private.web.bootstrap import ORIGIN

PLANNED = 7
CONDITIONAL = 3
DEFAULT_TERM = "instagram"


async def body(replay: E2Replay) -> None:
   environment = load_env()
   query = environment.get("IG_E2_SEARCH_QUERY") or DEFAULT_TERM
   hashtag = (environment.get("IG_E2_HASHTAG") or DEFAULT_TERM).lstrip("#")
   replay.record("inputs", {"query_length": len(query), "hashtag_length": len(hashtag)})

   await replay.bootstrap()

   for attempt in (1, 2):
      recent = await replay.graphql(
         "read-recent-searches",
         {},
         referer=f"{ORIGIN}/",
         label=f"recent searches {attempt}",
         try_other_path_on_null=attempt == 1,
      )
      entries = dig(recent, "data", "xig_recent_searches", "recent_searches") or []
      replay.record(f"recent_{attempt}", {"entries": len(entries)})

      if recent is not None:
         replay.shape("recent_searches", entries)

   for attempt in (1, 2):
      typeahead = await replay.graphql(
         "search-typeahead-non-personalised",
         {"hasQuery": True, "query": query},
         referer=f"{ORIGIN}/",
         label=f"non-personalised typeahead {attempt}",
         try_other_path_on_null=attempt == 1,
      )
      users = dig(typeahead, "data", "xdt_api__v1__fbsearch__non_profiled_serp", "users") or []
      replay.record(f"typeahead_{attempt}", {"users": len(users)})

      if typeahead is not None:
         replay.shape("non_personalised_typeahead", dig(typeahead, "data"))

   for attempt in (1, 2):
      header = await replay.graphql(
         "read-a-hashtag-header",
         {"tag_name": hashtag},
         referer=f"{ORIGIN}/explore/tags/{hashtag}/",
         label=f"hashtag header {attempt}",
         try_other_path_on_null=attempt == 1,
      )

      if header is not None:
         replay.shape("hashtag_header", dig(header, "data"))


if __name__ == "__main__":
   sys.exit(asyncio.run(run_probe("e2-search", PLANNED, CONDITIONAL, body)))
