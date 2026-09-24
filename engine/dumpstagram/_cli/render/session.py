"""The session summary, which reports what `Session.__repr__` reports and nothing more."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from dumpstagram.session import Session

__all__ = [
   "describe_session",
   "render_session",
]


def describe_session(session: Session, path: Path) -> dict[str, Any]:
   """The session summary both output forms are built from."""

   return {
      "session_path": str(path),
      "ds_user_id": session.ds_user_id,
      "app_id": session.app_id,
      "bootstrapped": session.fb_dtsg is not None and session.lsd is not None,
      "checkpoint_active": session.checkpoint_active,
      "proxied": session.proxy is not None,
      "requests_spent": 0,
   }


def render_session(summary: Mapping[str, Any]) -> str:
   """The human form of a session summary, one field per line."""

   return "\n".join(f"{key}: {summary[key]}" for key in summary)
