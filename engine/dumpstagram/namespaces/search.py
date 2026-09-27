"""``client.search``, reading the viewer's recent searches, what the search box offers for a
query, the accounts a query matches, a hashtag's header and the keyword grid.

The search box's results and accounts come from the personalised typeahead a signed-in
browser's search box sends, and
:attr:`~dumpstagram.behavior.Behavior.typeahead_route` set to
:attr:`~dumpstagram.behavior.TypeaheadRoute.NON_PERSONALISED` sends the non-profiled one instead,
a named departure (W102).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dumpstagram._core.search import (
   read_hashtag_header,
   read_keyword_results,
   read_recent_searches,
   read_top_results,
   read_typeahead_accounts,
)
from dumpstagram.models import (
   Hashtag,
   KeywordResults,
   ProfileSummary,
   RecentSearch,
   SearchResults,
)

if TYPE_CHECKING:
   from dumpstagram.aio import AsyncClient
   from dumpstagram.client import SyncClient

__all__ = ["AsyncSearch", "SyncSearch"]


class AsyncSearch:
   """Search, as ``client.search`` on :class:`~dumpstagram.aio.AsyncClient`."""

   _client: AsyncClient

   def __init__(self) -> None:
      raise TypeError("an AsyncSearch comes from AsyncClient.search, it is not built directly")

   @classmethod
   def _of(cls, client: AsyncClient) -> AsyncSearch:
      namespace = object.__new__(cls)
      namespace._client = client

      return namespace

   async def recent(self) -> tuple[RecentSearch, ...]:
      """Read the viewer's recent searches, newest first as the upstream orders them. One live
      request, and a bootstrap when the session holds no page token.

      Each entry is an account or a keyword, named by
      :attr:`~dumpstagram.models.RecentSearch.kind`. A hashtag or a place entry is reported by
      its kind with no payload, because neither shape has been read. The list is whole as sent,
      with nothing to page on.

      A browser reads this when its search panel opens. This sends it alone, with the site root
      as its referer, a departure recorded in ``docs/web-request-contract.md``.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_recent_searches(
            client._sender,
            client._session,
            user_agent=client._user_agent,
         )
      )

   async def accounts(self, query: str) -> tuple[ProfileSummary, ...]:
      """Read the accounts ``query`` matches, as the search box ranks them. One live request, and
      a bootstrap when the session holds no page token.

      Under the default behavior this sends the personalised typeahead a signed-in browser's
      search box sends and returns its accounts in the order the box shows them, which is what
      :meth:`top` reads with the keywords left out. One measured query answered 5 accounts.
      :attr:`~dumpstagram.behavior.Behavior.typeahead_route` set to
      :attr:`~dumpstagram.behavior.TypeaheadRoute.NON_PERSONALISED` sends the non-profiled
      typeahead instead, ranked without the viewer's profile, which answered 18 accounts for the
      same kind of query; that is the query this method sent before E2 batch 11b (W102). The
      answer is whole as sent, with nothing to page on. A row carries no relationship to the
      viewer and no ``is_private``.

      An empty or blank ``query`` raises :class:`ValueError` before anything is sent. Searching
      is not added to the recent searches: a browser adds an entry when a result is opened, and
      nothing is opened.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_typeahead_accounts(
            client._sender,
            client._session,
            query,
            route=client._behavior.typeahead_route,
            user_agent=client._user_agent,
         )
      )

   async def top(self, query: str) -> SearchResults:
      """Read what the search box offers for ``query``: accounts and keyword suggestions, and
      hashtags and places when the upstream offers them. One live request, and a bootstrap when
      the session holds no page token.

      The rows arrive in the order the box shows them, each with its
      :class:`~dumpstagram.models.SearchResultKind`. One measured query answered one keyword at
      position 0 and five accounts after it, and no hashtag or place; a hashtag or a place row is
      reported by its kind with no payload, since neither shape has been read. A keyword row's
      text is what :meth:`keyword` reads the grid of.

      Each call is the first query of a search session of its own, with a fresh session id and
      no rank token, as a browser's first query after the panel opens. A browser typing sends a
      query per pause in the same session; this sends one. Under
      :attr:`~dumpstagram.behavior.TypeaheadRoute.NON_PERSONALISED` it sends the non-profiled
      typeahead and the rows are accounts with no position (W102).

      An empty or blank ``query`` raises :class:`ValueError` before anything is sent. Nothing is
      added to the recent searches.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_top_results(
            client._sender,
            client._session,
            query,
            route=client._behavior.typeahead_route,
            user_agent=client._user_agent,
         )
      )

   async def keyword(self, query: str) -> KeywordResults:
      """Read the first page of the grid a keyword search shows. One live request, and a
      bootstrap when the session holds no page token.

      ``query`` is the text searched for, such as a keyword row :meth:`top` returned. A
      hashtag's page is this same grid for the tag with its ``#``: a browser sent to
      ``/explore/tags/<tag>/`` lands on the keyword page for ``#<tag>``, so
      ``keyword("#" + tag)`` reads the posts under a tag and :meth:`hashtag` its header (W103).

      Each post is a :class:`~dumpstagram.models.SearchPost`, the grid's own lighter shape. Only
      the first page is read, since no later page has been observed:
      :attr:`~dumpstagram.models.KeywordResults.has_more` is the upstream's flag that the grid
      goes on, and there is no cursor and no ``iter_keyword``. Two measured pages held 24 posts.

      A browser reads the grid inside the keyword page's load, beside the hashtag header query.
      This sends it alone, with the keyword page as its referer and a fresh page session id sent
      as both of the grid's session ids. An empty or blank ``query`` raises :class:`ValueError`
      before anything is sent.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_keyword_results(
            client._sender,
            client._session,
            query,
            user_agent=client._user_agent,
         )
      )

   async def hashtag(self, tag: str) -> Hashtag:
      """Read the header of a hashtag's page. One live request, and a bootstrap when the session
      holds no page token.

      ``tag`` is the name without its ``#``, letters, digits and underscores; a ``#`` or anything
      else raises :class:`ValueError` before anything is sent. The header carries the tag's id
      and nothing more. The posts under the tag are not read yet.

      A browser reads this inside the tag page's load. This sends it alone, with the tag's page
      as its referer.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_hashtag_header(
            client._sender,
            client._session,
            tag,
            user_agent=client._user_agent,
         )
      )


class SyncSearch:
   """Search, as ``client.search`` on :class:`~dumpstagram.client.SyncClient`. Each method
   blocks on the shared loop thread and answers as its :class:`AsyncSearch` twin does."""

   _client: SyncClient

   def __init__(self) -> None:
      raise TypeError("a SyncSearch comes from SyncClient.search, it is not built directly")

   @classmethod
   def _of(cls, client: SyncClient) -> SyncSearch:
      namespace = object.__new__(cls)
      namespace._client = client

      return namespace

   def recent(self) -> tuple[RecentSearch, ...]:
      """Read the viewer's recent searches. Blocks until it has them.

      The same call as :meth:`AsyncSearch.recent`, run on the shared loop thread. One live
      request.
      """

      return self._client._loop.run(
         self._client._impl.search.recent(),
         operation="SyncClient.search.recent",
      )

   def accounts(self, query: str) -> tuple[ProfileSummary, ...]:
      """Read the accounts ``query`` matches, as the search box ranks them. Blocks until it has
      them.

      The same call as :meth:`AsyncSearch.accounts`, run on the shared loop thread. One live
      request.
      """

      return self._client._loop.run(
         self._client._impl.search.accounts(query),
         operation="SyncClient.search.accounts",
      )

   def hashtag(self, tag: str) -> Hashtag:
      """Read the header of a hashtag's page. Blocks until it has it.

      The same call as :meth:`AsyncSearch.hashtag`, run on the shared loop thread. One live
      request.
      """

      return self._client._loop.run(
         self._client._impl.search.hashtag(tag),
         operation="SyncClient.search.hashtag",
      )

   def top(self, query: str) -> SearchResults:
      """Read what the search box offers for ``query``. Blocks until it has it.

      The same call as :meth:`AsyncSearch.top`, run on the shared loop thread. One live request.
      """

      return self._client._loop.run(
         self._client._impl.search.top(query),
         operation="SyncClient.search.top",
      )

   def keyword(self, query: str) -> KeywordResults:
      """Read the first page of the grid a keyword search shows. Blocks until it has it.

      The same call as :meth:`AsyncSearch.keyword`, run on the shared loop thread. One live
      request.
      """

      return self._client._loop.run(
         self._client._impl.search.keyword(query),
         operation="SyncClient.search.keyword",
      )
