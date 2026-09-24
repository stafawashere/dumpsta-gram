"""``client.direct``, direct threads and the notes on the direct inbox."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dumpstagram._core.direct import read_thread_messages
from dumpstagram._core.notes import read_notes
from dumpstagram._core.writes.direct import send_message, unsend_message
from dumpstagram._core.writes.notes import delete_note, set_note
from dumpstagram.models import Message, Note, NoteAudience, Page, SentMessage

if TYPE_CHECKING:
   from dumpstagram.aio import AsyncClient
   from dumpstagram.client import SyncClient

__all__ = ["AsyncDirect", "SyncDirect"]


class AsyncDirect:
   """Direct threads and the inbox's notes tray, as ``client.direct`` on
   :class:`~dumpstagram.aio.AsyncClient`."""

   _client: AsyncClient

   def __init__(self) -> None:
      raise TypeError("an AsyncDirect comes from AsyncClient.direct, it is not built directly")

   @classmethod
   def _of(cls, client: AsyncClient) -> AsyncDirect:
      namespace = object.__new__(cls)
      namespace._client = client

      return namespace

   async def messages(
      self,
      thread_fbid: str,
      *,
      after: str | None = None,
      newer_than_message_id: str | None = None,
   ) -> Page[Message]:
      """Read one page of one direct thread.

      ``thread_fbid`` is the thread's ``fbid``, which is one of three identifiers the same
      thread has. The other two return an empty answer rather than an error, so the parameter
      name says which one it wants.

      ``after`` is an ``end_cursor`` from a previous page. ``newer_than_message_id`` fetches
      only what has arrived since a message already seen, which makes a poll a top-up rather
      than a full re-read.

      The returned page's ``has_next_page`` is the only thing that says whether more exist. A
      short page is not the end of the thread.

      Under the default behavior the newest page is read with the query a browser sends when
      it opens the thread, and every other page with the query it sends as the thread scrolls.
      :attr:`~dumpstagram.behavior.Behavior.thread_first_page` set to
      :attr:`~dumpstagram.behavior.ThreadFirstPage.QUERY` reads the newest page with the
      scrolling query too. One live request either way.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_thread_messages(
            client._sender,
            client._session,
            thread_fbid,
            after=after,
            newer_than_message_id=newer_than_message_id,
            first_page=client._behavior.thread_first_page,
            user_agent=client._user_agent,
         )
      )

   async def send(self, thread_fbid: str, text: str) -> SentMessage:
      """Send ``text`` into the direct thread whose ``thread_fbid`` is ``thread_fbid``. One write,
      sent once, never retried.

      ``thread_fbid`` is the value :meth:`messages` takes. The thread must exist: a send that
      would start a new thread takes a different shape, which is not built. Empty text raises
      :class:`ValueError` before anything is sent.

      Returns a :class:`~dumpstagram.models.SentMessage` with the new message's ``id``, which is
      what :meth:`unsend` takes, its ``sent_at``, and the ``offline_threading_id`` this client
      generated for it. The answer carries nothing else, so the full
      :class:`~dumpstagram.models.Message` comes from reading the thread.

      A message appends, so it is never sent again, by this library or by any retry path. The
      recipient is notified and may read it at once. If the connection fails while it is in
      flight this raises :class:`~dumpstagram.errors.OutcomeUnknown`, and sending again may
      deliver it twice. To reconcile, read the thread's newest page with :meth:`messages` for
      the viewer's own message with this text sent since the attempt began before deciding
      anything. That match is ambiguous when the same text went twice. A send that returned is
      found exactly instead: the read echoes its ``offline_threading_id`` on
      :attr:`Message.offline_threading_id <dumpstagram.models.Message.offline_threading_id>`.

      The write waits out the behavior's write spacing and counts against its write budget. A
      browser marks the thread read and refetches it around a send. This sends the message
      alone, a departure recorded in ``docs/web-request-contract.md``.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         send_message(
            client._sender,
            client._session,
            thread_fbid,
            text,
            user_agent=client._user_agent,
         )
      )

   async def unsend(self, thread_fbid: str, message_id: str) -> None:
      """Unsend the viewer's own message ``message_id`` from the thread ``thread_fbid``. One
      write, sent once, never retried.

      ``message_id`` is :attr:`SentMessage.id <dumpstagram.models.SentMessage.id>` or
      :attr:`Message.id <dumpstagram.models.Message.id>`, a ``mid.`` string, and anything else
      raises :class:`ValueError` before anything is sent.

      The unsend names the thread by a third identifier that no message carries and only the
      thread open does, so the thread is opened first, as a browser has it open when its menu
      unsends. Two requests: the open, a read, and the unsend, a write.

      The recipient may already have read the message. An answer saying the unsend did not apply
      raises :class:`~dumpstagram.errors.UpstreamRejected` with code ``message_not_unsent``. After
      :class:`~dumpstagram.errors.OutcomeUnknown`, read the thread's newest page: an unsent
      message is no longer listed, with no placeholder in its place.
      """

      client = self._client
      client._refuse_when_closed()

      await client._watch_for_checkpoint(
         unsend_message(
            client._sender,
            client._session,
            thread_fbid,
            message_id,
            user_agent=client._user_agent,
         )
      )

   async def notes(self) -> tuple[Note, ...]:
      """Read the notes tray on the direct inbox, whole, in the tray's order. One live request.

      Each author has at most one note, and the viewer's own is the one whose
      :attr:`~dumpstagram.models.Note.author_id` equals this session's ``ds_user_id``. It is
      absent when the viewer has no note.

      The tray is one call with no cursor. If the upstream ever starts paging it, this raises
      :class:`~dumpstagram.errors.SchemaChanged` rather than returning the first page as the
      whole tray.

      A browser reads the tray inside an inbox page load, beside nine other queries. This sends
      the tray query alone under every behavior, a departure recorded in
      ``docs/web-request-contract.md`` until the inbox load is modelled.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_notes(
            client._sender,
            client._session,
            user_agent=client._user_agent,
         )
      )

   async def set_note(
      self, text: str, *, audience: NoteAudience = NoteAudience.CLOSE_FRIENDS
   ) -> Note:
      """Set the viewer's note on the direct inbox to ``text``. One write, sent once.

      Returns the created note, whose ``id`` is what :meth:`delete_note` takes. A set replaces
      any note the viewer already has up, whatever it was, including a song note, which this
      library cannot make again. Read :meth:`notes` first when the old one matters. Empty text
      raises :class:`ValueError`.

      ``audience`` defaults to :attr:`NoteAudience.CLOSE_FRIENDS
      <dumpstagram.models.NoteAudience.CLOSE_FRIENDS>`, the narrower of the two the web
      composer offers, so a note set without choosing is seen by the fewest people. Pass
      :attr:`NoteAudience.MUTUAL_FOLLOWS <dumpstagram.models.NoteAudience.MUTUAL_FOLLOWS>` for
      the composer's own default, followers the viewer follows back. If the upstream answers
      without an error but reports another audience, this raises
      :class:`~dumpstagram.errors.UpstreamRejected` with code ``note_audience_did_not_follow``,
      and the note it made is up.

      The write waits out the behavior's write spacing, counts against its write budget, and
      raises :class:`~dumpstagram.errors.OutcomeUnknown` if the connection fails while it is in
      flight. To reconcile that, read :meth:`notes` and look for the viewer's own note: a set
      replaces rather than appends, so sending again converges on one note.

      The request a browser sends around a note has not been recorded, so this sends the
      create alone, a departure recorded in ``docs/web-request-contract.md``.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         set_note(
            client._sender,
            client._session,
            text,
            audience=audience,
            user_agent=client._user_agent,
         )
      )

   async def delete_note(self, note_id: str) -> None:
      """Delete the viewer's note whose tray item id is ``note_id``. One write, sent once.

      ``note_id`` is :attr:`Note.id <dumpstagram.models.Note.id>`, from :meth:`set_note` or
      from the viewer's own item in :meth:`notes`, digits only, and never the author's id. The
      upstream answers a delete with nothing, so success is an answer without an error. After
      :class:`~dumpstagram.errors.OutcomeUnknown`, read :meth:`notes`: a note no longer listed
      is gone.
      """

      client = self._client
      client._refuse_when_closed()

      await client._watch_for_checkpoint(
         delete_note(
            client._sender,
            client._session,
            note_id,
            user_agent=client._user_agent,
         )
      )


class SyncDirect:
   """Direct threads and the inbox's notes tray, as ``client.direct`` on
   :class:`~dumpstagram.client.SyncClient`. Each method blocks on the shared loop thread and
   answers as its :class:`AsyncDirect` twin does."""

   _client: SyncClient

   def __init__(self) -> None:
      raise TypeError("a SyncDirect comes from SyncClient.direct, it is not built directly")

   @classmethod
   def _of(cls, client: SyncClient) -> SyncDirect:
      namespace = object.__new__(cls)
      namespace._client = client

      return namespace

   def messages(
      self,
      thread_fbid: str,
      *,
      after: str | None = None,
      newer_than_message_id: str | None = None,
   ) -> Page[Message]:
      """Read one page of one direct thread. Blocks until it has one.

      The same call as :meth:`AsyncDirect.messages`, with the same arguments and the same
      result, run on the shared loop thread. Exceptions cross back as themselves, with a note
      naming this method.
      """

      return self._client._loop.run(
         self._client._impl.direct.messages(
            thread_fbid,
            after=after,
            newer_than_message_id=newer_than_message_id,
         ),
         operation="SyncClient.direct.messages",
      )

   def send(self, thread_fbid: str, text: str) -> SentMessage:
      """Send a text message into a direct thread. Blocks until the write is answered.

      The same call as :meth:`AsyncDirect.send`, run on the shared loop thread. One write, sent
      once, never retried. After :class:`~dumpstagram.errors.OutcomeUnknown`, read
      :meth:`messages` before sending again, because a second send is a second message the
      recipient sees.
      """

      return self._client._loop.run(
         self._client._impl.direct.send(thread_fbid, text),
         operation="SyncClient.direct.send",
      )

   def unsend(self, thread_fbid: str, message_id: str) -> None:
      """Unsend the viewer's own message. Blocks until the write is answered.

      The same call as :meth:`AsyncDirect.unsend`, run on the shared loop thread. One thread
      open, then one write, sent once, never retried.
      """

      return self._client._loop.run(
         self._client._impl.direct.unsend(thread_fbid, message_id),
         operation="SyncClient.direct.unsend",
      )

   def notes(self) -> tuple[Note, ...]:
      """Read the notes tray on the direct inbox. Blocks until it has it.

      The same call as :meth:`AsyncDirect.notes`, run on the shared loop thread. One live
      request.
      """

      return self._client._loop.run(
         self._client._impl.direct.notes(),
         operation="SyncClient.direct.notes",
      )

   def set_note(self, text: str, *, audience: NoteAudience = NoteAudience.CLOSE_FRIENDS) -> Note:
      """Set the viewer's note. Blocks until the write is answered.

      The same call as :meth:`AsyncDirect.set_note`, with the same audience default, run on the
      shared loop thread. One write, sent once, never retried. It replaces any note already up.
      """

      return self._client._loop.run(
         self._client._impl.direct.set_note(text, audience=audience),
         operation="SyncClient.direct.set_note",
      )

   def delete_note(self, note_id: str) -> None:
      """Delete the viewer's note. Blocks until the write is answered.

      The same call as :meth:`AsyncDirect.delete_note`, run on the shared loop thread. One
      write, sent once, never retried.
      """

      return self._client._loop.run(
         self._client._impl.direct.delete_note(note_id),
         operation="SyncClient.direct.delete_note",
      )
