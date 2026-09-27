"""``client.account``, reading the viewer's own pending follow requests and activity feed.

Reading the activity feed through the engine does not mark it seen. A browser opening it follows
the read with a separate request that clears the viewer's own notifications badge, and the
engine sends none until that request is verified (W74).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from dumpstagram._core.account import read_activity_feed, read_follow_requests
from dumpstagram.models import ActivityFeed, FollowRequests

if TYPE_CHECKING:
   from dumpstagram.aio import AsyncClient
   from dumpstagram.client import SyncClient

__all__ = ["AsyncAccount", "SyncAccount"]


class AsyncAccount:
   """The viewer's own account, as ``client.account`` on :class:`~dumpstagram.aio.AsyncClient`."""

   _client: AsyncClient

   def __init__(self) -> None:
      raise TypeError("an AsyncAccount comes from AsyncClient.account, it is not built directly")

   @classmethod
   def _of(cls, client: AsyncClient) -> AsyncAccount:
      namespace = object.__new__(cls)
      namespace._client = client

      return namespace

   async def follow_requests(self) -> FollowRequests:
      """Read the accounts asking to follow the viewer. One live request.

      Only a private account receives follow requests, so a public one reads none. The accounts
      are the first page, in the upstream's order, and ``has_more`` says whether the list goes
      on. Nothing reads further, because no next page has been observed. A row carries no
      relationship to the viewer.

      A browser reads this inside its direct inbox load. This sends it alone, with the inbox as
      its referer, a departure recorded in ``docs/web-request-contract.md``.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_follow_requests(
            client._sender,
            client._session,
            user_agent=client._user_agent,
         )
      )

   async def activity(self) -> ActivityFeed:
      """Read the viewer's activity feed, the likes, follows, comments and requests the
      notifications page lists. One live request, and a bootstrap when the session holds no
      page token.

      This does not mark the feed seen. A browser opening the notifications page follows the
      read with a request that clears the viewer's own badge, which nobody else sees, and the
      engine sends none until that request is verified, a departure from browser parity recorded
      in ``docs/web-request-contract.md``. The read itself may move
      :attr:`~dumpstagram.models.ActivityFeed.last_checked_at`: of two reads seconds apart,
      the second answered a last check that falls on the first's send (INFERENCE that a read
      records a check).

      ``is_last_page`` is the upstream's own flag. No next page is read, because none has been
      observed, so where it is false the feed holds its first page only.
      """

      client = self._client
      client._refuse_when_closed()

      return await client._watch_for_checkpoint(
         read_activity_feed(
            client._sender,
            client._session,
            user_agent=client._user_agent,
         )
      )


class SyncAccount:
   """The viewer's own account, as ``client.account`` on :class:`~dumpstagram.client.SyncClient`.
   Each method blocks on the shared loop thread and answers as its :class:`AsyncAccount` twin
   does."""

   _client: SyncClient

   def __init__(self) -> None:
      raise TypeError("a SyncAccount comes from SyncClient.account, it is not built directly")

   @classmethod
   def _of(cls, client: SyncClient) -> SyncAccount:
      namespace = object.__new__(cls)
      namespace._client = client

      return namespace

   def follow_requests(self) -> FollowRequests:
      """Read the accounts asking to follow the viewer. Blocks until it has them.

      The same call as :meth:`AsyncAccount.follow_requests`, run on the shared loop thread. One
      live request.
      """

      return self._client._loop.run(
         self._client._impl.account.follow_requests(),
         operation="SyncClient.account.follow_requests",
      )

   def activity(self) -> ActivityFeed:
      """Read the viewer's activity feed. Blocks until it has it.

      The same call as :meth:`AsyncAccount.activity`, run on the shared loop thread. One live
      request, and nothing is marked seen.
      """

      return self._client._loop.run(
         self._client._impl.account.activity(),
         operation="SyncClient.account.activity",
      )
