"""``client.stories``, reading the stories tray, one account's live stories and one highlight,
and marking a story item seen.

Under the default behavior, reading an account's live stories or a highlight marks its first
item seen, as a browser's story viewer does when it opens, and the story's owner sees the viewer
in that item's seen list. :attr:`~dumpstagram.behavior.Behavior.mark_stories_seen` set to False
reads without marking. The tray marks nothing (W94).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dumpstagram._core.stories import read_highlight, read_stories_tray, read_story_reel
from dumpstagram._core.writes.stories import mark_story_item_seen
from dumpstagram.models import StoryItem, StoryReel, TrayReel

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
      cursor, so the tuple is the tray as sent. Nothing is marked seen, under any behavior, as a
      browser's tray marks nothing.

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
      """Read one account's live stories, every item in its reel. One live request, and under
      the default behavior one write marking the first item seen.

      ``user_id`` is the numeric account id, :attr:`Profile.id
      <dumpstagram.models.Profile.id>` or a tray row's ``owner.id``, and a username raises
      :class:`ValueError` before anything is sent. Returns ``None`` when the account has no live
      story, which is how the upstream answered the owner's own reel with none up.

      **This marks the reel's first item seen under the default behavior, and the account
      sees you in that item's seen list**, exactly as opening the story on the website does: a
      browser's story viewer marks the item it shows first with a separate mutation, and the
      engine sends that mutation after the read, one write that counts against the write budget
      and waits out the write spacing. Only the first item is marked, because a read returns
      every item at once while a browser shows one at a time; :meth:`mark_seen` marks any other.
      A browser opening a reel it has partly seen starts at the first unseen item, which the
      read does not say, so the engine marks the first item either way.
      :attr:`~dumpstagram.behavior.Behavior.mark_stories_seen` set to False marks nothing. When
      the write fails, its error is raised and the reel is not returned, so a caller is never
      told a story was read in parity when it was not; read again with marking off to get the
      reel alone.

      No live story has been read yet, only highlights, whose items are story items, so the
      item model is ASSUMED to fit a live reel too. A browser reads a reel when the story viewer
      opens. This sends it alone, with the site root as its referer.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_story_reel(
            client._sender,
            client._session,
            user_id,
            user_agent=client._user_agent,
            mark_first_item_seen=client._behavior.mark_stories_seen,
         )
      )

   async def highlight(self, highlight_id: str) -> StoryReel:
      """Read one highlight, every item in it. One live request, and under the default behavior
      one write marking the first item seen.

      ``highlight_id`` is :attr:`Highlight.id <dumpstagram.models.Highlight.id>`, in the
      ``highlight:<number>`` form :meth:`~dumpstagram.namespaces.profiles.AsyncProfiles.highlights`
      hands out, and anything else raises :class:`ValueError` before anything is sent. An answer
      with no reel raises :class:`~dumpstagram.errors.NotFound`.

      **Under the default behavior this marks the highlight's first item seen, as :meth:`reel`
      does, and on another account's highlight that account sees you in the item's seen list.**
      :attr:`~dumpstagram.behavior.Behavior.mark_stories_seen` set to False marks nothing. This
      sends the viewer's query alone, with the site root as its referer, where a browser opens a
      highlight from a profile.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_highlight(
            client._sender,
            client._session,
            highlight_id,
            user_agent=client._user_agent,
            mark_first_item_seen=client._behavior.mark_stories_seen,
         )
      )

   async def mark_seen(self, item: StoryItem, *, reel: StoryReel) -> None:
      """Mark one story item seen. One write, sent once, never retried.

      **The item's owner sees you in its seen list**, as when the item is shown on the website.
      ``item`` is one of ``reel.items``, and ``reel`` is the
      :class:`~dumpstagram.models.StoryReel` it was read in, from :meth:`reel` or
      :meth:`highlight`: the reel's id and the item's owner, pk and time posted are what the
      mutation carries, so an item that is not in ``reel`` raises :class:`ValueError` before
      anything is sent. Use it to mark the items after the first, which a read under the
      default behavior already marks.

      The write waits out the behavior's write spacing, counts against its write budget, and
      raises :class:`~dumpstagram.errors.OutcomeUnknown` if the connection fails while it is in
      flight. An answer with no seen response raises
      :class:`~dumpstagram.errors.UpstreamRejected` with code ``story_not_marked_seen``. The
      answer is the only confirmation: a highlight read carries no seen state, and a live
      reel's is the tray row's ``seen_at`` from :meth:`tray`. It does not depend on
      :attr:`~dumpstagram.behavior.Behavior.mark_stories_seen`, which governs reads only.
      """

      client = self._client
      client._refuse_when_closed()

      await client._watch_for_checkpoint(
         mark_story_item_seen(
            client._sender,
            client._session,
            reel,
            item,
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
      request, and under the default behavior one write marking the first item seen, which the
      account sees.
      """

      return self._client._loop.run(
         self._client._impl.stories.reel(user_id),
         operation="SyncClient.stories.reel",
      )

   def highlight(self, highlight_id: str) -> StoryReel:
      """Read one highlight. Blocks until it has it.

      The same call as :meth:`AsyncStories.highlight`, run on the shared loop thread. One live
      request, and under the default behavior one write marking the first item seen, which the
      highlight's owner sees.
      """

      return self._client._loop.run(
         self._client._impl.stories.highlight(highlight_id),
         operation="SyncClient.stories.highlight",
      )

   def mark_seen(self, item: StoryItem, *, reel: StoryReel) -> None:
      """Mark one story item seen. Blocks until the write is answered.

      The same call as :meth:`AsyncStories.mark_seen`, run on the shared loop thread. One write,
      sent once, never retried, and the item's owner sees you in its seen list.
      """

      return self._client._loop.run(
         self._client._impl.stories.mark_seen(item, reel=reel),
         operation="SyncClient.stories.mark_seen",
      )
