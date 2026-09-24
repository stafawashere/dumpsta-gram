"""``client.feeds``, the timelines a signed-in account reads."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dumpstagram._core.feed import read_feed_page
from dumpstagram.models import FeedItem, Page

if TYPE_CHECKING:
   from dumpstagram.aio import AsyncClient
   from dumpstagram.client import SyncClient

__all__ = ["AsyncFeeds", "SyncFeeds"]


class AsyncFeeds:
   """The timelines, as ``client.feeds`` on :class:`~dumpstagram.aio.AsyncClient`."""

   _client: AsyncClient

   def __init__(self) -> None:
      raise TypeError("an AsyncFeeds comes from AsyncClient.feeds, it is not built directly")

   @classmethod
   def _of(cls, client: AsyncClient) -> AsyncFeeds:
      namespace = object.__new__(cls)
      namespace._client = client

      return namespace

   async def home(self, *, after: str | None = None) -> Page[FeedItem]:
      """Read one page of the signed-in account's home timeline. One live request.

      ``after`` is an ``end_cursor`` from a previous page, and omitting it asks for the first
      page. Under the default behavior the first page is read out of the home document, as a
      browser reads it, and it is short: four measured loads carried 3 or 4 items.
      :attr:`~dumpstagram.behavior.Behavior.feed_first_page` set to
      :attr:`~dumpstagram.behavior.FeedFirstPage.QUERY` asks the pagination query instead.

      The returned page holds :class:`~dumpstagram.models.FeedItem` rather than posts, because
      most of a timeline is not posts: of fifteen measured items, six were posts and the rest
      were advertisements and suggestions. An item carrying a post has
      :attr:`~dumpstagram.models.FeedItem.kind` equal to
      :attr:`~dumpstagram.models.FeedItemKind.POST`, and every other kind is reported by name
      and carries nothing.

      The page's length is the upstream's decision. Three measured pages carried 14, 12 and 5
      items for the same request, so a caller collecting posts keeps asking and stops on
      ``has_next_page``, never on a page looking short.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_feed_page(
            client._sender,
            client._session,
            after=after,
            first_page=client._behavior.feed_first_page,
            companions=client._behavior.page_load_companions,
            cookie_sync=client._cookie_sync_if_on(),
            user_agent=client._user_agent,
         )
      )


class SyncFeeds:
   """The timelines, as ``client.feeds`` on :class:`~dumpstagram.client.SyncClient`. Each
   method blocks on the shared loop thread and answers as its :class:`AsyncFeeds` twin does."""

   _client: SyncClient

   def __init__(self) -> None:
      raise TypeError("a SyncFeeds comes from SyncClient.feeds, it is not built directly")

   @classmethod
   def _of(cls, client: SyncClient) -> SyncFeeds:
      namespace = object.__new__(cls)
      namespace._client = client

      return namespace

   def home(self, *, after: str | None = None) -> Page[FeedItem]:
      """Read one page of the home timeline. Blocks until it has one.

      The same call as :meth:`AsyncFeeds.home`, run on the shared loop thread. One live
      request.
      """

      return self._client._loop.run(
         self._client._impl.feeds.home(after=after),
         operation="SyncClient.feeds.home",
      )
