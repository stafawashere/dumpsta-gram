"""Gates on the session and on its on-disk format.

The session file is a compatibility surface and a credential store at the same time, so these
cover three separate failure classes: construction accepting material it cannot authenticate
with, a saved file that a later version reads only half of, and a credential escaping into a
representation.
"""

import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dumpstagram.errors import AuthenticationFailed, SchemaChanged
from dumpstagram.session import SCHEMA_VERSION, ProxyConfig, Session, SpinParameters

SESSIONID = "sessionid-secret-value"
CSRFTOKEN = "csrftoken-secret-value"
FB_DTSG = "fb-dtsg-secret-value"
LSD = "lsd-secret-value"
PROXY_URL = "http://proxy-user:proxy-password@proxy.example:8080"


def full_session() -> Session:
   return Session(
      sessionid=SESSIONID,
      ds_user_id="1234567890",
      csrftoken=CSRFTOKEN,
      extra_cookies={"mid": "mid-value", "datr": "datr-value"},
      fb_dtsg=FB_DTSG,
      lsd=LSD,
      app_id="936619743392459",
      spin=SpinParameters(revision="1024", branch="main", timestamp="1758000000"),
      hsi="7551000000000000000",
      haste_session="20128.HYP:instagram_web_pkg.2.1...0",
      bootstrapped_at=datetime(2026, 9, 21, 12, 30, tzinfo=UTC),
      proxy=ProxyConfig(url=PROXY_URL, verify_tls=False),
      checkpoint_active=True,
   )


@pytest.mark.parametrize("missing_field", ["sessionid", "ds_user_id", "csrftoken"])
def test_construction_refuses_missing_required_cookies(missing_field: str) -> None:
   """A session built without one of the three required cookies cannot authenticate at all."""
   arguments = {"sessionid": SESSIONID, "ds_user_id": "1234567890", "csrftoken": CSRFTOKEN}
   arguments[missing_field] = ""

   with pytest.raises(AuthenticationFailed) as raised:
      Session(**arguments)

   assert missing_field in str(raised.value)


def test_repr_carries_no_credential_material() -> None:
   """A session in a traceback or a log line would otherwise publish a takeover token."""
   session = full_session()
   representation = repr(session)

   serialised = json.dumps(session.to_dict())
   control_values = [SESSIONID, CSRFTOKEN, FB_DTSG, LSD, PROXY_URL]

   for secret in control_values:
      assert secret in serialised, "positive control: the scan must find the live values"
      assert secret not in representation


def test_proxy_repr_carries_no_credential_material() -> None:
   """A proxy URL embeds a username and password, so it is a credential of its own."""
   proxy = ProxyConfig(url=PROXY_URL)

   assert PROXY_URL not in repr(proxy)


def test_round_trip_through_disk_preserves_every_field(tmp_path: Path) -> None:
   """The Phase 1 stop condition is a reload, so a field lost in the mapping loses the account."""
   original = full_session()
   destination = tmp_path / "session.json"

   original.save(destination)
   reloaded = Session.load(destination)

   assert reloaded == original


def test_saved_file_is_owner_only(tmp_path: Path) -> None:
   """A world-readable session file hands a full account takeover token to any local process."""
   destination = tmp_path / "session.json"
   full_session().save(destination)

   mode = stat.S_IMODE(destination.stat().st_mode)

   assert mode & (stat.S_IRWXG | stat.S_IRWXO) == 0


def test_save_leaves_no_temporary_file_behind(tmp_path: Path) -> None:
   """A stray temporary file is an unredacted credential copy nothing later cleans up."""
   destination = tmp_path / "session.json"
   full_session().save(destination)

   assert [entry.name for entry in tmp_path.iterdir()] == ["session.json"]


def test_a_failed_save_leaves_the_previous_file_intact(tmp_path: Path, monkeypatch) -> None:
   """An interrupted write must not truncate the session the next process reloads."""
   destination = tmp_path / "session.json"
   session = full_session()
   session.save(destination)

   original_bytes = destination.read_bytes()

   def failing_replace(source: str, target: str) -> None:
      raise OSError("interrupted")

   monkeypatch.setattr(os, "replace", failing_replace)

   with pytest.raises(OSError):
      session.save(destination)

   assert destination.read_bytes() == original_bytes
   assert [entry.name for entry in tmp_path.iterdir()] == ["session.json"]


def test_load_refuses_an_unrecognised_schema_version(tmp_path: Path) -> None:
   """Loading a partly understood session means making authenticated requests with it."""
   destination = tmp_path / "session.json"
   payload = full_session().to_dict()
   payload["schema_version"] = SCHEMA_VERSION + 1
   destination.write_text(json.dumps(payload), encoding="utf-8")

   with pytest.raises(SchemaChanged):
      Session.load(destination)


def test_load_refuses_a_file_with_no_schema_version(tmp_path: Path) -> None:
   """An unversioned file is a guess about what wrote it."""
   destination = tmp_path / "session.json"
   payload = full_session().to_dict()
   del payload["schema_version"]
   destination.write_text(json.dumps(payload), encoding="utf-8")

   with pytest.raises(SchemaChanged):
      Session.load(destination)


def test_load_ignores_unknown_keys(tmp_path: Path) -> None:
   """A file written by a later version must not be rejected for carrying a field we ignore."""
   destination = tmp_path / "session.json"
   payload = full_session().to_dict()
   payload["fields_from_a_later_version"] = {"anything": True}
   destination.write_text(json.dumps(payload), encoding="utf-8")

   assert Session.load(destination) == full_session()


def test_saved_format_keys_are_the_documented_set(tmp_path: Path) -> None:
   """The serialised layout is the compatibility surface, not the field layout above it."""
   destination = tmp_path / "session.json"
   full_session().save(destination)

   payload = json.loads(destination.read_text(encoding="utf-8"))

   assert set(payload) == {
      "schema_version",
      "sessionid",
      "ds_user_id",
      "csrftoken",
      "extra_cookies",
      "fb_dtsg",
      "lsd",
      "app_id",
      "spin",
      "hsi",
      "haste_session",
      "bootstrapped_at",
      "proxy",
      "checkpoint_active",
   }


def test_extra_cookies_default_is_not_shared_between_sessions() -> None:
   """A shared mutable default leaks one account's cookie jar into another's."""
   first = Session(sessionid=SESSIONID, ds_user_id="1", csrftoken=CSRFTOKEN)
   second = Session(sessionid=SESSIONID, ds_user_id="2", csrftoken=CSRFTOKEN)

   first.extra_cookies["mid"] = "mid-value"

   assert second.extra_cookies == {}


def test_extra_cookies_are_copied_from_the_caller() -> None:
   """A caller mutating the mapping it passed in must not silently change the session."""
   caller_owned = {"mid": "mid-value"}
   session = Session(
      sessionid=SESSIONID, ds_user_id="1", csrftoken=CSRFTOKEN, extra_cookies=caller_owned
   )

   caller_owned["datr"] = "datr-value"

   assert session.extra_cookies == {"mid": "mid-value"}
