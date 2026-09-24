"""``client.social``, the viewer's relationships to other accounts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dumpstagram._core.writes.follows import follow_user, unfollow_user

if TYPE_CHECKING:
   from dumpstagram.aio import AsyncClient
   from dumpstagram.client import SyncClient

__all__ = ["AsyncSocial", "SyncSocial"]


class AsyncSocial:
   """Relationships, as ``client.social`` on :class:`~dumpstagram.aio.AsyncClient`."""

   _client: AsyncClient

   def __init__(self) -> None:
      raise TypeError("an AsyncSocial comes from AsyncClient.social, it is not built directly")

   @classmethod
   def _of(cls, client: AsyncClient) -> AsyncSocial:
      namespace = object.__new__(cls)
      namespace._client = client

      return namespace

   async def follow(self, user_id: str) -> None:
      """Follow the account whose numeric id is ``user_id``. One write, sent once, never retried.

      ``user_id`` is :attr:`Profile.id <dumpstagram.models.Profile.id>`. A username raises
      :class:`ValueError` before anything is sent, and
      :meth:`~dumpstagram.namespaces.profiles.AsyncProfiles.by_username` turns one into a
      :class:`~dumpstagram.models.Profile` carrying the id.

      Returns nothing, because the answer cannot tell a follow from a request. On a private
      account a follow becomes a follow request, and the answer selects ``following`` alone,
      which the request leaves false. The account's profile read with
      :meth:`~dumpstagram.namespaces.profiles.AsyncProfiles.by_id` says which it was, through
      ``friendship_status.following`` and ``friendship_status.outgoing_request``, and it is
      also the read that reconciles :class:`~dumpstagram.errors.OutcomeUnknown`. The account is
      notified of the follow.

      The write waits out the behavior's write spacing and counts against its write budget. The
      request a browser sends around a follow has not been recorded, so this sends the follow
      alone, a departure recorded in ``docs/web-request-contract.md``.
      """

      client = self._client
      client._refuse_when_closed()

      await client._watch_for_checkpoint(
         follow_user(
            client._sender,
            client._session,
            user_id,
            user_agent=client._user_agent,
         )
      )

   async def unfollow(self, user_id: str) -> None:
      """Unfollow the account whose numeric id is ``user_id``. One write, sent once, never
      retried.

      The same identifier, rules and reconciling read as :meth:`follow`. An answer that still
      reports following raises :class:`~dumpstagram.errors.UpstreamRejected`. Whether it also
      withdraws a pending follow request to a private account is unobserved, so read
      ``friendship_status.outgoing_request`` afterwards when that matters.
      """

      client = self._client
      client._refuse_when_closed()

      await client._watch_for_checkpoint(
         unfollow_user(
            client._sender,
            client._session,
            user_id,
            user_agent=client._user_agent,
         )
      )


class SyncSocial:
   """Relationships, as ``client.social`` on :class:`~dumpstagram.client.SyncClient`. Each
   method blocks on the shared loop thread and answers as its :class:`AsyncSocial` twin does."""

   _client: SyncClient

   def __init__(self) -> None:
      raise TypeError("a SyncSocial comes from SyncClient.social, it is not built directly")

   @classmethod
   def _of(cls, client: SyncClient) -> SyncSocial:
      namespace = object.__new__(cls)
      namespace._client = client

      return namespace

   def follow(self, user_id: str) -> None:
      """Follow the account whose numeric id is ``user_id``. Blocks until the write is answered.

      The same call as :meth:`AsyncSocial.follow`, run on the shared loop thread. One write,
      sent once, never retried.
      """

      return self._client._loop.run(
         self._client._impl.social.follow(user_id),
         operation="SyncClient.social.follow",
      )

   def unfollow(self, user_id: str) -> None:
      """Unfollow the account whose numeric id is ``user_id``. Blocks until the write is
      answered.

      The same call as :meth:`AsyncSocial.unfollow`, run on the shared loop thread. One write,
      sent once, never retried.
      """

      return self._client._loop.run(
         self._client._impl.social.unfollow(user_id),
         operation="SyncClient.social.unfollow",
      )
