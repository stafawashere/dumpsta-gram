"""``client.media``, one post and what the viewer does to it: likes, comments, downloads, and
publishing and deleting the viewer's own."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterator, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from dumpstagram._core.comments import read_comment_page
from dumpstagram._core.downloads import download_rendition
from dumpstagram._core.paging import check_limit, iterate_pages, iterate_pages_blocking
from dumpstagram._core.posts import read_post
from dumpstagram._core.writes.comments import create_comment, delete_comment
from dumpstagram._core.writes.likes import like_post, unlike_post
from dumpstagram._core.writes.posts import delete_post, publish_carousel, publish_photo
from dumpstagram.models import (
   Comment,
   MediaImage,
   Page,
   PostDetail,
   PublishedPost,
   VideoRendition,
)

if TYPE_CHECKING:
   from dumpstagram.aio import AsyncClient
   from dumpstagram.client import SyncClient

__all__ = ["AsyncMedia", "SyncMedia"]


class AsyncMedia:
   """Posts, their likes, their comments and their downloads, as ``client.media`` on
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

   async def download(
      self,
      rendition: MediaImage | VideoRendition,
      path: str | os.PathLike[str],
      *,
      overwrite: bool = False,
   ) -> Path:
      """Fetch one rendition from Instagram's CDN into the file at ``path``, and return it.

      ``rendition`` is one entry of a post's ``images`` or ``videos``, or of a carousel
      slide's. It is one fetch of a static file, not an Instagram API request, so it takes no
      turn from this account's pacer, and several downloads may run at once, four connections at
      most per client. No cookie is sent, because the CDN asked for none on any fetch measured.

      The body is written to a temporary file beside ``path`` as it arrives and renamed onto
      ``path`` only when it is complete, so a failed download leaves nothing behind. A file
      already at ``path`` raises :class:`FileExistsError` before anything is sent, unless
      ``overwrite`` is true. The directory must exist.

      A body shorter or longer than the length the CDN declared raises
      :class:`~dumpstagram.errors.TransportFailure`. Rendition URLs are signed and expire, and
      a refused one raises :class:`~dumpstagram.errors.NotFound`, after which reading the post
      again gives a fresh URL. A URL outside the CDN's hosts is refused before it is sent.
      """

      client = self._client
      client._refuse_when_closed()

      return await download_rendition(
         client._cdn,
         rendition.url,
         path,
         overwrite=overwrite,
         user_agent=client._user_agent,
      )

   async def publish_photo(
      self, image: bytes | str | os.PathLike[str], *, caption: str = ""
   ) -> PublishedPost:
      """Publish ``image`` as a post on the viewer's account with ``caption``, and return it.

      ``image`` is a JPEG, as bytes or as the path of a file. Anything else raises
      :class:`ValueError` before anything is sent, because only a JPEG upload has been
      observed. Converting is the caller's to do. The width and height are read from the file.

      Two writes, each sent once and never retried: the upload to Instagram's upload host,
      then the publish that names it. Each waits out the behavior's write spacing and counts
      against its write budget, so under the default behavior a publish takes about half a
      minute. Nothing is sent about a location, a tag, a collaborator or sharing elsewhere.

      The post is visible to everyone who can see the account as soon as the publish applies.
      Read it back with :meth:`by_code` and :attr:`PublishedPost.code
      <dumpstagram.models.PublishedPost.code>` to confirm it is up.

      When the upload applies and the publish fails, the upload is orphaned: stored, published
      nowhere, and not retried or reused. The error raised is the one the failing write raised,
      with a note naming the half that failed and the orphaned upload id. After
      :class:`~dumpstagram.errors.OutcomeUnknown` on the publish the post may be up, so read the
      viewer's profile and its ``media_count`` before publishing again.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         publish_photo(
            client._sender,
            client._uploads,
            client._session,
            image,
            caption=caption,
            user_agent=client._user_agent,
         )
      )

   async def publish_carousel(
      self, images: Sequence[bytes | str | os.PathLike[str]], *, caption: str = ""
   ) -> PublishedPost:
      """Publish ``images`` as one carousel post, in that order, and return it.

      Each image is what :meth:`publish_photo` takes, and every one is read and checked before
      the first upload leaves. Fewer than two raises :class:`ValueError`, since one image is a
      photo. The upper limit is the upstream's and has not been observed.

      One write per image and one publish, each sent once and never retried, each spaced and
      budgeted as :meth:`publish_photo`'s are. When an upload or the publish fails, the uploads
      that applied before it are orphaned, and the error carries a note naming which write
      failed and which upload ids applied. Confirm and reconcile as :meth:`publish_photo` says.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         publish_carousel(
            client._sender,
            client._uploads,
            client._session,
            images,
            caption=caption,
            user_agent=client._user_agent,
         )
      )

   async def delete_post(self, post_pk: str, code: str) -> None:
      """Delete the viewer's own post whose media ``pk`` is ``post_pk`` and shortcode ``code``.

      One write, sent once, never retried. ``post_pk`` is :attr:`PublishedPost.pk
      <dumpstagram.models.PublishedPost.pk>` or :attr:`PostDetail.pk
      <dumpstagram.models.PostDetail.pk>`, and the ``<pk>_<owner id>`` form raises
      :class:`ValueError` before anything is sent. ``code`` is the post's shortcode, which the
      delete names the post's page by, as the page the browser deletes from.

      Only the viewer's own post can be deleted, because the request names the post with the
      viewer's own id. Raises :class:`~dumpstagram.errors.UpstreamRejected` with code
      ``post_not_deleted`` when the answer says nothing was deleted.

      To confirm, read the post with :meth:`by_code`. A deleted post's read was refused with
      :class:`~dumpstagram.errors.UpstreamRejected` on all five deletes read back, and the
      profile's ``media_count`` fell back by one. The same two reads reconcile
      :class:`~dumpstagram.errors.OutcomeUnknown`.
      """

      client = self._client
      client._refuse_when_closed()

      await client._watch_for_checkpoint(
         delete_post(
            client._sender,
            client._session,
            post_pk,
            code,
            user_agent=client._user_agent,
         )
      )


class SyncMedia:
   """Posts, their likes, their comments and their downloads, as ``client.media`` on
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

   def download(
      self,
      rendition: MediaImage | VideoRendition,
      path: str | os.PathLike[str],
      *,
      overwrite: bool = False,
   ) -> Path:
      """Fetch one rendition from the CDN into ``path``. Blocks until the file is complete.

      The same call as :meth:`AsyncMedia.download`, run on the shared loop thread. One CDN
      fetch and no Instagram API request.
      """

      return self._client._loop.run(
         self._client._impl.media.download(rendition, path, overwrite=overwrite),
         operation="SyncClient.media.download",
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

   def publish_photo(
      self, image: bytes | str | os.PathLike[str], *, caption: str = ""
   ) -> PublishedPost:
      """Publish ``image`` as a post. Blocks until the publish is answered.

      The same call as :meth:`AsyncMedia.publish_photo`, run on the shared loop thread. Two
      writes, each sent once, never retried, and an orphaned upload named in the error's note
      when the publish fails.
      """

      return self._client._loop.run(
         self._client._impl.media.publish_photo(image, caption=caption),
         operation="SyncClient.media.publish_photo",
      )

   def publish_carousel(
      self, images: Sequence[bytes | str | os.PathLike[str]], *, caption: str = ""
   ) -> PublishedPost:
      """Publish ``images`` as one carousel post. Blocks until the publish is answered.

      The same call as :meth:`AsyncMedia.publish_carousel`, run on the shared loop thread. One
      write per image and one publish, each sent once, never retried.
      """

      return self._client._loop.run(
         self._client._impl.media.publish_carousel(images, caption=caption),
         operation="SyncClient.media.publish_carousel",
      )

   def delete_post(self, post_pk: str, code: str) -> None:
      """Delete the viewer's own post. Blocks until the write is answered.

      The same call as :meth:`AsyncMedia.delete_post`, run on the shared loop thread. One
      write, sent once, never retried.
      """

      return self._client._loop.run(
         self._client._impl.media.delete_post(post_pk, code),
         operation="SyncClient.media.delete_post",
      )
