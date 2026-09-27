"""Map the recent searches, the non-personalised typeahead and a hashtag's header into typed
models.

Built from the answers ``probes/e2_search.py`` kept on 2026-09-27. Dropped, and why:

- on an account row of either list, ``search_social_context`` and
  ``search_social_context_snippet_type``, a line of text the search box prints under the row (a
  follower count on the typeahead, mutual followers on the recent searches), which is
  presentation and names other accounts, ``unseen_count``, 0 on every row,
  ``aigm_account_label_info``, disabled on every row, ``ai_agent_owner_username``, null on every
  row, ``__typename``, and what :func:`parse_profile_summary` already drops
- on a keyword entry, ``id``, null on all 22 read
- on the typeahead, ``inform_module``, null on both answers
"""

from __future__ import annotations

from typing import Any

from dumpstagram._private.web.parse.common import _object_at, _required_string
from dumpstagram._private.web.parse.profiles import _list_of, parse_profile_summary
from dumpstagram.errors import SchemaChanged
from dumpstagram.models import Hashtag, ProfileSummary, RecentSearch, RecentSearchKind

__all__ = [
   "HASHTAG_HEADER_PATH",
   "NON_PERSONALISED_TYPEAHEAD_PATH",
   "RECENT_SEARCHES_PATH",
   "parse_hashtag_header",
   "parse_non_personalised_typeahead",
   "parse_recent_searches",
]

RECENT_SEARCHES_PATH = ("data", "xig_recent_searches")
"""The path to the object carrying ``recent_searches``."""

NON_PERSONALISED_TYPEAHEAD_PATH = ("data", "xdt_api__v1__fbsearch__non_profiled_serp")
"""The path to the object carrying the typeahead's ``users``."""

HASHTAG_HEADER_PATH = ("data", "fetch__XDTTagInfo")
"""The path to the hashtag's header."""


def _recent_search(entry: Any, path: str) -> RecentSearch:
   """One recent search, reduced to the one slot the upstream filled.

   Exactly one slot was non-null on all 30 entries read. Two filled slots, or none, raises, as a
   timeline item does, and so does a slot :class:`RecentSearchKind` does not name.
   """

   if not isinstance(entry, dict):
      raise SchemaChanged(f"{path} is not an object", path=path)

   filled = [key for key, value in entry.items() if value is not None]

   if len(filled) != 1:
      raise SchemaChanged(
         f"{path} filled {len(filled)} of its slots rather than exactly one", path=path
      )

   slot = filled[0]

   try:
      kind = RecentSearchKind(slot)
   except ValueError as failure:
      raise SchemaChanged(
         f"{path}.{slot} is a recent search slot this version does not know", path=path
      ) from failure

   if kind is RecentSearchKind.ACCOUNT:
      return RecentSearch(kind=kind, account=parse_profile_summary(entry[slot], f"{path}.{slot}"))

   if kind is RecentSearchKind.KEYWORD:
      keyword_path = f"{path}.{slot}"
      keyword = _required_string(entry[slot], "name", keyword_path)

      return RecentSearch(kind=kind, keyword=keyword)

   return RecentSearch(kind=kind)


def parse_recent_searches(payload: Any) -> tuple[RecentSearch, ...]:
   """One ``PolarisSearchNullStateQuery`` payload, the entries in the upstream's order.

   Finding: ``read-recent-searches``.
   """

   root = _object_at(payload, RECENT_SEARCHES_PATH)
   root_path = ".".join(RECENT_SEARCHES_PATH)
   entries = _list_of(root, "recent_searches", root_path)

   return tuple(
      _recent_search(entry, f"{root_path}.recent_searches[{index}]")
      for index, entry in enumerate(entries)
   )


def parse_non_personalised_typeahead(payload: Any) -> tuple[ProfileSummary, ...]:
   """One ``PolarisSearchBoxNonProfiledRefetchableQuery`` payload, the accounts in its order.

   The root carried ``users`` and ``inform_module`` and nothing else on both answers, no
   hashtags, no places and no cursor, so the list is whole as sent (W83).

   Finding: ``search-typeahead-non-personalised``.
   """

   root = _object_at(payload, NON_PERSONALISED_TYPEAHEAD_PATH)
   root_path = ".".join(NON_PERSONALISED_TYPEAHEAD_PATH)
   users = _list_of(root, "users", root_path)

   return tuple(
      parse_profile_summary(user, f"{root_path}.users[{index}]") for index, user in enumerate(users)
   )


def parse_hashtag_header(payload: Any, tag: str) -> Hashtag:
   """One ``PolarisHashtagHeaderActionButtonsQuery`` payload, the header of ``tag``.

   The answer names the tag's id and nothing else, so ``name`` is the tag that was asked for.

   Finding: ``read-a-hashtag-header``.
   """

   header = _object_at(payload, HASHTAG_HEADER_PATH)
   header_path = ".".join(HASHTAG_HEADER_PATH)

   return Hashtag(id=_required_string(header, "id", header_path), name=tag)
