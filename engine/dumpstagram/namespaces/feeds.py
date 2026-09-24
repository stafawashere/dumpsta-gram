"""``client.feeds``, the timelines a signed-in account reads."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING

from dumpstagram._core.feed import read_feed_page
from dumpstagram._core.paging import check_limit, iterate_pages, iterate_pages_blocking
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

   def iter_home(self, *, limit: int | None, after: str | None = None) -> AsyncIterator[FeedItem]:
      """Walk the home timeline item by item, reading a page with :meth:`home` each time the
      one before it is used up. Use it with ``async for``, and do not await it.

      ``limit`` is required and counts items. The walk stops once that many have been yielded,
      without reading a page it would not use, and ``limit=None`` walks until
      ``has_next_page`` is false, which on a home timeline may be never. ``after`` starts the
      walk from a cursor instead of the first page.

      Each page is one read with everything :meth:`home` sends for it, paced as any read is,
      and never read ahead of the caller. An empty page that says more exist is followed, and
      a page that says more exist with no cursor raises
      :class:`~dumpstagram.errors.SchemaChanged`. A negative ``limit`` raises
      :class:`ValueError` before anything is sent.
      """

      check_limit(limit)

      return iterate_pages(lambda cursor: self.home(after=cursor), limit=limit, after=after)


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

   def iter_home(self, *, limit: int | None, after: str | None = None) -> Iterator[FeedItem]:
      """Walk the home timeline item by item. Blocks while each page is read.

      The same walk as :meth:`AsyncFeeds.iter_home`, with the same ``limit``, each page read on
      the shared loop thread. Exceptions cross back as themselves, with a note naming this
      method. Closing the iterator early leaves nothing running, because no page is read
      ahead.
      """

      check_limit(limit)
      client = self._client

      def read_page(cursor: str | None) -> Page[FeedItem]:
         return client._loop.run(
            client._impl.feeds.home(after=cursor),
            operation="SyncClient.feeds.iter_home",
         )

      return iterate_pages_blocking(read_page, limit=limit, after=after)
