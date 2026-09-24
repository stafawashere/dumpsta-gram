"""Map the answer to a follow or an unfollow."""

from __future__ import annotations

from typing import Any

from dumpstagram._private.web.parse.common import _object_at, _required_flag, _required_string
from dumpstagram.errors import SchemaChanged

__all__ = [
   "FOLLOW_ANSWER_ROOT",
   "UNFOLLOW_ANSWER_ROOT",
   "parse_follow_answer",
]

FOLLOW_ANSWER_ROOT = "xdt_create_friendship"
"""The root field a follow answers under, carrying ``friendship_status`` and the account ``id``."""

UNFOLLOW_ANSWER_ROOT = "xdt_destroy_friendship"
"""The root field an unfollow answers under, the same shape as :data:`FOLLOW_ANSWER_ROOT`."""


def parse_follow_answer(payload: Any, root_field: str, user_id: str) -> bool:
   """The ``following`` a follow or an unfollow answered with, from ``data.<root_field>``.

   Four sends on 2026-09-23 each answered with ``friendship_status`` holding only ``following``,
   and the account's ``id`` echoed, 215 and 217 bytes, no ``errors`` array. An echoed id naming
   another account is a schema change rather than an answer about this one.
   """

   root = _object_at(payload, ("data", root_field))
   root_path = f"data.{root_field}"

   echoed_id = _required_string(root, "id", root_path)

   if echoed_id != user_id:
      raise SchemaChanged(
         f"{root_path}.id names another account than the one written to", path=f"{root_path}.id"
      )

   status = _object_at(payload, ("data", root_field, "friendship_status"))

   return _required_flag(status, "following", f"{root_path}.friendship_status")
