"""Send a text message into a direct thread and unsend one, each sent once through
``_core/writing.py``.

A message appends, so a send is never sent again. After an unknown outcome the reconciling read
is the thread itself: every send carries an ``offline_threading_id`` the client generated, fresh
per call, and the thread read echoes it on the message, so the message is found exactly rather
than by its text and a time window.

An unsend sets a state. It takes the thread's 39-digit ``thread_id``, which no message carries,
so the thread is opened first to learn it. The open is a read and may recover a stale token like
any read. The unsend is not.

The recipient is notified of a message and may read it before any unsend.
"""

from __future__ import annotations

import secrets
import time
from collections.abc import Callable

from dumpstagram._core.direct import read_thread_id
from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.writing import send_write
from dumpstagram._private.transport import WriteRequest
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.parse.direct import (
   parse_direct_text_send_answer,
   parse_direct_unsend_answer,
)
from dumpstagram._private.web.requests.direct import (
   build_direct_text_send_request,
   build_direct_unsend_request,
   is_a_thread_fbid,
   offline_threading_id,
)
from dumpstagram.errors import UpstreamRejected
from dumpstagram.models import SentMessage
from dumpstagram.session import Session

__all__ = ["send_message", "unsend_message"]

UNSEND_NOT_APPLIED = "message_not_unsent"
"""The code raised when an unsend is answered without an error but with false."""

MESSAGE_ID_PREFIX = "mid."

RANDOM_BITS = 32
"""The browser draws a random number up to 4294967295 and keeps the low 22 bits of it."""


def _clock_ms() -> int:
   return int(time.time() * 1000)


def _random_bits() -> int:
   return secrets.randbits(RANDOM_BITS)


async def send_message(
   sender: PacedSender,
   session: Session,
   thread_fbid: str,
   text: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
   clock_ms: Callable[[], int] = _clock_ms,
   random_bits: Callable[[], int] = _random_bits,
) -> SentMessage:
   """Send ``text`` into the thread whose ``thread_fbid`` is ``thread_fbid``. One write, and
   one bootstrap first when the session carries no page token."""

   _refuse_what_is_not_a_thread_fbid(thread_fbid)

   if not text:
      raise ValueError("a message needs text, and an empty one was given")

   if not session.fb_dtsg:
      await bootstrap(sender, session, user_agent=user_agent)

   threading_id = offline_threading_id(clock_ms(), random_bits())
   request = build_direct_text_send_request(
      session, thread_fbid, text, threading_id, user_agent=user_agent
   )
   payload = await send_write(sender, session, WriteRequest(request, "send_message"))

   return parse_direct_text_send_answer(payload, thread_fbid, threading_id)


async def unsend_message(
   sender: PacedSender,
   session: Session,
   thread_fbid: str,
   message_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> None:
   """Unsend the viewer's message ``message_id`` from the thread whose ``thread_fbid`` is
   ``thread_fbid``. One thread open, a read, then one write."""

   _refuse_what_is_not_a_thread_fbid(thread_fbid)

   is_a_message_id = message_id.startswith(MESSAGE_ID_PREFIX)

   if not is_a_message_id:
      raise ValueError(f"{message_id!r} is not a message id. Pass Message.id, a mid. string")

   thread_id = await read_thread_id(sender, session, thread_fbid, user_agent=user_agent)

   if not session.fb_dtsg:
      await bootstrap(sender, session, user_agent=user_agent)

   request = build_direct_unsend_request(
      session, thread_fbid, thread_id, message_id, user_agent=user_agent
   )
   payload = await send_write(sender, session, WriteRequest(request, "unsend_message"))

   applied = parse_direct_unsend_answer(payload)

   if not applied:
      raise UpstreamRejected(
         "the answer to an unsend said it did not apply",
         code=UNSEND_NOT_APPLIED,
      )


def _refuse_what_is_not_a_thread_fbid(thread_fbid: str) -> None:
   if not is_a_thread_fbid(thread_fbid):
      raise ValueError(f"{thread_fbid!r} is not a thread_fbid, which is digits only")
