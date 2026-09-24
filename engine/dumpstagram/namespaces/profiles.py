"""``client.profiles``, reading one account's profile."""

from __future__ import annotations

from typing import TYPE_CHECKING

from dumpstagram._core.profiles import read_profile, read_profile_by_id
from dumpstagram.models import Profile

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
