"""The page-load cookie sync, sent as a delayed tail after a document action.

A browser runs the sync seconds after its page loads, often after the user's next action has
started, so it is not part of the document's action and it does not take a pacer slot. It is
the second named exception to a serial ``_core``, after the profile page's fan out, ruled by
the owner on 2026-09-23 as ruling 17 in ``engine/docs/build-plan.md``.

The timing is drawn from twelve captured loads across four runs. The iframe document departed
3.8 to 7.8 s after the page's document, and the iframe was ready 0.15 to 2.45 s after that,
when the ``fr`` exchange and the iframe's fetch went out together. The post back followed the
fetch's answer by 40 to 70 ms. Both draws are uniform over the observed range, an ASSUMPTION
about the shape from twelve samples.

A tail waits while the account is held for a throttle and departs nothing once the session is
in a checkpoint. A newer page load replaces a pending tail, and closing the client cancels it,
which is what navigating away or closing the tab does. Its failures never reach the caller,
whose action has already returned: a checkpoint is recorded on the session, a throttle on the
pacer, and anything else ends the tail, clearing ``fr`` when it was the exchange that failed,
as the page does.

``fr`` follows the page's rule and nothing else. An answer equal to what was sent changes
nothing, an empty answer removes it, any other answer is stored, and a failed exchange removes
it. When the answer differs, the page goes on to hand it to the iframe, a branch no capture has
recorded, so the engine stores it and sends nothing further.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Callable

from dumpstagram._core.pacer import backoff_delay
from dumpstagram._core.page_load import raise_only_what_concerns_the_account
from dumpstagram._core.requesting import BackgroundSender
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, PageParameters
from dumpstagram._private.web.cookie_sync import (
   build_facebook_sync_request,
   build_fr_cookie_request,
   build_iframe_document_request,
   build_instagram_sync_request,
   read_fr,
   read_iframe_parameters,
   read_sync_data,
   syncs_on,
)
from dumpstagram.errors import CheckpointRequired, DumpstagramError, RateLimited
from dumpstagram.session import Session

__all__ = ["IFRAME_DELAY_SECONDS", "READY_GAP_SECONDS", "CookieSync"]

IFRAME_DELAY_SECONDS = (3.8, 7.8)
"""From the page's document departing to the iframe document departing."""

READY_GAP_SECONDS = (0.15, 2.45)
"""From the iframe document answering to the exchange and the fetch departing."""


class CookieSync:
   """The one pending cookie sync tail of one client's account.

   ``instagram`` carries the account's cookies and ``facebook`` carries none. Both pass the
   same pacer, whose clock the tail's delays are measured on.
   """

   def __init__(
      self,
      instagram: BackgroundSender,
      facebook: BackgroundSender,
      *,
      draw: Callable[[float, float], float] = random.uniform,
   ) -> None:
      self._instagram = instagram
      self._facebook = facebook
      self._pacer = instagram.pacer
      self._draw = draw
      self._tail: asyncio.Task[None] | None = None
      self._closed = False

   @property
   def pending(self) -> bool:
      """Whether a tail has been started and has not finished."""

      return self._tail is not None and not self._tail.done()

   def start(
      self,
      session: Session,
      page_url: str,
      *,
      loaded_at: float,
      user_agent: str = DEFAULT_USER_AGENT,
   ) -> None:
      """Schedule the tail of a page at ``page_url`` whose document departed at ``loaded_at``.

      ``loaded_at`` is an instant on the pacer's clock. A page whose path the page itself
      exempts starts nothing, and a pending tail from an earlier page is dropped either way,
      since a new document unloads the old page.
      """

      self.drop()

      is_exempt_page = not syncs_on(page_url)
      should_not_start = self._closed or is_exempt_page

      if should_not_start:
         return

      self._tail = asyncio.get_running_loop().create_task(
         self._run(session, page_url, loaded_at, user_agent)
      )

   def drop(self) -> None:
      """Cancel a pending tail, wherever it is."""

      tail = self._tail

      if tail is not None:
         tail.cancel()

   async def aclose(self) -> None:
      """Cancel a pending tail and wait for it to stop. Nothing starts afterwards."""

      self._closed = True
      tail = self._tail

      if tail is None:
         return

      tail.cancel()
      await asyncio.gather(tail, return_exceptions=True)

   async def _run(self, session: Session, page_url: str, loaded_at: float, user_agent: str) -> None:
      iframe_departs_at = loaded_at + self._draw(*IFRAME_DELAY_SECONDS)
      await self._pacer.sleep(max(0.0, iframe_departs_at - self._pacer.now()))

      if session.checkpoint_active:
         return

      try:
         document = await self._facebook.send(build_iframe_document_request(user_agent))
         parameters = read_iframe_parameters(document)
      except DumpstagramError:
         return

      await self._pacer.sleep(self._draw(*READY_GAP_SECONDS))

      if session.checkpoint_active:
         return

      async with asyncio.TaskGroup() as group:
         group.create_task(self._exchange_fr(session, page_url, user_agent))
         group.create_task(self._relay(session, parameters, page_url, user_agent))

   async def _exchange_fr(self, session: Session, page_url: str, user_agent: str) -> None:
      sent = session.fr

      try:
         response = await self._instagram.send(
            build_fr_cookie_request(session, page_url, user_agent)
         )
         answer = read_fr(response)
      except DumpstagramError as failure:
         session.fr = None
         self._record(session, failure)
         return

      if answer == sent:
         return

      session.fr = answer or None

   async def _relay(
      self,
      session: Session,
      parameters: PageParameters,
      page_url: str,
      user_agent: str,
   ) -> None:
      try:
         fetched = await self._facebook.send(build_facebook_sync_request(parameters, user_agent))
         encrypted_data = read_sync_data(fetched)
      except DumpstagramError:
         return

      if session.checkpoint_active:
         return

      request = build_instagram_sync_request(session, encrypted_data, page_url, user_agent)

      try:
         raise_only_what_concerns_the_account(await self._instagram.send(request))
      except DumpstagramError as failure:
         self._record(session, failure)

   def _record(self, session: Session, failure: DumpstagramError) -> None:
      """Keep what concerns the whole account from a failure nobody is waiting on."""

      if isinstance(failure, CheckpointRequired):
         session.checkpoint_active = True
         return

      if isinstance(failure, RateLimited):
         delay = backoff_delay(1, self._pacer.backoff, retry_after=failure.retry_after)
         self._pacer.hold(delay)
