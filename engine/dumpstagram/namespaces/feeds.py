"""``client.feeds``, the timelines a signed-in account reads: the home timeline, the explore grid,
a place's page, whether the home feed has new posts, the reels feed, and an audio's page."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING

from dumpstagram._core.discovery import (
   audio_clips_page,
   explore_posts_page,
   read_audio_page,
   read_explore_grid,
   read_location_info,
   read_location_posts,
   read_new_feed_posts,
   read_reels_feed_page,
)
from dumpstagram._core.feed import read_feed_page
from dumpstagram._core.paging import check_limit, iterate_pages, iterate_pages_blocking
from dumpstagram.models import (
   AudioPage,
   ExploreGrid,
   FeedItem,
   LocationPosts,
   LocationTab,
   Page,
   Place,
   Post,
)

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

   async def explore(self, *, after: str | None = None) -> ExploreGrid:
      """Read one page of the explore grid. One live request.

      ``after`` is the ``end_cursor`` of a page this method returned, and omitting it asks for
      the first page. The grid arrives in sections, each a large tile's reel and the smaller tiles
      beside it, and every post is a :class:`~dumpstagram.models.Post`, read from the explore
      grid's own media shape. ``is_seen`` reads False on every post, since the grid never sends
      it. A first page read carried 20 posts in four sections and a later page 18 in six.

      :attr:`~dumpstagram.models.ExploreGrid.more_available` is the upstream's own flag that the
      grid goes on, and it is the only thing that ends a walk; it was true on every page read.
      :meth:`iter_explore` walks the grid post by post.

      A browser reads the first page inside the ``/explore/`` page load and each later page as the
      grid is scrolled. This sends each alone, with that page as its referer, a departure recorded
      in ``docs/web-request-contract.md``.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_explore_grid(
            client._sender,
            client._session,
            after=after,
            user_agent=client._user_agent,
         )
      )

   async def explore_posts(self, *, after: str | None = None) -> Page[Post]:
      """Read one page of the explore grid as a plain page of posts. One live request.

      The same read as :meth:`explore`, returned as a :class:`~dumpstagram.models.Page`: every
      post in the grid's order, ``has_next_page`` the upstream's ``more_available`` and
      ``end_cursor`` the same cursor :meth:`explore` hands out, so the two take each other's
      cursors. It is the page :meth:`iter_explore` walks.
      """

      grid = await self.explore(after=after)

      return explore_posts_page(grid)

   def iter_explore(self, *, limit: int | None, after: str | None = None) -> AsyncIterator[Post]:
      """Walk the explore grid post by post, reading a page with :meth:`explore_posts` each time
      the one before it is used up. Use it with ``async for``, and do not await it.

      ``limit`` is required and counts posts. The walk stops once that many have been yielded,
      without reading a page it would not use, and ``limit=None`` walks until the upstream's
      ``more_available`` is false, which on the explore grid may be never. ``after`` starts the
      walk from a cursor :meth:`explore` or :meth:`explore_posts` returned. Each page is one
      read, paced as any read is, and never read ahead of the caller. A page that says more
      exist with no cursor raises :class:`~dumpstagram.errors.SchemaChanged`, and a negative
      ``limit`` raises :class:`ValueError` before anything is sent.
      """

      check_limit(limit)

      return iterate_pages(
         lambda cursor: self.explore_posts(after=cursor), limit=limit, after=after
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

   async def reels(self, *, after: str | None = None) -> Page[Post]:
      """Read one page of the reels feed, the ``/reels/`` tab. One live request.

      ``after`` is an ``end_cursor`` from a previous page, and omitting it asks for the first
      page, which is short: the tab asks for 2 reels, and two measured first pages carried 1 and
      2. A later page asks for 10, and two measured ones carried 4. The page's length is the
      upstream's decision, so a caller keeps asking and stops on ``has_next_page``.

      Each reel is a :class:`~dumpstagram.models.Post` read from the feed's own media shape,
      with what the feed does not send read as W101 records: ``is_seen`` and
      ``is_paid_partnership`` read False and carry no information, the author's
      ``hd_profile_pic_url`` and the post's ``collaborators`` are ``None``, and ``audio`` is
      ``None`` on a reel whose original sound comes without its mute flag, which every one read
      did. A song is read.

      The cursor carries the upstream's cursor and the reels of its page, because the next page
      query names the reels already shown, as a browser names the reels it played. It is opaque;
      anything that did not come from this method raises :class:`ValueError` before anything is
      sent.

      A browser plays each reel as it scrolls, reports every view and asks for advertisements
      to place between them. The engine plays nothing, so no view is reported and no ads pool
      is asked for, and nobody sees the viewer as having watched anything. Both pages carry
      ``/reels/`` as referer. Departures recorded in ``docs/web-request-contract.md``.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_reels_feed_page(
            client._sender,
            client._session,
            after=after,
            user_agent=client._user_agent,
         )
      )

   def iter_reels(self, *, limit: int | None, after: str | None = None) -> AsyncIterator[Post]:
      """Walk the reels feed reel by reel, reading a page with :meth:`reels` each time the one
      before it is used up. Use it with ``async for``, and do not await it.

      ``limit`` is required and counts reels. The walk stops once that many have been yielded,
      without reading a page it would not use, and ``limit=None`` walks until ``has_next_page``
      is false, which on the reels feed may be never. ``after`` starts the walk from a cursor
      :meth:`reels` returned. Each page is one read, paced as any read is, and never read ahead
      of the caller. A negative ``limit`` raises :class:`ValueError` before anything is sent.
      """

      check_limit(limit)

      return iterate_pages(lambda cursor: self.reels(after=cursor), limit=limit, after=after)

   async def audio(self, audio_id: str, *, after: str | None = None) -> AudioPage:
      """Read one page of an audio's page, the track and the reels that use it. One live
      request.

      ``audio_id`` is the track's numeric id, :attr:`Post.audio_id
      <dumpstagram.models.Post.audio_id>` on a reel that uses it or :attr:`MediaAudio.audio_id
      <dumpstagram.models.MediaAudio.audio_id>`, and anything but digits raises
      :class:`ValueError` before anything is sent. ``after`` is the ``end_cursor`` of a page this
      method returned, and omitting it asks for the first page. A song's page carried 12 reels a
      page, and a one-reel original sound's first page its one reel.

      :attr:`~dumpstagram.models.AudioPage.more_available` is the upstream's own flag and the
      only thing that ends a walk. It can say true when nothing follows: the one-reel page said
      true, and its next page carried no reels and said false, so reading to the end of a short
      page spends one read that returns nothing. :attr:`~dumpstagram.models.AudioPage.audio` and
      ``clips_count`` describe the track on a first page and may not on a later one, see
      :class:`~dumpstagram.models.AudioPage`.

      A browser reads the first page after loading the ``/reels/audio/<id>/`` document and each
      later page as the grid is scrolled. This sends the read alone, with that page as its
      referer, a departure recorded in ``docs/web-request-contract.md``. Nothing is played.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_audio_page(
            client._sender,
            client._session,
            audio_id,
            after=after,
            user_agent=client._user_agent,
         )
      )

   async def audio_clips(self, audio_id: str, *, after: str | None = None) -> Page[Post]:
      """Read one page of an audio's reels as a plain page of posts. One live request.

      The same read as :meth:`audio`, returned as a :class:`~dumpstagram.models.Page` of its
      reels, ``has_next_page`` the upstream's ``more_available`` and ``end_cursor`` the same
      cursor :meth:`audio` hands out. It is the page :meth:`iter_audio` walks.
      """

      page = await self.audio(audio_id, after=after)

      return audio_clips_page(page)

   def iter_audio(
      self, audio_id: str, *, limit: int | None, after: str | None = None
   ) -> AsyncIterator[Post]:
      """Walk an audio's reels one by one, reading a page with :meth:`audio_clips` each time the
      one before it is used up. Use it with ``async for``, and do not await it.

      ``limit`` is required and counts reels. The walk stops once that many have been yielded,
      without reading a page it would not use, and ``limit=None`` walks until the upstream's
      ``more_available`` is false, which on a one-reel page came after one empty read. ``after``
      starts the walk from a cursor :meth:`audio` or :meth:`audio_clips` returned. Each page is
      one read, paced as any read is, and never read ahead of the caller. A negative ``limit``
      raises :class:`ValueError` before anything is sent.
      """

      check_limit(limit)

      return iterate_pages(
         lambda cursor: self.audio_clips(audio_id, after=cursor), limit=limit, after=after
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

   def explore(self, *, after: str | None = None) -> ExploreGrid:
      """Read one page of the explore grid. Blocks until it has it.

      The same call as :meth:`AsyncFeeds.explore`, run on the shared loop thread. One live
      request.
      """

      return self._client._loop.run(
         self._client._impl.feeds.explore(after=after),
         operation="SyncClient.feeds.explore",
      )

   def explore_posts(self, *, after: str | None = None) -> Page[Post]:
      """Read one page of the explore grid as a plain page of posts. Blocks until it has it.

      The same call as :meth:`AsyncFeeds.explore_posts`, run on the shared loop thread. One live
      request.
      """

      return self._client._loop.run(
         self._client._impl.feeds.explore_posts(after=after),
         operation="SyncClient.feeds.explore_posts",
      )

   def iter_explore(self, *, limit: int | None, after: str | None = None) -> Iterator[Post]:
      """Walk the explore grid post by post. Blocks while each page is read.

      The same walk as :meth:`AsyncFeeds.iter_explore`, with the same ``limit``, each page read
      on the shared loop thread. Closing the iterator early leaves nothing running, because no
      page is read ahead.
      """

      check_limit(limit)
      client = self._client

      def read_page(cursor: str | None) -> Page[Post]:
         return client._loop.run(
            client._impl.feeds.explore_posts(after=cursor),
            operation="SyncClient.feeds.iter_explore",
         )

      return iterate_pages_blocking(read_page, limit=limit, after=after)

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

   def reels(self, *, after: str | None = None) -> Page[Post]:
      """Read one page of the reels feed. Blocks until it has one.

      The same call as :meth:`AsyncFeeds.reels`, run on the shared loop thread. One live
      request.
      """

      return self._client._loop.run(
         self._client._impl.feeds.reels(after=after),
         operation="SyncClient.feeds.reels",
      )

   def iter_reels(self, *, limit: int | None, after: str | None = None) -> Iterator[Post]:
      """Walk the reels feed reel by reel. Blocks while each page is read.

      The same walk as :meth:`AsyncFeeds.iter_reels`, with the same ``limit``, each page read on
      the shared loop thread. Closing the iterator early leaves nothing running, because no
      page is read ahead.
      """

      check_limit(limit)
      client = self._client

      def read_page(cursor: str | None) -> Page[Post]:
         return client._loop.run(
            client._impl.feeds.reels(after=cursor),
            operation="SyncClient.feeds.iter_reels",
         )

      return iterate_pages_blocking(read_page, limit=limit, after=after)

   def audio(self, audio_id: str, *, after: str | None = None) -> AudioPage:
      """Read one page of an audio's page. Blocks until it has it.

      The same call as :meth:`AsyncFeeds.audio`, run on the shared loop thread. One live
      request.
      """

      return self._client._loop.run(
         self._client._impl.feeds.audio(audio_id, after=after),
         operation="SyncClient.feeds.audio",
      )

   def audio_clips(self, audio_id: str, *, after: str | None = None) -> Page[Post]:
      """Read one page of an audio's reels as a plain page of posts. Blocks until it has it.

      The same call as :meth:`AsyncFeeds.audio_clips`, run on the shared loop thread. One live
      request.
      """

      return self._client._loop.run(
         self._client._impl.feeds.audio_clips(audio_id, after=after),
         operation="SyncClient.feeds.audio_clips",
      )

   def iter_audio(
      self, audio_id: str, *, limit: int | None, after: str | None = None
   ) -> Iterator[Post]:
      """Walk an audio's reels one by one. Blocks while each page is read.

      The same walk as :meth:`AsyncFeeds.iter_audio`, with the same ``limit``, each page read on
      the shared loop thread. Closing the iterator early leaves nothing running, because no page
      is read ahead.
      """

      check_limit(limit)
      client = self._client

      def read_page(cursor: str | None) -> Page[Post]:
         return client._loop.run(
            client._impl.feeds.audio_clips(audio_id, after=cursor),
            operation="SyncClient.feeds.iter_audio",
         )

      return iterate_pages_blocking(read_page, limit=limit, after=after)
