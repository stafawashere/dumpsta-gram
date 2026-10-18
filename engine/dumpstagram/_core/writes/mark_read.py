"""Mark a direct thread read, sent once through ``_core/writing.py``.

A mark read moves the viewer's read receipt, which the other participants see, so it is a write
like any other and counts against the write budget. The validation a browser sends 2 ms after
it changes nothing anyone was seen to see, so it follows as an ordinary paced request rather
than a second write, and is never sent when the mark read raised.

It lives apart from ``direct.py`` because the thread read sends it, and ``direct.py`` reads the
thread to unsend.
"""

from __future__ import annotations

from dumpstagram._core.requesting import PacedSender
from dumpstagram._core.writing import send_write
from dumpstagram._private.transport import WriteRequest
from dumpstagram._private.web.bootstrap import DEFAULT_USER_AGENT, bootstrap
from dumpstagram._private.web.classify import classify
from dumpstagram._private.web.parse.direct import (
   ThreadReadState,
   parse_mark_read_answer,
   parse_mark_read_validation,
)
from dumpstagram._private.web.requests.direct import (
   build_mark_thread_read_request,
   build_mark_thread_read_validation_request,
)
from dumpstagram.errors import UpstreamRejected
from dumpstagram.session import Session

__all__ = ["MARK_READ_NOT_APPLIED", "mark_thread_read"]

MARK_READ_NOT_APPLIED = "thread_not_marked_read"
"""The code raised when a mark read is answered without an error but with no read receipt."""


async def mark_thread_read(
   sender: PacedSender,
   session: Session,
   thread_fbid: str,
   state: ThreadReadState,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> bool:
   """Mark the thread ``thread_fbid`` read up to its newest message, as a browser does once the
   thread is open, when ``state``, read from that open, says it is unread. Returns whether the
   mark was sent.

   One write and then the validation, an ordinary request. Nothing is sent for a thread the
   viewer has already read, or one with no message on its newest page.
   """

   newest_id = state.newest_message_id
   newest_ms = state.newest_sent_ms

   if not state.is_unread or newest_id is None or newest_ms is None:
      return False

   if not session.fb_dtsg:
      await bootstrap(sender, session, user_agent=user_agent)

   mark = build_mark_thread_read_request(
      session, thread_fbid, state.thread_id, newest_id, user_agent=user_agent
   )
   payload = await send_write(sender, session, WriteRequest(mark, "mark_thread_read"))

   if not parse_mark_read_answer(payload):
      raise UpstreamRejected(
         "the answer to a mark read carried no read receipt",
         code=MARK_READ_NOT_APPLIED,
      )

   validation = build_mark_thread_read_validation_request(
      session, thread_fbid, state.thread_id, newest_id, newest_ms, user_agent=user_agent
   )
   parse_mark_read_validation(classify(await sender.send(validation)))

   return True
