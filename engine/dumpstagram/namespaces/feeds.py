"""``client.feeds``, the timelines a signed-in account reads: the home timeline, the explore grid,
a place's page, and whether the home feed has new posts."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING

from dumpstagram._core.discovery import (
   read_explore_grid,
   read_location_info,
   read_location_posts,
   read_new_feed_posts,
)
from dumpstagram._core.feed import read_feed_page
from dumpstagram._core.paging import check_limit, iterate_pages, iterate_pages_blocking
from dumpstagram.models import ExploreGrid, FeedItem, LocationPosts, LocationTab, Page, Place

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

   async def explore(self) -> ExploreGrid:
      """Read the first page of the explore grid. One live request.

      The grid arrives in sections, each a large tile's reel and the smaller tiles beside it,
      and every post is a :class:`~dumpstagram.models.Post`, read from the explore grid's own
      media shape. ``is_seen`` reads False on every post, since the grid never sends it.
      :attr:`~dumpstagram.models.ExploreGrid.more_available` is the upstream's flag that the grid
      goes on. No later page is read, because how a browser asks for one has not been observed,
      so there is no cursor and no ``iter_explore``.

      A browser reads the grid inside the ``/explore/`` page load. This sends it alone, with that
      page as its referer, a departure recorded in ``docs/web-request-contract.md``.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_explore_grid(
            client._sender,
            client._session,
            user_agent=client._user_agent,
         )
      )

   async def place(self, location_id: str) -> Place:
      """Read the header of a place's page: its name, category, address, coordinates and how
      many posts are tagged there. One live request.

      ``location_id`` is the place's numeric ``pk``, :attr:`Location.id
      <dumpstagram.models.Location.id>` on a post tagged there, and anything but digits raises
      :class:`ValueError` before anything is sent. :meth:`location` reads the place's posts.

      A browser reads the header inside the place's page load. This sends it alone, with the
      place's page as its referer.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_location_info(
            client._sender,
            client._session,
            location_id,
            user_agent=client._user_agent,
         )
      )

   async def location(
      self, location_id: str, *, tab: LocationTab = LocationTab.RANKED
   ) -> LocationPosts:
      """Read the first page of the posts tagged at a place. One live request.

      ``location_id`` is the place's numeric ``pk``, as :meth:`place` takes it, and anything but
      digits raises :class:`ValueError` before anything is sent. ``tab`` is which of the place's
      grids to read, and only :attr:`~dumpstagram.models.LocationTab.RANKED` has been observed.

      Each post is a :class:`~dumpstagram.models.PostThumbnail`, because the grid sends its
      author without a full name, so it cannot be a :class:`~dumpstagram.models.Post` without a
      guess. :meth:`~dumpstagram.namespaces.media.AsyncMedia.by_code` with its ``code`` reads the
      whole post. The page's length is the upstream's decision: two measured pages carried 21
      posts for a request of 12.

      Only the first page is read. :attr:`~dumpstagram.models.LocationPosts.has_more` is the
      upstream's own flag that the grid goes on, but the query that pages it answered the first
      page's cursor with that same cursor and mostly the same posts, so there is no cursor to
      pass and no ``iter_location``.

      A browser reads the grid inside the place's page load. This sends it alone, with the
      place's page as its referer.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_location_posts(
            client._sender,
            client._session,
            location_id,
            tab=tab,
            user_agent=client._user_agent,
         )
      )

   async def has_new_posts(self) -> bool:
      """Ask whether the home feed has posts newer than the viewer last loaded. One live
      request.

      The answer is the upstream's own flag, false on both measured reads. A browser asks from
      the home page to decide whether to offer new posts. This sends it alone, with the site
      root as its referer.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_new_feed_posts(
            client._sender,
            client._session,
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

   def explore(self) -> ExploreGrid:
      """Read the first page of the explore grid. Blocks until it has it.

      The same call as :meth:`AsyncFeeds.explore`, run on the shared loop thread. One live
      request.
      """

      return self._client._loop.run(
         self._client._impl.feeds.explore(),
         operation="SyncClient.feeds.explore",
      )

   def place(self, location_id: str) -> Place:
      """Read the header of a place's page. Blocks until it has it.

      The same call as :meth:`AsyncFeeds.place`, run on the shared loop thread. One live
      request.
      """

      return self._client._loop.run(
         self._client._impl.feeds.place(location_id),
         operation="SyncClient.feeds.place",
      )

   def location(self, location_id: str, *, tab: LocationTab = LocationTab.RANKED) -> LocationPosts:
      """Read the first page of the posts tagged at a place. Blocks until it has it.

      The same call as :meth:`AsyncFeeds.location`, run on the shared loop thread. One live
      request.
      """

      return self._client._loop.run(
         self._client._impl.feeds.location(location_id, tab=tab),
         operation="SyncClient.feeds.location",
      )

   def has_new_posts(self) -> bool:
      """Ask whether the home feed has new posts. Blocks until it has the answer.

      The same call as :meth:`AsyncFeeds.has_new_posts`, run on the shared loop thread. One live
      request.
      """

      return self._client._loop.run(
         self._client._impl.feeds.has_new_posts(),
         operation="SyncClient.feeds.has_new_posts",
      )
