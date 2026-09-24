"""The direct requests: a thread's pages, opening a thread, the inbox listing, and a text send
and its unsend.
"""

from __future__ import annotations

from typing import Any

from dumpstagram._private.transport import Request
from dumpstagram._private.web.bootstrap import BOOTSTRAP_URL, DEFAULT_USER_AGENT, ORIGIN
from dumpstagram._private.web.documents.direct import (
   DIRECT_INBOX,
   DIRECT_TEXT_SEND,
   DIRECT_UNSEND,
   THREAD_DETAIL,
   THREAD_MESSAGE_PAGE,
   THREAD_OLDER_PAGE,
)
from dumpstagram._private.web.requests.common import _USER_ID, build_graphql_request
from dumpstagram.session import Session

__all__ = [
   "INBOX_ROW_MESSAGES",
   "PAGE_SIZE",
   "SEND_ATTRIBUTION",
   "build_direct_text_send_request",
   "build_direct_unsend_request",
   "build_inbox_listing_request",
   "build_thread_detail_request",
   "build_thread_older_page_request",
   "build_thread_page_request",
   "is_a_thread_fbid",
   "offline_threading_id",
   "thread_url",
]

PAGE_SIZE = 20
"""Capped server side.

Requesting 20, 50 and 200 each returned exactly 20, so a larger number here buys nothing and
the cost of an operation is a fixed function of how much data it covers.
"""

SEND_ATTRIBUTION = "igd_web_chat_tab:in_thread"
"""What the composer names as the origin of a text send, a literal in its source.

The same string was compiled on a thread page and sent from the chat tab a profile page opens.
"""

_OFFLINE_THREADING_ID_BITS = 63

_OFFLINE_THREADING_RANDOM_BITS = 22

INBOX_ROW_MESSAGES = 5
"""How many of its newest messages each inbox row carries, as every captured inbox load asked."""


def build_thread_page_request(
   session: Session,
   thread_fbid: str,
   *,
   after: str | None = None,
   newer_than_message_id: str | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """One page of one direct thread.

   ``thread_fbid`` is the thread's ``fbid``, which is one of three ids the same thread has.
   Passing the wrong one returns an empty result rather than an error, so the identifier kind
   is part of the signature rather than something a caller works out.

   ``newer_than_message_id`` fetches only what has arrived since a message already seen,
   which is what makes a polling listener a top-up rather than a full re-read.
   """

   return build_graphql_request(
      session,
      THREAD_MESSAGE_PAGE,
      _thread_page_variables(thread_fbid, after, newer_than_message_id),
      referer=thread_url(thread_fbid),
      user_agent=user_agent,
   )


def thread_url(thread_fbid: str) -> str:
   """The page a browser has open while it reads a thread, and so the referer of every read."""

   return f"{ORIGIN}/direct/t/{thread_fbid}/"


def _thread_page_variables(
   thread_fbid: str,
   after: str | None,
   newer_than_message_id: str | None,
) -> dict[str, Any]:
   return {
      "after": after,
      "before": None,
      "first": PAGE_SIZE,
      "last": None,
      "newer_than_message_id": newer_than_message_id,
      "older_than_message_id": None,
      "id": thread_fbid,
      "__relay_internal__pv__IGDInitialMessagePageCountrelayprovider": PAGE_SIZE,
   }


def build_thread_detail_request(
   session: Session,
   thread_fbid: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The query a browser sends to open a thread, which answers with its newest page.

   ``IGDEnableOffMsysChatThemesQErelayprovider`` is false because every one of the 63 requests
   a browser sent across four captures on 2026-09-23 carried false. The finding's replay
   template carries true, and that replay answered too, so the flag is not what makes the
   request succeed. It is reproduced as the browser sends it.

   ``min_uq_seq_id`` was null on all 63.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/open-a-direct-thread.md``.
   """

   variables = {
      "min_uq_seq_id": None,
      "thread_fbid": thread_fbid,
      "__relay_internal__pv__IGDEnableOffMsysChatThemesQErelayprovider": False,
      "__relay_internal__pv__IGDInitialMessagePageCountrelayprovider": PAGE_SIZE,
   }

   return build_graphql_request(
      session,
      THREAD_DETAIL,
      variables,
      referer=thread_url(thread_fbid),
      user_agent=user_agent,
   )


def build_thread_older_page_request(
   session: Session,
   thread_fbid: str,
   *,
   after: str | None = None,
   newer_than_message_id: str | None = None,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """One page of one thread, as a browser asks for it when the thread scrolls up.

   The variables are the ones :func:`build_thread_page_request` sends, in the order the browser
   sends them. Every captured browser request carried a 132-character ``after`` and a null
   ``newer_than_message_id``. A null ``after`` was replayed twice and answered. The engine sends
   a ``newer_than_message_id`` too, which a browser never did: with a live base the answer holds
   only newer messages, the newest twenty first, and ``after`` with the same base pages back to
   the base and ends there with ``has_next_page`` false.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/direct-thread-older-page-offmsys.md``.
   """

   return build_graphql_request(
      session,
      THREAD_OLDER_PAGE,
      _thread_page_variables(thread_fbid, after, newer_than_message_id),
      referer=thread_url(thread_fbid),
      user_agent=user_agent,
   )


def build_inbox_listing_request(
   session: Session,
   *,
   device_id: str,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """The inbox's first page of threads, asked for the way an inbox load asks for it.

   ``device_id`` is the ``clientId`` of ``IGDMqttWebDeviceID`` in the inbox document, which a
   browser mints fresh on every load. A replay with a random uuid4 the page never issued
   answered the same way, so a listener holds one for its lifetime as one open inbox would.

   The four provider flags are the values every captured inbox load sent for this account.
   ``IGDMaxUnreadMessagesCountrelayprovider`` is what makes each row carry its newest five
   messages, and so the newest message id a poll compares.

   Finding: ``direct-inbox-thread-list`` in the knowledge base.
   """

   variables = {
      "device_id_for_iris_subscription": device_id,
      "__relay_internal__pv__IGDIsProfessionalAccountGKrelayprovider": False,
      "__relay_internal__pv__IGDPinnedThreadsRenderEnabledGKrelayprovider": True,
      "__relay_internal__pv__IGDMaxUnreadMessagesCountrelayprovider": INBOX_ROW_MESSAGES,
      "__relay_internal__pv__IGDThreadListActionsEnabledGKrelayprovider": True,
   }

   return build_graphql_request(
      session,
      DIRECT_INBOX,
      variables,
      referer=BOOTSTRAP_URL,
      user_agent=user_agent,
   )


def is_a_thread_fbid(value: str) -> bool:
   """Whether ``value`` has the shape of a ``thread_fbid``, digits only, at most 30 of them.

   The two measured were 16 and 17 digits. The thread's 39-digit ``thread_id`` fails this,
   which is the mix-up it catches, since the unsend takes that id and the send does not. The
   ``thread_key`` passes, and nothing here can tell it apart by shape.
   """

   return _USER_ID.fullmatch(value) is not None


def offline_threading_id(now_ms: int, random_bits: int) -> str:
   """The client-generated identifier a text send carries, built as the browser builds it.

   ``IGDOfflineThreadingID.generateOfflineThreadingID`` writes the millisecond clock in binary,
   appends the low 22 bits of a random 32-bit number, keeps the last 63 binary digits and
   renders them in decimal. That is the clock shifted left by 22 with the random bits below it,
   cut to 63 bits. A thread read echoes it on the new message's node, which is what makes a
   reconciling read exact.
   """

   random_mask = (1 << _OFFLINE_THREADING_RANDOM_BITS) - 1
   combined = (now_ms << _OFFLINE_THREADING_RANDOM_BITS) | (random_bits & random_mask)

   return str(combined & ((1 << _OFFLINE_THREADING_ID_BITS) - 1))


def build_direct_text_send_request(
   session: Session,
   thread_fbid: str,
   text: str,
   threading_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """Send ``text`` into the thread whose ``thread_fbid`` is ``thread_fbid``.

   The fourteen variables in the order and with the values the browser's composer sent for a
   plain text message: no reply, no mention, no command, not forwarded. ``recipient_igids`` is
   what the composer sends in place of ``ig_thread_igid`` when no thread exists, and that shape
   is not built here because it was never sent. ``sampled`` and ``replied_to_client_context``
   are never set by the composer and leave as Relay's default null. The text travels wrapped as
   ``sensitive_string_value``.

   The referer is the thread page. The observed browser send came from the chat tab a profile
   page opens and carried the profile page, which the engine cannot name from a thread id, a
   departure recorded in ``docs/web-request-contract.md``.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/send-a-direct-text-message.md``.
   """

   variables: dict[str, Any] = {
      "ig_thread_igid": thread_fbid,
      "offline_threading_id": threading_id,
      "recipient_igids": None,
      "replied_to_client_context": None,
      "replied_to_item_id": None,
      "reply_to_message_id": None,
      "sampled": None,
      "text": {"sensitive_string_value": text},
      "mentions": [],
      "mentioned_user_ids": [],
      "commands": None,
      "forwarded_from_thread_id": None,
      "is_forwarded_from_own_message": None,
      "send_attribution": SEND_ATTRIBUTION,
   }

   return build_graphql_request(
      session,
      DIRECT_TEXT_SEND,
      variables,
      referer=thread_url(thread_fbid),
      user_agent=user_agent,
   )


def build_direct_unsend_request(
   session: Session,
   thread_fbid: str,
   thread_id: str,
   message_id: str,
   *,
   user_agent: str = DEFAULT_USER_AGENT,
) -> Request:
   """Unsend the viewer's message ``message_id`` from the thread whose long id is ``thread_id``.

   ``thread_id`` is the thread's 39-digit id, which the unsend takes under ``send_data``, and
   ``thread_fbid`` only names the referer, the thread page.

   Finding: ``skills/reverse-engineer/knowledge/endpoints/unsend-a-direct-message.md``.
   """

   return build_graphql_request(
      session,
      DIRECT_UNSEND,
      {"message_id": message_id, "send_data": {"thread_id": thread_id}},
      referer=thread_url(thread_fbid),
      user_agent=user_agent,
   )
