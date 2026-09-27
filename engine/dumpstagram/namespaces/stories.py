"""``client.stories``, reading the stories tray, one account's live stories and one highlight.

Reading a story through the engine does not mark it seen. A browser marks every item it shows
with a separate mutation, and the engine sends none until that mutation is verified on the
owner's own story (W68).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dumpstagram._core.stories import read_highlight, read_stories_tray, read_story_reel
from dumpstagram.models import StoryReel, TrayReel

if TYPE_CHECKING:
   from dumpstagram.aio import AsyncClient
   from dumpstagram.client import SyncClient

__all__ = ["AsyncStories", "SyncStories"]


class AsyncStories:
   """Stories, as ``client.stories`` on :class:`~dumpstagram.aio.AsyncClient`."""

   _client: AsyncClient

   def __init__(self) -> None:
      raise TypeError("an AsyncStories comes from AsyncClient.stories, it is not built directly")

   @classmethod
   def _of(cls, client: AsyncClient) -> AsyncStories:
      namespace = object.__new__(cls)
      namespace._client = client

      return namespace

   async def tray(self) -> tuple[TrayReel, ...]:
      """Read the stories tray at the top of the home page. One live request.

      One :class:`~dumpstagram.models.TrayReel` per account with live stories, in the tray's
      order, which says whose stories there are and how far the viewer has seen them, and
      carries no items. :meth:`reel` with ``owner.id`` reads an account's items. The tray has no
      cursor, so the tuple is the tray as sent. Nothing is marked seen.

      A browser reads the tray inside a page load. This sends it alone, with the site root as
      its referer, a departure recorded in ``docs/web-request-contract.md``.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_stories_tray(
            client._sender,
            client._session,
            user_agent=client._user_agent,
         )
      )

   async def reel(self, user_id: str) -> StoryReel | None:
      """Read one account's live stories, every item in its reel. One live request.

      ``user_id`` is the numeric account id, :attr:`Profile.id
      <dumpstagram.models.Profile.id>` or a tray row's ``owner.id``, and a username raises
      :class:`ValueError` before anything is sent. Returns ``None`` when the account has no live
      story, which is how the upstream answered the owner's own reel with none up.

      This does not mark any item seen, so the owner does not see the viewer in the story's seen
      list. A browser would: it marks each item it shows with a separate mutation, and the
      engine sends none until that mutation is verified on the owner's own story, a departure
      from browser parity recorded in ``docs/web-request-contract.md``. No live story has been
      read yet, only highlights, whose items are story items, so the item model is ASSUMED to
      fit a live reel too.

      A browser reads a reel when the story viewer opens. This sends it alone, with the site
      root as its referer.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_story_reel(
            client._sender,
            client._session,
            user_id,
            user_agent=client._user_agent,
         )
      )

   async def highlight(self, highlight_id: str) -> StoryReel:
      """Read one highlight, every item in it. One live request.

      ``highlight_id`` is :attr:`Highlight.id <dumpstagram.models.Highlight.id>`, in the
      ``highlight:<number>`` form :meth:`~dumpstagram.namespaces.profiles.AsyncProfiles.highlights`
      hands out, and anything else raises :class:`ValueError` before anything is sent. An answer
      with no reel raises :class:`~dumpstagram.errors.NotFound`.

      Nothing is marked seen, for :meth:`reel`'s reason. This sends the viewer's query alone,
      with the site root as its referer, where a browser opens a highlight from a profile.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_highlight(
            client._sender,
            client._session,
            highlight_id,
            user_agent=client._user_agent,
         )
      )


class SyncStories:
   """Stories, as ``client.stories`` on :class:`~dumpstagram.client.SyncClient`. Each method
   blocks on the shared loop thread and answers as its :class:`AsyncStories` twin does."""

   _client: SyncClient

   def __init__(self) -> None:
      raise TypeError("a SyncStories comes from SyncClient.stories, it is not built directly")

   @classmethod
   def _of(cls, client: SyncClient) -> SyncStories:
      namespace = object.__new__(cls)
      namespace._client = client

      return namespace

   def tray(self) -> tuple[TrayReel, ...]:
      """Read the stories tray. Blocks until it has it.

      The same call as :meth:`AsyncStories.tray`, run on the shared loop thread. One live
      request.
      """

      return self._client._loop.run(
         self._client._impl.stories.tray(),
         operation="SyncClient.stories.tray",
      )

   def reel(self, user_id: str) -> StoryReel | None:
      """Read one account's live stories. Blocks until it has them.

      The same call as :meth:`AsyncStories.reel`, run on the shared loop thread. One live
      request, and no item is marked seen.
      """

      return self._client._loop.run(
         self._client._impl.stories.reel(user_id),
         operation="SyncClient.stories.reel",
      )

   def highlight(self, highlight_id: str) -> StoryReel:
      """Read one highlight. Blocks until it has it.

      The same call as :meth:`AsyncStories.highlight`, run on the shared loop thread. One live
      request, and no item is marked seen.
      """

      return self._client._loop.run(
         self._client._impl.stories.highlight(highlight_id),
         operation="SyncClient.stories.highlight",
      )
