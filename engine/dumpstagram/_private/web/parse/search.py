"""Map the recent searches, both typeaheads, a hashtag's header and the keyword grid into typed
models.

Built from the answers ``probes/e2_search.py`` and ``probes/e2_capture_replays.py --stage
search`` kept on 2026-09-27. Dropped, and why:

- on an account row of either list, ``search_social_context`` and
  ``search_social_context_snippet_type``, a line of text the search box prints under the row (a
  follower count on the typeahead, mutual followers on the recent searches), which is
  presentation and names other accounts, ``unseen_count``, 0 on every row,
  ``aigm_account_label_info``, disabled on every row, ``ai_agent_owner_username``, null on every
  row, ``__typename``, and what :func:`parse_profile_summary` already drops
- on a keyword entry, ``id``, null on all 22 read
- on the typeahead, ``inform_module``, null on both answers
- on the personalised typeahead, the account row's ``is_unpublished``, ``live_broadcast_id`` and
  ``live_broadcast_visibility`` and the keys above, a keyword's ``id``, a number that no read
  takes, ``see_more.preview_number``, 5 on both answers, how many rows the box previews,
  ``inform_module``, null on both, and ``rank_token``, which only a later query of the same
  search session would send back, and no search here sends one (W102)
- on the keyword grid, ``xdt_viewer``, the viewer's own id and a flag, each edge's ``cursor``,
  null but on the last edge, where it repeats ``page_info.end_cursor``, which nothing here
  follows, and on a post ``organic_tracking_token``, ``is_dash_eligible``,
  ``number_of_qualities``, ``comments_disabled``, null on all 48, ``carousel_media``, whose
  slides carry no kind, and the author's ``pk``, equal to its ``id`` (W103)
"""

from __future__ import annotations

from typing import Any

from dumpstagram._private.web.parse.common import (
   _object_at,
   _optional_flag,
   _optional_integer,
   _optional_string,
   _required,
   _required_flag,
   _required_integer,
   _required_string,
)
from dumpstagram._private.web.parse.media import (
   _caption_text,
   _duration_if_video,
   _images,
   _post_author,
   _taken_at,
   _videos,
)
from dumpstagram._private.web.parse.profiles import _list_of, parse_profile_summary
from dumpstagram.errors import SchemaChanged
from dumpstagram.models import (
   Hashtag,
   KeywordResults,
   ProfileSummary,
   RecentSearch,
   RecentSearchKind,
   SearchPost,
   SearchResult,
   SearchResultKind,
   SearchResults,
)

__all__ = [
   "EMPTY_KEYWORD_UNITS",
   "HASHTAG_HEADER_PATH",
   "KEYWORD_GRID_UNIT",
   "KEYWORD_RESULTS_PATH",
   "NON_PERSONALISED_TYPEAHEAD_PATH",
   "PERSONALISED_TYPEAHEAD_PATH",
   "RECENT_SEARCHES_PATH",
   "accounts_in_order",
   "parse_hashtag_header",
   "parse_keyword_results",
   "parse_non_personalised_typeahead",
   "parse_personalised_typeahead",
   "parse_recent_searches",
   "results_of_accounts",
]

RECENT_SEARCHES_PATH = ("data", "xig_recent_searches")
"""The path to the object carrying ``recent_searches``."""

NON_PERSONALISED_TYPEAHEAD_PATH = ("data", "xdt_api__v1__fbsearch__non_profiled_serp")
"""The path to the object carrying the typeahead's ``users``."""

HASHTAG_HEADER_PATH = ("data", "fetch__XDTTagInfo")
"""The path to the hashtag's header."""

PERSONALISED_TYPEAHEAD_PATH = ("data", "xdt_api__v1__fbsearch__topsearch_connection")
"""The path to the object carrying the personalised typeahead's four lists."""

KEYWORD_RESULTS_PATH = ("data", "xdt_fbsearch__top_serp_graphql")
"""The path to the keyword grid's connection."""

KEYWORD_GRID_UNIT = "XDTTopSerpMediaGridUnit"
"""The keyword grid's row of posts, three to a row on all 16 rows read."""

EMPTY_KEYWORD_UNITS = frozenset({"XDTTopSerpHeaderUnit", "XDTTopSerpAccountsHCMUnit"})
"""The keyword page's header rows and its accounts row, which carried nothing but their
``__typename`` on both answers read, so they carry nothing to map (W103)."""


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


def _positioned(row: Any, path: str) -> int:
   return _required_integer(row, "position", path)


def _account_result(row: Any, path: str) -> SearchResult:
   return SearchResult(
      kind=SearchResultKind.ACCOUNT,
      position=_positioned(row, path),
      account=parse_profile_summary(_required(row, "user", path), f"{path}.user"),
   )


def _keyword_result(row: Any, path: str) -> SearchResult:
   keyword = _object_at(row, ("keyword",))

   return SearchResult(
      kind=SearchResultKind.KEYWORD,
      position=_positioned(row, path),
      keyword=_required_string(keyword, "name", f"{path}.keyword"),
   )


def _keyword_rows(root: dict[str, Any], root_path: str) -> list[Any]:
   """The keyword suggestions under ``see_more.list``. ``see_more`` was an object on both answers
   read; a null one is read as no suggestions, since a query the upstream has none for is the
   plausible reason for it (INFERENCE, not observed)."""

   see_more = _required(root, "see_more", root_path)

   if see_more is None:
      return []

   see_more_path = f"{root_path}.see_more"

   if not isinstance(see_more, dict):
      raise SchemaChanged(f"{see_more_path} is not an object or null", path=see_more_path)

   return _list_of(see_more, "list", see_more_path)


def parse_personalised_typeahead(payload: Any) -> SearchResults:
   """One ``PolarisSearchBoxRefetchableQuery`` payload, the rows in the order the box shows them.

   Accounts and keywords carry ``position``, the upstream's place for the row in the blended
   list, and are ordered by it, ties in the order the lists arrived. A hashtag or a place row is
   carried by its kind alone after them, in the upstream's order, since neither shape has been
   read (W102).

   Finding: ``search-typeahead-personalised-as-sent``.
   """

   root = _object_at(payload, PERSONALISED_TYPEAHEAD_PATH)
   root_path = ".".join(PERSONALISED_TYPEAHEAD_PATH)
   keywords = [
      _keyword_result(row, f"{root_path}.see_more.list[{index}]")
      for index, row in enumerate(_keyword_rows(root, root_path))
   ]
   accounts = [
      _account_result(row, f"{root_path}.users[{index}]")
      for index, row in enumerate(_list_of(root, "users", root_path))
   ]
   hashtags = [
      SearchResult(kind=SearchResultKind.HASHTAG) for _ in _list_of(root, "hashtags", root_path)
   ]
   places = [SearchResult(kind=SearchResultKind.PLACE) for _ in _list_of(root, "places", root_path)]
   positioned = sorted([*keywords, *accounts], key=lambda result: result.position or 0)

   return SearchResults(results=(*positioned, *hashtags, *places))


def accounts_in_order(results: SearchResults) -> tuple[ProfileSummary, ...]:
   """The account rows of ``results``, in the order the box shows them."""

   return tuple(result.account for result in results.results if result.account is not None)


def results_of_accounts(accounts: tuple[ProfileSummary, ...]) -> SearchResults:
   """The non-personalised route's accounts as search results, in its order, with no position,
   since that answer carries none."""

   return SearchResults(
      results=tuple(
         SearchResult(kind=SearchResultKind.ACCOUNT, account=account) for account in accounts
      )
   )


def _search_post(node: Any, path: str) -> SearchPost:
   if not isinstance(node, dict):
      raise SchemaChanged(f"{path} is not an object", path=path)

   videos = _videos(node, path)

   return SearchPost(
      id=_required_string(node, "id", path),
      pk=_required_string(node, "pk", path),
      code=_required_string(node, "code", path),
      taken_at=_taken_at(node, path),
      author=_post_author(node, path, hd_picture_if_carried=True),
      media_type=_required_integer(node, "media_type", path),
      like_count=_required_integer(node, "like_count", path),
      comment_count=_required_integer(node, "comment_count", path),
      like_and_view_counts_disabled=_required_flag(node, "like_and_view_counts_disabled", path),
      caption=_caption_text(node, path),
      accessibility_caption=_optional_string(node, "accessibility_caption", path),
      original_width=_optional_integer(node, "original_width", path),
      original_height=_optional_integer(node, "original_height", path),
      carousel_media_count=_optional_integer(node, "carousel_media_count", path),
      images=_images(node, path),
      videos=videos,
      video_duration=_duration_if_video(node, videos, path),
      has_audio=_optional_flag(node, "has_audio", path),
      view_count=_optional_integer(node, "view_count", path),
   )


def _unit_posts(unit: Any, path: str) -> list[SearchPost]:
   """The posts of one row of the page. A grid row's are read; a header or accounts row that
   carries anything beside its kind raises, as does a row of a kind this version does not know,
   because a post it held would otherwise go missing unseen."""

   kind = _required_string(unit, "__typename", path)

   if kind == KEYWORD_GRID_UNIT:
      items = _list_of(unit, "items", path)

      return [_search_post(item, f"{path}.items[{index}]") for index, item in enumerate(items)]

   carries_something = any(value is not None for key, value in unit.items() if key != "__typename")
   is_an_empty_row = kind in EMPTY_KEYWORD_UNITS and not carries_something

   if not is_an_empty_row:
      raise SchemaChanged(f"{path} is a {kind} row this version does not read", path=path)

   return []


def parse_keyword_results(payload: Any) -> KeywordResults:
   """One ``PolarisKeywordSearchExplorePageRelayQuery`` payload, the grid's posts in the order the
   page shows them, and the upstream's flag that the grid goes on (W103).

   Finding: ``read-keyword-search-results``.
   """

   connection = _object_at(payload, KEYWORD_RESULTS_PATH)
   connection_path = ".".join(KEYWORD_RESULTS_PATH)
   edges = _list_of(connection, "edges", connection_path)
   posts = [
      post
      for index, edge in enumerate(edges)
      for post in _unit_posts(_object_at(edge, ("node",)), f"{connection_path}.edges[{index}].node")
   ]
   page_info_path = f"{connection_path}.page_info"
   page_info = _object_at(connection, ("page_info",))

   return KeywordResults(
      posts=tuple(posts),
      has_more=_required_flag(page_info, "has_next_page", page_info_path),
   )
