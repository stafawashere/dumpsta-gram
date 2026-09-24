"""``client.media``, one post and what the viewer does to it: likes and comments."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING

from dumpstagram._core.comments import read_comment_page
from dumpstagram._core.paging import check_limit, iterate_pages, iterate_pages_blocking
from dumpstagram._core.posts import read_post
from dumpstagram._core.writes.comments import create_comment, delete_comment
from dumpstagram._core.writes.likes import like_post, unlike_post
from dumpstagram.models import Comment, Page, PostDetail

if TYPE_CHECKING:
   from dumpstagram.aio import AsyncClient
   from dumpstagram.client import SyncClient

__all__ = ["AsyncMedia", "SyncMedia"]


class AsyncMedia:
   """Posts, their likes and their comments, as ``client.media`` on
   :class:`~dumpstagram.aio.AsyncClient`."""

   _client: AsyncClient

   def __init__(self) -> None:
      raise TypeError("an AsyncMedia comes from AsyncClient.media, it is not built directly")

   @classmethod
   def _of(cls, client: AsyncClient) -> AsyncMedia:
      namespace = object.__new__(cls)
      namespace._client = client

      return namespace

   async def by_code(self, code: str) -> PostDetail:
      """Read one post by the shortcode in its web address. One live request.

      The answer carries both of the post's identifiers, and :attr:`PostDetail.pk
      <dumpstagram.models.PostDetail.pk>` is the one :meth:`like` and :meth:`unlike` take. It
      carries ``has_liked`` and ``like_count`` for this viewer, which is how a like is
      confirmed, and how one whose outcome was unknown is reconciled.

      A browser reads a post inside a post page load. This sends the post query alone under
      every behavior, a departure recorded in ``docs/web-request-contract.md``.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_post(
            client._sender,
            client._session,
            code,
            user_agent=client._user_agent,
         )
      )

   async def like(self, post_pk: str) -> None:
      """Like the post whose media ``pk`` is ``post_pk``. One write, sent once, never retried.

      ``post_pk`` is :attr:`Post.pk <dumpstagram.models.Post.pk>` or
      :attr:`PostDetail.pk <dumpstagram.models.PostDetail.pk>`. The ``<pk>_<author id>`` form in
      their ``id`` raises :class:`ValueError` before anything is sent.

      Liking a post that is already liked succeeds and changes nothing, observed once. The write
      waits out the behavior's write spacing, counts against its write budget, and raises
      :class:`~dumpstagram.errors.OutcomeUnknown` if the connection fails while it is in flight.
      To reconcile that, read the post with :meth:`by_code` and look at ``has_liked``.

      The request a browser sends around a like has not been recorded, so this sends the like
      alone, a departure recorded in ``docs/web-request-contract.md``.
      """

      client = self._client
      client._refuse_when_closed()

      await client._watch_for_checkpoint(
         like_post(
            client._sender,
            client._session,
            post_pk,
            user_agent=client._user_agent,
         )
      )

   async def unlike(self, post_pk: str) -> None:
      """Unlike the post whose media ``pk`` is ``post_pk``. One write, sent once, never retried.

      The same identifier, rules and reconciliation as :meth:`like`. Unliking a post that is
      not liked succeeds and changes nothing, observed once.
      """

      client = self._client
      client._refuse_when_closed()

      await client._watch_for_checkpoint(
         unlike_post(
            client._sender,
            client._session,
            post_pk,
            user_agent=client._user_agent,
         )
      )

   async def comments(self, post_pk: str, *, after: str | None = None) -> Page[Comment]:
      """Read one page of the comments on the post whose media ``pk`` is ``post_pk``.

      One live request. ``after`` is the previous page's ``end_cursor``, and ``has_next_page``
      is the only sign that more exist: a short or empty page is not the end. This is the read
      that confirms :meth:`comment` and :meth:`delete_comment`, and the one that reconciles
      either after :class:`~dumpstagram.errors.OutcomeUnknown`.

      ``post_pk`` is :attr:`Post.pk <dumpstagram.models.Post.pk>` or
      :attr:`PostDetail.pk <dumpstagram.models.PostDetail.pk>`, and the ``<pk>_<author id>``
      form raises :class:`ValueError` before anything is sent.

      A browser reads comments inside a post page load, its first page with a query of its
      own. This sends the pagination query alone for every page, a departure recorded in
      ``docs/web-request-contract.md``.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_comment_page(
            client._sender,
            client._session,
            post_pk,
            after=after,
            user_agent=client._user_agent,
         )
      )

   def iter_comments(
      self, post_pk: str, *, limit: int | None, after: str | None = None
   ) -> AsyncIterator[Comment]:
      """Walk the comments on one post comment by comment, reading a page with
      :meth:`comments` each time the one before it is used up. Use it with ``async for``, and
      do not await it.

      ``limit`` is required and counts comments. The walk stops once that many have been
      yielded, without reading a page it would not use, and ``limit=None`` walks until
      ``has_next_page`` is false, one read per page. ``after`` starts the walk from a cursor
      instead of the first page.

      Each page is one read, paced as any read is, and never read ahead of the caller. An
      empty page that says more exist is followed, and a page that says more exist with no
      cursor raises :class:`~dumpstagram.errors.SchemaChanged`. A negative ``limit`` raises
      :class:`ValueError` before anything is sent.
      """

      check_limit(limit)

      return iterate_pages(
         lambda cursor: self.comments(post_pk, after=cursor), limit=limit, after=after
      )

   async def comment(self, post_pk: str, text: str) -> Comment:
      """Comment ``text`` on the post whose media ``pk`` is ``post_pk``. One write, sent once.

      Returns the created comment, whose ``id`` is what :meth:`delete_comment` takes. Its
      ``like_count``, ``reply_count``, ``parent_comment_id`` and ``has_liked`` are None, because
      the answer to a new comment does not carry them. Empty text raises :class:`ValueError`.

      A comment appends, so it is never sent again, by this library or by any retry path. If
      the connection fails while it is in flight this raises
      :class:`~dumpstagram.errors.OutcomeUnknown`, and sending again may post it twice where
      everyone who can see the post sees it. To reconcile, read the post's comments with
      :meth:`comments` and look for the viewer's own comment with this text created after the
      attempt began, and only then decide.

      The write waits out the behavior's write spacing and counts against its write budget.
      The request a browser sends around a comment has not been recorded, so this sends the
      comment alone, a departure recorded in ``docs/web-request-contract.md``.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         create_comment(
            client._sender,
            client._session,
            post_pk,
            text,
            user_agent=client._user_agent,
         )
      )

   async def delete_comment(self, post_pk: str, comment_id: str) -> None:
      """Delete the comment ``comment_id`` on the post whose media ``pk`` is ``post_pk``.

      One write, sent once, never retried. Both identifiers are digits only, and the upstream
      takes them together. ``comment_id`` is :attr:`Comment.id
      <dumpstagram.models.Comment.id>`.

      Raises :class:`~dumpstagram.errors.UpstreamRejected` with code ``comment_not_deleted``
      when the upstream answers that nothing was deleted, which is how it answered a delete
      naming no existing comment. After :class:`~dumpstagram.errors.OutcomeUnknown`, read the
      comments with :meth:`comments`: a comment that is no longer listed is gone.
      """

      client = self._client
      client._refuse_when_closed()

      await client._watch_for_checkpoint(
         delete_comment(
            client._sender,
            client._session,
            post_pk,
            comment_id,
            user_agent=client._user_agent,
         )
      )


class SyncMedia:
   """Posts, their likes and their comments, as ``client.media`` on
   :class:`~dumpstagram.client.SyncClient`. Each method blocks on the shared loop thread and
   answers as its :class:`AsyncMedia` twin does."""

   _client: SyncClient

   def __init__(self) -> None:
      raise TypeError("a SyncMedia comes from SyncClient.media, it is not built directly")

   @classmethod
   def _of(cls, client: SyncClient) -> SyncMedia:
      namespace = object.__new__(cls)
      namespace._client = client

      return namespace

   def by_code(self, code: str) -> PostDetail:
      """Read one post by its shortcode. Blocks until it has it.

      The same call as :meth:`AsyncMedia.by_code`, run on the shared loop thread. One live
      request.
      """

      return self._client._loop.run(
         self._client._impl.media.by_code(code),
         operation="SyncClient.media.by_code",
      )

   def like(self, post_pk: str) -> None:
      """Like the post whose media ``pk`` is ``post_pk``. Blocks until the write is answered.

      The same call as :meth:`AsyncMedia.like`, run on the shared loop thread. One write, sent
      once, never retried.
      """

      return self._client._loop.run(
         self._client._impl.media.like(post_pk),
         operation="SyncClient.media.like",
      )

   def unlike(self, post_pk: str) -> None:
      """Unlike the post whose media ``pk`` is ``post_pk``. Blocks until the write is answered.

      The same call as :meth:`AsyncMedia.unlike`, run on the shared loop thread. One write,
      sent once, never retried.
      """

      return self._client._loop.run(
         self._client._impl.media.unlike(post_pk),
         operation="SyncClient.media.unlike",
      )

   def comments(self, post_pk: str, *, after: str | None = None) -> Page[Comment]:
      """Read one page of a post's comments. Blocks until it has it.

      The same call as :meth:`AsyncMedia.comments`, run on the shared loop thread. One live
      request.
      """

      return self._client._loop.run(
         self._client._impl.media.comments(post_pk, after=after),
         operation="SyncClient.media.comments",
      )

   def iter_comments(
      self, post_pk: str, *, limit: int | None, after: str | None = None
   ) -> Iterator[Comment]:
      """Walk the comments on one post comment by comment. Blocks while each page is read.

      The same walk as :meth:`AsyncMedia.iter_comments`, with the same ``limit``, each page
      read on the shared loop thread. Exceptions cross back as themselves, with a note naming
      this method. Closing the iterator early leaves nothing running, because no page is read
      ahead.
      """

      check_limit(limit)
      client = self._client

      def read_page(cursor: str | None) -> Page[Comment]:
         return client._loop.run(
            client._impl.media.comments(post_pk, after=cursor),
            operation="SyncClient.media.iter_comments",
         )

      return iterate_pages_blocking(read_page, limit=limit, after=after)

   def comment(self, post_pk: str, text: str) -> Comment:
      """Comment on a post. Blocks until the write is answered.

      The same call as :meth:`AsyncMedia.comment`, run on the shared loop thread. One write,
      sent once, never retried. After :class:`~dumpstagram.errors.OutcomeUnknown`, read
      :meth:`comments` before sending again, because a second send is a second comment.
      """

      return self._client._loop.run(
         self._client._impl.media.comment(post_pk, text),
         operation="SyncClient.media.comment",
      )

   def delete_comment(self, post_pk: str, comment_id: str) -> None:
      """Delete one comment on a post. Blocks until the write is answered.

      The same call as :meth:`AsyncMedia.delete_comment`, run on the shared loop thread. One
      write, sent once, never retried.
      """

      return self._client._loop.run(
         self._client._impl.media.delete_comment(post_pk, comment_id),
         operation="SyncClient.media.delete_comment",
      )
