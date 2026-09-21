"""Gates for the shared loop thread and the exception seam across it.

The defects this layer produces are all invisible at the call site. An exception that changes
type crossing the seam breaks every `except dumpstagram.RateLimited` a caller wrote. A
cancellation that arrives as a `BaseException` walks past `except Exception`. A refcount that
never reaches zero keeps a thread alive for the lifetime of the process. A task that dies with
nobody awaiting it produces nothing at all unless the loop's handler writes it down.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from dumpstagram._core.loop_thread import (
   LOGGER_NAME,
   THREAD_NAME,
   _LoopThread,
   log_loop_exception,
   seam_note,
)
from dumpstagram.errors import OperationCancelled, RateLimited

SECRET = "71234567%3AabcdefGHIJKL%3A17"


def live_thread_names() -> set[str]:
   """Thread names the interpreter is actually carrying, rather than the bookkeeping.

   The refcount and the handle are both cleared by `release`, so a gate reading either of
   them stays green when the thread is never stopped. This reads the interpreter.
   """

   return {thread.name for thread in threading.enumerate() if thread.is_alive()}


@pytest.fixture
def loop_thread():
   thread = _LoopThread.acquire()

   try:
      yield thread
   finally:
      thread.release()


def test_runs_a_coroutine_and_returns_its_value(loop_thread: _LoopThread) -> None:
   async def work() -> int:
      await asyncio.sleep(0)

      return 7

   assert loop_thread.run(work(), operation="test.work") == 7


def test_an_exception_arrives_as_the_same_object(loop_thread: _LoopThread) -> None:
   """Catches a facade that wraps or re-types, which would give one engine two hierarchies."""

   raised = RateLimited("slow down", retry_after=12.0)

   async def work() -> None:
      raise raised

   with pytest.raises(RateLimited) as caught:
      loop_thread.run(work(), operation="test.rate_limited")

   assert caught.value is raised
   assert caught.value.retry_after == 12.0


def test_the_seam_note_is_attached(loop_thread: _LoopThread) -> None:
   """Catches a later refactor quietly wrapping exceptions again.

   The note is the only thing distinguishing a re-raised original from a wrapper, so asserting
   on it is what makes the gate above mean anything a year from now.
   """

   async def work() -> None:
      raise RateLimited("slow down")

   with pytest.raises(RateLimited) as caught:
      loop_thread.run(work(), operation="test.note")

   assert seam_note("test.note") in caught.value.__notes__


def test_cancellation_becomes_a_public_error(loop_thread: _LoopThread) -> None:
   """Catches a `BaseException` escaping a blocking call and skipping `except Exception`."""

   async def work() -> None:
      raise asyncio.CancelledError

   with pytest.raises(OperationCancelled):
      loop_thread.run(work(), operation="test.cancelled")


def test_cancellation_is_caught_by_except_exception(loop_thread: _LoopThread) -> None:
   """The reason the translation exists, asserted as behaviour rather than as a type name."""

   async def work() -> None:
      raise asyncio.CancelledError

   try:
      loop_thread.run(work(), operation="test.cancelled")
   except Exception as failure:
      assert isinstance(failure, OperationCancelled)
   else:
      pytest.fail("the cancellation did not reach the caller as an ordinary exception")


def test_the_thread_is_shared_and_refcounted() -> None:
   """Catches one loop thread per client, which is wasteful at ten accounts and hard to undo."""

   first = _LoopThread.acquire()
   second = _LoopThread.acquire()

   try:
      assert first is second
      assert first.references == 2
   finally:
      second.release()

      assert THREAD_NAME in live_thread_names()

      first.release()

   assert THREAD_NAME not in live_thread_names()


def test_a_third_release_is_a_defect() -> None:
   """Catches an unbalanced lifecycle being absorbed instead of reported."""

   thread = _LoopThread.acquire()
   thread.release()

   with pytest.raises(RuntimeError):
      thread.release()


def test_running_after_the_last_release_refuses() -> None:
   """Catches work being submitted to a loop that is already gone, which would hang."""

   thread = _LoopThread.acquire()
   thread.release()

   async def work() -> int:
      return 1

   with pytest.raises(RuntimeError):
      thread.run(work(), operation="test.after_close")


def test_an_unhandled_loop_error_is_logged(caplog: pytest.LogCaptureFixture) -> None:
   """Catches a task dying with nobody awaiting it and producing no record at all."""

   loop = asyncio.new_event_loop()

   try:
      failure = RateLimited("slow down")

      with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
         log_loop_exception(
            loop, {"message": "task exception was never retrieved", "exception": failure}
         )
   finally:
      loop.close()

   assert "task exception was never retrieved" in caplog.text


def test_the_logged_traceback_is_redacted(caplog: pytest.LogCaptureFixture) -> None:
   """Catches the loop handler handing an unredacted traceback to whatever the host attached."""

   loop = asyncio.new_event_loop()

   try:
      raise ValueError(f"request carried sessionid={SECRET}")
   except ValueError as failure:
      with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
         log_loop_exception(loop, {"message": "unhandled", "exception": failure})
   finally:
      loop.close()

   assert SECRET not in caplog.text
   assert "ValueError" in caplog.text


def test_the_same_traceback_carries_the_value_unredacted() -> None:
   """Positive control for the gate above."""

   import traceback

   try:
      raise ValueError(f"request carried sessionid={SECRET}")
   except ValueError as failure:
      formatted = "".join(traceback.format_exception(type(failure), failure, failure.__traceback__))

   assert SECRET in formatted


def test_asyncio_run_appears_nowhere_in_the_library() -> None:
   """Catches a facade building and tearing down a loop per call, which discards the pool."""

   package = Path(__file__).resolve().parents[1] / "dumpstagram"
   offenders = [
      path for path in sorted(package.rglob("*.py")) if "asyncio.run(" in path.read_text()
   ]

   assert offenders == []


def test_the_scan_finds_asyncio_run_when_it_is_present(tmp_path: Path) -> None:
   """Positive control. An absence check over zero matching files proves nothing."""

   sample = tmp_path / "sample.py"
   sample.write_text("asyncio.run(work())\n")

   assert "asyncio.run(" in sample.read_text()


def test_the_package_root_logger_has_only_a_null_handler() -> None:
   """Catches the library choosing output for its host, which here may be a Swift app."""

   logger = logging.getLogger(LOGGER_NAME)

   assert logger.level == logging.NOTSET
   assert [type(handler) for handler in logger.handlers] == [logging.NullHandler]


def test_importing_the_package_starts_no_thread() -> None:
   """Catches import-time side effects, of which a live thread is the worst kind."""

   probe = "import threading, dumpstagram; print(sorted(t.name for t in threading.enumerate()))"
   completed = subprocess.run(
      [sys.executable, "-c", probe],
      capture_output=True,
      text=True,
      check=True,
      cwd=Path(__file__).resolve().parents[1],
   )

   assert "dumpstagram-loop" not in completed.stdout
