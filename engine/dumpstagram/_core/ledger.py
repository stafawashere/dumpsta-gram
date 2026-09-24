"""The account's write record: when its writes departed, and whether its writes are stopped.

The pacer judges the write budget and the write stop against a record kept here. A client
built over a bare :class:`~dumpstagram.session.Session` keeps the record in memory, so it
lives and dies with the pacer as it always has. A client built from a session file keeps it
in a ledger file beside that file, so every process on the account reads and writes one
record, and a stop one of them saw is still there for the next.

The ledger file holds instants and a flag, never a credential, an id or any content. It is
JSON with a ``schema_version``, replaced whole by a rename, and every read and write happens
under an exclusive ``flock`` on a separate lock file, which is never renamed over and so is
the one inode every process locks. A ledger that cannot be read, or that a newer engine
wrote, refuses every write rather than being reset, because a reset would forget a stop.

Instants in a memory ledger are on the pacer's monotonic clock. Instants in a ledger file are
wall clock seconds, because a monotonic reading means nothing to another process. A wall
clock set backwards keeps old departures counted for longer, and one set forwards lets them
leave the window early.

POSIX only, per ADR-0010: ``fcntl`` does not exist on Windows.
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import math
import os
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

__all__ = [
   "LEDGER_SCHEMA_VERSION",
   "FileLedger",
   "LedgerUnreadable",
   "MemoryLedger",
   "WriteLedger",
   "WriteRecord",
   "ledger_path_for",
]

LEDGER_SCHEMA_VERSION = 1

LEDGER_SUFFIX = ".ledger"


class LedgerUnreadable(Exception):
   """The ledger file is not one this engine wrote, or a newer engine wrote it."""


@dataclass
class WriteRecord:
   """The instants the account's writes departed at, oldest first, and the stop."""

   departures: list[float] = field(default_factory=list)
   writes_stopped: bool = False
   stopped_at: float | None = None

   def forget_before(self, instant: float) -> None:
      """Drop every departure at or before ``instant``, which the window no longer counts."""

      self.departures = [departed_at for departed_at in self.departures if departed_at > instant]

   def copy(self) -> WriteRecord:
      return WriteRecord(list(self.departures), self.writes_stopped, self.stopped_at)


class WriteLedger(Protocol):
   """Where one account's write record lives."""

   async def update[T](self, change: Callable[[WriteRecord, float], T]) -> T:
      """Apply ``change`` to the current record at the ledger's own instant, and keep it.

      ``change`` raising leaves the record as it was.
      """
      ...


class MemoryLedger:
   """The record held by one pacer, on the pacer's clock, gone when the process ends."""

   def __init__(self, clock: Callable[[], float]) -> None:
      self._clock = clock
      self._record = WriteRecord()

   async def update[T](self, change: Callable[[WriteRecord, float], T]) -> T:
      working = self._record.copy()
      result = change(working, self._clock())
      self._record = working

      return result


class FileLedger:
   """The record kept in a file every process on the account shares.

   Sharing contract: task safe and thread safe within a process, and safe across processes,
   because every access holds the file lock from the read to the rename. Not loop bound.
   """

   def __init__(self, path: str | os.PathLike[str], *, clock: Callable[[], float] = time.time):
      self.path = Path(path)
      self.lock_path = self.path.with_name(self.path.name + ".lock")
      self._clock = clock

   async def update[T](self, change: Callable[[WriteRecord, float], T]) -> T:
      """The awaitable form of :meth:`update_now`, run on a worker thread.

      Cancelling the await does not stop the thread. A change already applied stays in the
      file, which for a departure means a budget slot spent on a write that never left.
      """

      return await asyncio.to_thread(self.update_now, change)

   def update_now[T](self, change: Callable[[WriteRecord, float], T]) -> T:
      """Read the record, apply ``change``, and write it back, all under the file lock."""

      with self._locked():
         record = self._read()
         unchanged = record.copy()

         result = change(record, self._clock())

         if record != unchanged:
            self._write(record)

         return result

   def read_now(self) -> WriteRecord:
      """The current record, read under the file lock, changing nothing."""

      with self._locked():
         return self._read()

   @contextmanager
   def _locked(self) -> Iterator[None]:
      self.path.parent.mkdir(parents=True, exist_ok=True)
      descriptor = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o600)

      try:
         fcntl.flock(descriptor, fcntl.LOCK_EX)
         yield
      finally:
         os.close(descriptor)

   def _read(self) -> WriteRecord:
      try:
         raw = self.path.read_bytes()
      except FileNotFoundError:
         return WriteRecord()

      try:
         payload = json.loads(raw)
      except (UnicodeDecodeError, json.JSONDecodeError) as parse_failure:
         raise LedgerUnreadable(f"the pacing ledger at {self.path} is not JSON") from parse_failure

      return record_from(payload, self.path)

   def _write(self, record: WriteRecord) -> None:
      serialised = json.dumps(
         {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "departures": record.departures,
            "writes_stopped": record.writes_stopped,
            "stopped_at": record.stopped_at,
         },
         indent=2,
         sort_keys=True,
      )

      handle, temporary_name = tempfile.mkstemp(
         dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp"
      )

      try:
         with os.fdopen(handle, "w", encoding="utf-8") as temporary_file:
            temporary_file.write(serialised)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

         os.replace(temporary_name, self.path)
      except BaseException:
         Path(temporary_name).unlink(missing_ok=True)
         raise


def ledger_path_for(session_path: str | os.PathLike[str]) -> Path:
   """The ledger file beside a session file: ``session.json`` keeps ``session.json.ledger``."""

   session_file = Path(session_path)

   return session_file.with_name(session_file.name + LEDGER_SUFFIX)


def record_from(payload: Any, path: Path) -> WriteRecord:
   """A record read field by field, refusing anything this engine would not have written."""

   if not isinstance(payload, dict):
      raise LedgerUnreadable(f"the pacing ledger at {path} is not a JSON object")

   version = payload.get("schema_version")
   is_this_version = type(version) is int and version == LEDGER_SCHEMA_VERSION

   if not is_this_version:
      raise LedgerUnreadable(
         f"the pacing ledger at {path} has schema_version {version!r}, and this engine "
         f"reads only {LEDGER_SCHEMA_VERSION}"
      )

   departures = payload.get("departures")
   writes_stopped = payload.get("writes_stopped")
   stopped_at = payload.get("stopped_at")

   departures_are_instants = isinstance(departures, list) and all(
      is_instant(departed_at) for departed_at in departures
   )
   stop_is_a_flag = type(writes_stopped) is bool
   stopped_at_is_an_instant = stopped_at is None or is_instant(stopped_at)

   is_well_formed = departures_are_instants and stop_is_a_flag and stopped_at_is_an_instant

   if not is_well_formed:
      raise LedgerUnreadable(f"the pacing ledger at {path} does not hold a write record")

   assert isinstance(departures, list)

   return WriteRecord(
      departures=sorted(float(departed_at) for departed_at in departures),
      writes_stopped=bool(writes_stopped),
      stopped_at=None if stopped_at is None else float(stopped_at),
   )


def is_instant(value: object) -> bool:
   is_flag = isinstance(value, bool)
   is_number = isinstance(value, int | float) and not is_flag

   if not is_number:
      return False

   assert isinstance(value, int | float)

   return math.isfinite(value)
