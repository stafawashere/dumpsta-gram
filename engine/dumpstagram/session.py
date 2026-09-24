"""Per-account session state and its on-disk form.

A `Session` is constructed by the caller from cookie material copied out of a browser, per
ADR-0008. The library adopts a session, it does not create one, so nothing here renews or
refreshes anything.

The persisted form is a compatibility surface in its own right. It is JSON, it carries an
explicit `schema_version`, and the mapping between fields and keys is written out by hand so a
later rename inside this module cannot invalidate a file someone already saved.
"""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from dumpstagram._core.ledger import FileLedger, LedgerUnreadable, WriteRecord, ledger_path_for
from dumpstagram.errors import AuthenticationFailed, SchemaChanged

__all__ = [
   "SCHEMA_VERSION",
   "ProxyConfig",
   "Session",
   "SpinParameters",
   "clear_write_stop",
]

SCHEMA_VERSION = 1
"""The version written into every session file, and the only one this code will load."""

_REDACTED = "<redacted>"


@dataclass(frozen=True)
class SpinParameters:
   """The `__spin_*` family scraped from an authenticated page.

   Ablation showed the upstream ignores all of them. They are sent anyway, because a request
   missing the fields a browser sends is a fingerprint.
   """

   revision: str | None = None
   branch: str | None = None
   timestamp: str | None = None


@dataclass(frozen=True)
class ProxyConfig:
   """Proxy routing for this account.

   The URL may carry a username and password, so the whole configuration is treated as a
   credential and never appears in a representation or a log.
   """

   url: str
   verify_tls: bool = True

   def __repr__(self) -> str:
      return f"ProxyConfig(url={_REDACTED!r}, verify_tls={self.verify_tls!r})"


@dataclass
class Session:
   """Everything that identifies one account to Instagram.

   Instance-scoped per ADR-0004. There is no module-level session and no hidden login state.

   `sessionid` alone is a full account takeover token with no second factor, so it, the other
   credential material, and the proxy configuration are kept out of `__repr__` and out of every
   log line.

   `fr` is not a cookie. It is the value a browser keeps in `localStorage` under that key and
   hands to the page-load cookie sync, `None` when the browser holds none.

   `actor_id` is the account's Facebook-side id, read from a bootstrapped page, and `None`
   until one has been read. It is a different number from `ds_user_id` and never stands in
   for it.
   """

   sessionid: str = field(repr=False)
   ds_user_id: str = ""
   csrftoken: str = field(default="", repr=False)
   extra_cookies: Mapping[str, str] = field(default_factory=dict, repr=False)
   fb_dtsg: str | None = field(default=None, repr=False)
   lsd: str | None = field(default=None, repr=False)
   app_id: str | None = None
   spin: SpinParameters | None = None
   hsi: str | None = None
   haste_session: str | None = None
   bloks_version_id: str | None = None
   fr: str | None = field(default=None, repr=False)
   bootstrapped_at: datetime | None = None
   proxy: ProxyConfig | None = field(default=None, repr=False)
   checkpoint_active: bool = False
   actor_id: str | None = None

   def __post_init__(self) -> None:
      required_cookies = {
         "sessionid": self.sessionid,
         "ds_user_id": self.ds_user_id,
         "csrftoken": self.csrftoken,
      }

      missing = sorted(name for name, value in required_cookies.items() if not value)

      if missing:
         raise AuthenticationFailed(
            f"session is missing required cookie material: {', '.join(missing)}"
         )

      self.extra_cookies = dict(self.extra_cookies)

   def __repr__(self) -> str:
      has_tokens = self.fb_dtsg is not None and self.lsd is not None

      return (
         f"Session(ds_user_id={self.ds_user_id!r}, app_id={self.app_id!r}, "
         f"bootstrapped={has_tokens!r}, checkpoint_active={self.checkpoint_active!r}, "
         f"proxied={self.proxy is not None!r})"
      )

   def to_dict(self) -> dict[str, Any]:
      """The serialised form, mapped key by key rather than derived from the field layout."""
      spin_payload = None

      if self.spin is not None:
         spin_payload = {
            "revision": self.spin.revision,
            "branch": self.spin.branch,
            "timestamp": self.spin.timestamp,
         }

      proxy_payload = None

      if self.proxy is not None:
         proxy_payload = {"url": self.proxy.url, "verify_tls": self.proxy.verify_tls}

      bootstrapped_at = None

      if self.bootstrapped_at is not None:
         bootstrapped_at = self.bootstrapped_at.isoformat()

      return {
         "schema_version": SCHEMA_VERSION,
         "sessionid": self.sessionid,
         "ds_user_id": self.ds_user_id,
         "csrftoken": self.csrftoken,
         "extra_cookies": dict(self.extra_cookies),
         "fb_dtsg": self.fb_dtsg,
         "lsd": self.lsd,
         "app_id": self.app_id,
         "spin": spin_payload,
         "hsi": self.hsi,
         "haste_session": self.haste_session,
         "bloks_version_id": self.bloks_version_id,
         "fr": self.fr,
         "actor_id": self.actor_id,
         "bootstrapped_at": bootstrapped_at,
         "proxy": proxy_payload,
         "checkpoint_active": self.checkpoint_active,
      }

   @classmethod
   def from_dict(cls, payload: Mapping[str, Any]) -> Session:
      """Rebuild a session from its serialised form.

      Unknown keys are ignored. An unrecognised `schema_version` is refused rather than
      partially understood, because a half-read session still makes authenticated requests.
      """
      version = payload.get("schema_version")

      if version != SCHEMA_VERSION:
         raise SchemaChanged(
            f"session file schema_version {version!r} is not supported, expected "
            f"{SCHEMA_VERSION!r}",
            path="schema_version",
         )

      spin_payload = payload.get("spin")
      spin = None

      if spin_payload is not None:
         spin = SpinParameters(
            revision=spin_payload.get("revision"),
            branch=spin_payload.get("branch"),
            timestamp=spin_payload.get("timestamp"),
         )

      proxy_payload = payload.get("proxy")
      proxy = None

      if proxy_payload is not None:
         proxy_url = proxy_payload.get("url")

         if not proxy_url:
            raise SchemaChanged("session file carries a proxy without a url", path="proxy.url")

         proxy = ProxyConfig(url=proxy_url, verify_tls=proxy_payload.get("verify_tls", True))

      bootstrapped_raw = payload.get("bootstrapped_at")
      bootstrapped_at = None

      if bootstrapped_raw is not None:
         try:
            bootstrapped_at = datetime.fromisoformat(bootstrapped_raw)
         except (TypeError, ValueError) as parse_failure:
            raise SchemaChanged(
               "session file carries an unparsable bootstrap timestamp",
               path="bootstrapped_at",
            ) from parse_failure

      return cls(
         sessionid=payload.get("sessionid", ""),
         ds_user_id=payload.get("ds_user_id", ""),
         csrftoken=payload.get("csrftoken", ""),
         extra_cookies=dict(payload.get("extra_cookies") or {}),
         fb_dtsg=payload.get("fb_dtsg"),
         lsd=payload.get("lsd"),
         app_id=payload.get("app_id"),
         spin=spin,
         hsi=payload.get("hsi"),
         haste_session=payload.get("haste_session"),
         bloks_version_id=payload.get("bloks_version_id"),
         fr=payload.get("fr"),
         actor_id=payload.get("actor_id"),
         bootstrapped_at=bootstrapped_at,
         proxy=proxy,
         checkpoint_active=bool(payload.get("checkpoint_active", False)),
      )

   def save(self, path: str | os.PathLike[str]) -> None:
      """Write the session to `path`, owner-readable only, replacing any previous file.

      The temporary file is created in the destination directory with owner-only permissions
      and renamed over the target, so an interrupted write cannot leave a truncated session for
      the next process to half-accept.
      """
      destination = Path(path)
      destination.parent.mkdir(parents=True, exist_ok=True)

      serialised = json.dumps(self.to_dict(), indent=2, sort_keys=True)

      handle, temporary_name = tempfile.mkstemp(
         dir=destination.parent, prefix=f".{destination.name}.", suffix=".tmp"
      )

      try:
         with os.fdopen(handle, "w", encoding="utf-8") as temporary_file:
            temporary_file.write(serialised)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

         os.replace(temporary_name, destination)
      except BaseException:
         Path(temporary_name).unlink(missing_ok=True)
         raise

   @classmethod
   def load(cls, path: str | os.PathLike[str]) -> Session:
      """Read a session written by :meth:`save`.

      JSON only. Nothing here ever reaches for `pickle`, `marshal`, `eval`, `exec`, or a
      YAML loader, because the file holds a credential and a loader that can construct objects
      turns that file into code execution.
      """
      source = Path(path)

      try:
         payload = json.loads(source.read_text(encoding="utf-8"))
      except json.JSONDecodeError as parse_failure:
         raise SchemaChanged(f"session file at {source} is not valid JSON") from parse_failure

      if not isinstance(payload, dict):
         raise SchemaChanged(f"session file at {source} is not a JSON object")

      return cls.from_dict(payload)


def clear_write_stop(path: str | os.PathLike[str]) -> bool:
   """Lift the write stop kept beside the session file at ``path``, and say whether one was set.

   A client built with ``from_session_file(path)`` keeps the account's write budget and write
   stop in ``<path>.ledger``. The stop is set by a write rejection nothing recorded explains,
   the likeliest form of an action block, and it never lapses on its own, so lifting it is a
   person's decision after looking at the account, never a program's reflex. The hour's write
   departures are kept, so the budget still counts them.

   Blocks for as long as another process holds the ledger's lock, which is a few milliseconds.
   Raises :class:`~dumpstagram.errors.SchemaChanged` and changes nothing when the ledger cannot
   be read. Deleting that file lifts the stop and also forgets the hour's writes.
   """

   ledger = FileLedger(ledger_path_for(path))

   try:
      return ledger.update_now(_lift_stop)
   except LedgerUnreadable as unreadable:
      raise SchemaChanged(
         f"{unreadable}. Nothing was cleared. Deleting that file lifts the stop and also "
         "forgets the hour's writes"
      ) from unreadable


def _lift_stop(record: WriteRecord, now: float) -> bool:
   was_stopped = record.writes_stopped
   record.writes_stopped = False
   record.stopped_at = None

   return was_stopped
