"""``client.profiles``, reading one account's profile, its posts grid, its reels and tagged tabs,
its highlights tray, its followers and the accounts it follows, and the accounts suggested beside
it or to the viewer."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING

from dumpstagram._core.paging import check_limit, iterate_pages, iterate_pages_blocking
from dumpstagram._core.profiles import (
   read_followers_page,
   read_following_page,
   read_highlight_tray,
   read_profile,
   read_profile_by_id,
   read_profile_posts_page,
   read_profile_reels,
   read_suggested_accounts,
   read_suggested_beside_profile,
   read_tagged_posts,
)
from dumpstagram.models import (
   HighlightTray,
   Page,
   Post,
   Profile,
   ProfileReels,
   ProfileSummary,
   SuggestedAccount,
   TaggedPosts,
)

if TYPE_CHECKING:
   from dumpstagram.aio import AsyncClient
   from dumpstagram.client import SyncClient

__all__ = ["AsyncProfiles", "SyncProfiles"]


class AsyncProfiles:
   """Profiles, as ``client.profiles`` on :class:`~dumpstagram.aio.AsyncClient`."""

   _client: AsyncClient

   def __init__(self) -> None:
      raise TypeError("an AsyncProfiles comes from AsyncClient.profiles, it is not built directly")

   @classmethod
   def _of(cls, client: AsyncClient) -> AsyncProfiles:
      namespace = object.__new__(cls)
      namespace._client = client

      return namespace

   async def by_username(self, username: str) -> Profile:
      """Read one account's profile by username.

      Under the default behavior this loads the profile page and sends the page's six queries
      at once, seven requests in one action, as a browser does. It raises
      :class:`~dumpstagram.errors.NotFound` when no account has the username.

      :attr:`~dumpstagram.behavior.Behavior.profile_route` set to
      :attr:`~dumpstagram.behavior.ProfileRoute.QUERIES` spends two requests instead, resolving
      the username through the account's timeline and then reading the profile. That route
      raises :class:`~dumpstagram.errors.NotFound` when the account does not exist, or its
      posts are not visible to this session, or it has none, and cannot say which.

      A caller that already holds the id wants :meth:`by_id`, one request.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_profile(
            client._sender,
            client._session,
            username,
            route=client._behavior.profile_route,
            companions=client._behavior.page_load_companions,
            cookie_sync=client._cookie_sync_if_on(),
            user_agent=client._user_agent,
         )
      )

   async def by_id(self, user_id: str) -> Profile:
      """Read one account's profile by its numeric account id. One live request.

      ``user_id`` is the account's ``pk``, which is what :attr:`~dumpstagram.models.Profile.id`
      carries. It is not the ``fbid`` the same account carries as a message sender, and the
      two are different numbers for the same person.

      On anyone else's profile, ``friendship_status`` carries the viewer's relationship to the
      account, which makes this the read that confirms
      :meth:`~dumpstagram.namespaces.social.AsyncSocial.follow` and
      :meth:`~dumpstagram.namespaces.social.AsyncSocial.unfollow`.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_profile_by_id(
            client._sender,
            client._session,
            user_id,
            user_agent=client._user_agent,
         )
      )

   async def posts(self, username: str, *, after: str | None = None) -> Page[Post]:
      """Read one page of an account's posts grid, twelve posts, newest first. One live request.

      ``username`` is the account's username, which the grid is keyed on; a caller holding a
      :class:`~dumpstagram.models.Profile` passes its ``username``. ``after`` is the
      ``end_cursor`` of a page this method returned, and the page's ``has_next_page`` is the only
      thing that says whether more exist. Pinned posts come first, as the grid shows them.

      Each item is a :class:`~dumpstagram.models.Post`, the home timeline's model, and on a grid
      its ``is_seen`` is always False because the upstream sends null for it there. A post whose
      location failed on the upstream arrives with the rest of the page rather than failing it.

      A browser reads the first page inside the profile page load, beside the document and five
      other queries. This sends the grid's query alone, a departure recorded in
      ``docs/web-request-contract.md``. A later page is sent as a browser sends it when the grid
      is scrolled. An account whose posts the viewer cannot see answers an empty page.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_profile_posts_page(
            client._sender,
            client._session,
            username,
            after=after,
            user_agent=client._user_agent,
         )
      )

   async def highlights(self, user_id: str) -> HighlightTray:
      """Read an account's story highlights tray, its first page. One live request.

      ``user_id`` is the numeric account id, :attr:`Profile.id
      <dumpstagram.models.Profile.id>`, and a username raises :class:`ValueError` before
      anything is sent. Each highlight carries its title and cover; reading the stories in one is
      not part of this read, and nothing is marked seen.

      Only the first page is read, because the query that reads further has never answered: no
      tray read so far had a second page. ``has_more`` on the result is the upstream's own flag
      and says when the tuple is not the whole tray.

      A browser reads the tray inside the profile page load. This sends it alone, with the site
      root as its referer rather than the profile page, departures recorded in
      ``docs/web-request-contract.md``.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_highlight_tray(
            client._sender,
            client._session,
            user_id,
            user_agent=client._user_agent,
         )
      )

   async def suggested(self, user_id: str) -> tuple[ProfileSummary, ...]:
      """Read the accounts the website suggests beside an account's profile. One live request.

      ``user_id`` is the numeric account id, and a username raises :class:`ValueError` before
      anything is sent. The accounts come in the upstream's order, each with the viewer's
      relationship to it, and the answer carries no cursor, so the tuple is the whole list.

      This is the query a browser sends when the suggestions beside a profile are opened. It is
      sent with the site root as its referer rather than the profile page, a departure recorded
      in ``docs/web-request-contract.md``.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_suggested_beside_profile(
            client._sender,
            client._session,
            user_id,
            user_agent=client._user_agent,
         )
      )

   async def suggested_for_you(self) -> tuple[SuggestedAccount, ...]:
      """Read the suggested accounts list the website shows the viewer. One live request.

      Each :class:`~dumpstagram.models.SuggestedAccount` is an account and the line the website
      shows under it. The list is asked for five at a time as the recorded browse asked, and the
      answer carries no cursor, so the tuple is what one read returns.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_suggested_accounts(
            client._sender,
            client._session,
            user_agent=client._user_agent,
         )
      )

   async def followers(self, user_id: str, *, after: str | None = None) -> Page[ProfileSummary]:
      """Read one page of an account's followers, in the upstream's order. Two live requests.

      ``user_id`` is the numeric account id, :attr:`Profile.id
      <dumpstagram.models.Profile.id>`, and a username raises :class:`ValueError` before
      anything is sent. ``after`` is the ``end_cursor`` of a page this method returned, and the
      page's ``has_next_page`` is the upstream's own ``has_more``, the only thing that says
      whether more exist. The upstream decides a page's length: twelve are asked for, and a
      second page of seven still said more existed.

      Each account's ``friendship_status`` is the viewer's relationship to it, read by the
      request a browser's follow list sends beside each page, inside the same action.
      :attr:`~dumpstagram.behavior.Behavior.follow_list_statuses` set to False leaves that
      request out, one live request a page, and every ``friendship_status`` is then ``None``.

      A browser opens the list from the profile page, so its referer is that page. This sends
      the site root, because the method has an id and no username, a departure recorded in
      ``docs/web-request-contract.md``. Only the viewer's own followers have been read, so what
      the upstream answers for a private account the viewer does not follow is not observed.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_followers_page(
            client._sender,
            client._session,
            user_id,
            after=after,
            with_statuses=client._behavior.follow_list_statuses,
            user_agent=client._user_agent,
         )
      )

   async def following(self, user_id: str, *, after: str | None = None) -> Page[ProfileSummary]:
      """Read one page of the accounts an account follows, in the upstream's order. Two live
      requests.

      ``user_id`` is the numeric account id, :attr:`Profile.id
      <dumpstagram.models.Profile.id>`, and a username raises :class:`ValueError` before
      anything is sent. ``after`` is the ``end_cursor`` of a page this method returned, and the
      page's ``has_next_page`` is the upstream's own ``has_more``, the only thing that says
      whether more exist. Twelve are asked for, and the upstream decides a page's length. The
      list is ranked by the upstream, and two first pages read seconds apart held 11 of the same
      12 accounts, so a walk may meet an account twice or miss one.

      Each account's ``friendship_status`` is the viewer's relationship to it, read by the
      request a browser's list sends beside each page, inside the same action, as
      :meth:`followers` does. :attr:`~dumpstagram.behavior.Behavior.follow_list_statuses` set to
      False leaves that request out for both lists, one live request a page, and every
      ``friendship_status`` is then ``None``.

      A browser opens the list from the profile page, so its referer is that page. This sends
      the site root, because the method has an id and no username, a departure recorded in
      ``docs/web-request-contract.md``. Only the viewer's own list has been read.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_following_page(
            client._sender,
            client._session,
            user_id,
            after=after,
            with_statuses=client._behavior.follow_list_statuses,
            user_agent=client._user_agent,
         )
      )

   async def reels(self, user_id: str) -> ProfileReels:
      """Read an account's reels tab, its first page, newest first. One live request.

      ``user_id`` is the numeric account id, :attr:`Profile.id
      <dumpstagram.models.Profile.id>`, and a username raises :class:`ValueError` before
      anything is sent. Each item is a :class:`~dumpstagram.models.ReelThumbnail`, the cover and
      counts the tab shows; :meth:`~dumpstagram.namespaces.media.AsyncMedia.by_code` reads one
      whole.

      Only the first page is read, because no query that reads the tab further has been
      observed. ``has_more`` on the result is the upstream's own flag and says when the tuple is
      not the whole tab.

      A browser reads the tab when it is clicked on the profile page, beside the suggested
      accounts query. This sends the tab's query alone, with the site root as its referer rather
      than the profile page, departures recorded in ``docs/web-request-contract.md``.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_profile_reels(
            client._sender,
            client._session,
            user_id,
            user_agent=client._user_agent,
         )
      )

   async def tagged(self, user_id: str) -> TaggedPosts:
      """Read an account's tagged tab, its first page: the posts other accounts tagged it in. One
      live request.

      ``user_id`` is the numeric account id, and a username raises :class:`ValueError` before
      anything is sent. Each item is a :class:`~dumpstagram.models.PostThumbnail`, whose author
      is the account that posted it, not the one tagged.

      Only the first page is read, because no query that reads the tab further has been
      observed. ``has_more`` on the result is the upstream's own flag and says when the tuple is
      not the whole tab.

      A browser reads the tab when it is clicked on the profile page, beside the suggested
      accounts query. This sends the tab's query alone, with the site root as its referer rather
      than the profile page, departures recorded in ``docs/web-request-contract.md``.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_tagged_posts(
            client._sender,
            client._session,
            user_id,
            user_agent=client._user_agent,
         )
      )

   def iter_posts(
      self, username: str, *, limit: int | None, after: str | None = None
   ) -> AsyncIterator[Post]:
      """Walk an account's posts grid post by post, newest first, reading a page with
      :meth:`posts` each time the one before it is used up. Use it with ``async for``, and do not
      await it.

      ``limit`` is required and counts posts. The walk stops once that many have been yielded,
      without reading a page it would not use, and ``limit=None`` walks to the oldest post, one
      read per page. ``after`` starts the walk from a cursor :meth:`posts` handed out.

      Each page is one read with everything :meth:`posts` sends for it, paced as any read is,
      and never read ahead of the caller. A page that says more exist with no cursor raises
      :class:`~dumpstagram.errors.SchemaChanged`, and a negative ``limit`` raises
      :class:`ValueError` before anything is sent.
      """

      check_limit(limit)

      return iterate_pages(
         lambda cursor: self.posts(username, after=cursor), limit=limit, after=after
      )

   def iter_followers(
      self, user_id: str, *, limit: int | None, after: str | None = None
   ) -> AsyncIterator[ProfileSummary]:
      """Walk an account's followers one account at a time, reading a page with
      :meth:`followers` each time the one before it is used up. Use it with ``async for``, and
      do not await it.

      ``limit`` is required and counts accounts. The walk stops once that many have been
      yielded, without reading a page it would not use, and ``limit=None`` walks until a page
      says no more exist. ``after`` starts the walk from a cursor :meth:`followers` handed out.

      Each page is one read with everything :meth:`followers` sends for it, paced as any read
      is, and never read ahead of the caller. A page that says more exist with no cursor raises
      :class:`~dumpstagram.errors.SchemaChanged`, and a negative ``limit`` raises
      :class:`ValueError` before anything is sent.
      """

      check_limit(limit)

      return iterate_pages(
         lambda next_max_id: self.followers(user_id, after=next_max_id), limit=limit, after=after
      )

   def iter_following(
      self, user_id: str, *, limit: int | None, after: str | None = None
   ) -> AsyncIterator[ProfileSummary]:
      """Walk the accounts an account follows one at a time, reading a page with
      :meth:`following` each time the one before it is used up. Use it with ``async for``, and
      do not await it.

      ``limit`` is required and counts accounts. The walk stops once that many have been
      yielded, without reading a page it would not use, and ``limit=None`` walks until a page
      says no more exist. ``after`` starts the walk from a cursor :meth:`following` handed out.

      Each page is one read with everything :meth:`following` sends for it, paced as any read
      is, and never read ahead of the caller. A page that says more exist with no cursor raises
      :class:`~dumpstagram.errors.SchemaChanged`, and a negative ``limit`` raises
      :class:`ValueError` before anything is sent.
      """

      check_limit(limit)

      return iterate_pages(
         lambda offset: self.following(user_id, after=offset), limit=limit, after=after
      )


class SyncProfiles:
   """Profiles, as ``client.profiles`` on :class:`~dumpstagram.client.SyncClient`. Each method
   blocks on the shared loop thread and answers as its :class:`AsyncProfiles` twin does."""

   _client: SyncClient

   def __init__(self) -> None:
      raise TypeError("a SyncProfiles comes from SyncClient.profiles, it is not built directly")

   @classmethod
   def _of(cls, client: SyncClient) -> SyncProfiles:
      namespace = object.__new__(cls)
      namespace._client = client

      return namespace

   def by_username(self, username: str) -> Profile:
      """Read one account's profile by username. Blocks until it has one.

      The same call as :meth:`AsyncProfiles.by_username`, with the same arguments and the same
      result, run on the shared loop thread. Seven live requests in one action under the
      default behavior, two under :attr:`~dumpstagram.behavior.ProfileRoute.QUERIES`.
      """

      return self._client._loop.run(
         self._client._impl.profiles.by_username(username),
         operation="SyncClient.profiles.by_username",
      )

   def by_id(self, user_id: str) -> Profile:
      """Read one account's profile by its numeric account id. Blocks until it has one.

      The same call as :meth:`AsyncProfiles.by_id`, run on the shared loop thread. One live
      request.
      """

      return self._client._loop.run(
         self._client._impl.profiles.by_id(user_id),
         operation="SyncClient.profiles.by_id",
      )

   def posts(self, username: str, *, after: str | None = None) -> Page[Post]:
      """Read one page of an account's posts grid. Blocks until it has one.

      The same call as :meth:`AsyncProfiles.posts`, with the same arguments and the same result,
      run on the shared loop thread. One live request.
      """

      return self._client._loop.run(
         self._client._impl.profiles.posts(username, after=after),
         operation="SyncClient.profiles.posts",
      )

   def highlights(self, user_id: str) -> HighlightTray:
      """Read an account's story highlights tray, its first page. Blocks until it has it.

      The same call as :meth:`AsyncProfiles.highlights`, run on the shared loop thread. One live
      request.
      """

      return self._client._loop.run(
         self._client._impl.profiles.highlights(user_id),
         operation="SyncClient.profiles.highlights",
      )

   def suggested(self, user_id: str) -> tuple[ProfileSummary, ...]:
      """Read the accounts suggested beside an account's profile. Blocks until it has them.

      The same call as :meth:`AsyncProfiles.suggested`, run on the shared loop thread. One live
      request.
      """

      return self._client._loop.run(
         self._client._impl.profiles.suggested(user_id),
         operation="SyncClient.profiles.suggested",
      )

   def suggested_for_you(self) -> tuple[SuggestedAccount, ...]:
      """Read the suggested accounts list. Blocks until it has it.

      The same call as :meth:`AsyncProfiles.suggested_for_you`, run on the shared loop thread.
      One live request.
      """

      return self._client._loop.run(
         self._client._impl.profiles.suggested_for_you(),
         operation="SyncClient.profiles.suggested_for_you",
      )

   def followers(self, user_id: str, *, after: str | None = None) -> Page[ProfileSummary]:
      """Read one page of an account's followers. Blocks until it has one.

      The same call as :meth:`AsyncProfiles.followers`, with the same arguments and the same
      result, run on the shared loop thread. Two live requests, one when
      :attr:`~dumpstagram.behavior.Behavior.follow_list_statuses` is off.
      """

      return self._client._loop.run(
         self._client._impl.profiles.followers(user_id, after=after),
         operation="SyncClient.profiles.followers",
      )

   def following(self, user_id: str, *, after: str | None = None) -> Page[ProfileSummary]:
      """Read one page of the accounts an account follows. Blocks until it has one.

      The same call as :meth:`AsyncProfiles.following`, with the same arguments and the same
      result, run on the shared loop thread. Two live requests, one when
      :attr:`~dumpstagram.behavior.Behavior.follow_list_statuses` is off.
      """

      return self._client._loop.run(
         self._client._impl.profiles.following(user_id, after=after),
         operation="SyncClient.profiles.following",
      )

   def reels(self, user_id: str) -> ProfileReels:
      """Read an account's reels tab, its first page. Blocks until it has it.

      The same call as :meth:`AsyncProfiles.reels`, run on the shared loop thread. One live
      request.
      """

      return self._client._loop.run(
         self._client._impl.profiles.reels(user_id),
         operation="SyncClient.profiles.reels",
      )

   def tagged(self, user_id: str) -> TaggedPosts:
      """Read an account's tagged tab, its first page. Blocks until it has it.

      The same call as :meth:`AsyncProfiles.tagged`, run on the shared loop thread. One live
      request.
      """

      return self._client._loop.run(
         self._client._impl.profiles.tagged(user_id),
         operation="SyncClient.profiles.tagged",
      )

   def iter_posts(
      self, username: str, *, limit: int | None, after: str | None = None
   ) -> Iterator[Post]:
      """Walk an account's posts grid post by post. Blocks while each page is read.

      The same walk as :meth:`AsyncProfiles.iter_posts`, with the same ``limit``, each page read
      on the shared loop thread. Exceptions cross back as themselves, with a note naming this
      method. Closing the iterator early leaves nothing running, because no page is read ahead.
      """

      check_limit(limit)
      client = self._client

      def read_page(cursor: str | None) -> Page[Post]:
         return client._loop.run(
            client._impl.profiles.posts(username, after=cursor),
            operation="SyncClient.profiles.iter_posts",
         )

      return iterate_pages_blocking(read_page, limit=limit, after=after)

   def iter_followers(
      self, user_id: str, *, limit: int | None, after: str | None = None
   ) -> Iterator[ProfileSummary]:
      """Walk an account's followers one account at a time. Blocks while each page is read.

      The same walk as :meth:`AsyncProfiles.iter_followers`, with the same ``limit``, each page
      read on the shared loop thread. Exceptions cross back as themselves, with a note naming
      this method. Closing the iterator early leaves nothing running, because no page is read
      ahead.
      """

      check_limit(limit)
      client = self._client

      def read_followers_of(next_max_id: str | None) -> Page[ProfileSummary]:
         return client._loop.run(
            client._impl.profiles.followers(user_id, after=next_max_id),
            operation="SyncClient.profiles.iter_followers",
         )

      return iterate_pages_blocking(read_followers_of, limit=limit, after=after)

   def iter_following(
      self, user_id: str, *, limit: int | None, after: str | None = None
   ) -> Iterator[ProfileSummary]:
      """Walk the accounts an account follows one at a time. Blocks while each page is read.

      The same walk as :meth:`AsyncProfiles.iter_following`, with the same ``limit``, each page
      read on the shared loop thread. Exceptions cross back as themselves, with a note naming
      this method. Closing the iterator early leaves nothing running, because no page is read
      ahead.
      """

      check_limit(limit)
      client = self._client

      def read_following_of(offset: str | None) -> Page[ProfileSummary]:
         return client._loop.run(
            client._impl.profiles.following(user_id, after=offset),
            operation="SyncClient.profiles.iter_following",
         )

      return iterate_pages_blocking(read_following_of, limit=limit, after=after)
