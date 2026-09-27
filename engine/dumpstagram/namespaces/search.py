"""``client.search``, reading the viewer's recent searches, the accounts a query matches and a
hashtag's header.

The accounts come from the search box's non-personalised typeahead. A signed-in browser's search
box is believed to send the personalised one, whose variables have not been observed, so this is
a named departure from browser parity until the capture night (W83).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dumpstagram._core.search import (
   read_hashtag_header,
   read_non_personalised_typeahead,
   read_recent_searches,
)
from dumpstagram.models import Hashtag, ProfileSummary, RecentSearch

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
      """Read the accounts ``query`` matches, as the search box's non-personalised typeahead
      ranks them. One live request, and a bootstrap when the session holds no page token.

      The ranking does not use the viewer's profile: it is the query a search box sends when
      personalisation is off, and a signed-in browser is believed to send the personalised one
      instead, whose accounts, hashtags and places are not read yet. Two reads of the same query
      answered the same 18 accounts in the same order. The answer carries accounts only, whole
      as sent, with nothing to page on. A row carries no relationship to the viewer and no
      ``is_private``.

      An empty or blank ``query`` raises :class:`ValueError` before anything is sent. Searching
      is not added to the recent searches: a browser adds an entry when a result is opened, and
      nothing is opened.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_non_personalised_typeahead(
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
      """Read the accounts ``query`` matches, ranked without the viewer's profile. Blocks until
      it has them.

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
