"""The doctor command, the rotation canary run on demand.

It is the one command that reaches something no public method offers, because what it checks is
the private query registry, which ADR-0007 keeps off the public surface. It reaches it through
the assembly in ``dumpstagram.aio`` and never imports ``_core`` or ``_private`` itself.

A dry run is the default and sends nothing, not even a session read. ``--live`` states what it
is about to send on stderr before the first request leaves.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol, TextIO

from dumpstagram._cli.commands.common import (
   Subcommands,
   add_request_options,
   emit,
   resolve_session_path,
)
from dumpstagram._cli.exits import EXIT_DRIFT, EXIT_OK, EXIT_REPLAY_FAILED
from dumpstagram._cli.render.doctor import (
   DoctorPlanView,
   DoctorReportView,
   describe_plan,
   describe_report,
   render_dry_run,
   render_plan_line,
   render_report,
)
from dumpstagram.aio import AsyncClient, _rotation_doctor, _rotation_doctor_plan
from dumpstagram.session import Session

__all__ = [
   "DoctorFactory",
   "OpenedDoctor",
   "PlanFactory",
   "add_doctor_parser",
   "exit_code_for_report",
   "open_doctor",
   "plan_only",
   "run_doctor",
]

DEFAULT_BUNDLE_LIMIT = _rotation_doctor_plan().bundle_limit


class OpenedDoctor(Protocol):
   @property
   def session(self) -> Session: ...

   def plan(self) -> DoctorPlanView: ...

   async def run(self) -> DoctorReportView: ...

   async def aclose(self) -> None: ...


class DoctorFactory(Protocol):
   def __call__(self, path: Path, *, user_agent: str | None, bundle_limit: int) -> OpenedDoctor: ...


class PlanFactory(Protocol):
   def __call__(self, bundle_limit: int) -> DoctorPlanView: ...


class _ClientDoctor:
   """The canary together with the client it runs over, closed together."""

   def __init__(self, client: AsyncClient, bundle_limit: int) -> None:
      self._client = client
      self._doctor = _rotation_doctor(client, bundle_limit=bundle_limit)

   @property
   def session(self) -> Session:
      return self._client.session

   def plan(self) -> DoctorPlanView:
      return self._doctor.plan()

   async def run(self) -> DoctorReportView:
      return await self._doctor.run()

   async def aclose(self) -> None:
      try:
         await self._doctor.aclose()
      finally:
         await self._client.aclose()


def open_doctor(path: Path, *, user_agent: str | None, bundle_limit: int) -> OpenedDoctor:
   return _ClientDoctor(AsyncClient.from_session_file(path, user_agent=user_agent), bundle_limit)


def plan_only(bundle_limit: int) -> DoctorPlanView:
   return _rotation_doctor_plan(bundle_limit)


def exit_code_for_report(report: DoctorReportView) -> int:
   if report.drifted:
      return EXIT_DRIFT

   if report.failed_replays:
      return EXIT_REPLAY_FAILED

   return EXIT_OK


def run_doctor(
   arguments: argparse.Namespace,
   environment: Mapping[str, str],
   stdout: TextIO,
   stderr: TextIO,
   doctor_factory: DoctorFactory,
   plan_factory: PlanFactory,
) -> int:
   if not arguments.live:
      plan = plan_factory(arguments.bundle_limit)
      payload = {"command": "doctor", "live": False, "plan": describe_plan(plan)}

      emit(payload, render_dry_run(plan), as_json=arguments.json, stream=stdout)

      return EXIT_OK

   path = resolve_session_path(arguments.session, environment)
   opened = doctor_factory(
      path, user_agent=arguments.user_agent, bundle_limit=arguments.bundle_limit
   )
   plan = opened.plan()
   token_before_the_run = opened.session.fb_dtsg

   print(render_plan_line(plan), file=stderr, flush=True)

   async def run_and_close() -> DoctorReportView:
      try:
         return await opened.run()
      finally:
         await opened.aclose()

   with asyncio.Runner() as runner:
      report = runner.run(run_and_close())

   harvested_a_new_token = opened.session.fb_dtsg != token_before_the_run
   may_write_back = not arguments.no_session_writeback

   if harvested_a_new_token and may_write_back:
      opened.session.save(path)

   payload = {
      "command": "doctor",
      "live": True,
      "plan": describe_plan(plan),
      **describe_report(report),
   }

   emit(payload, render_report(report), as_json=arguments.json, stream=stdout)

   return exit_code_for_report(report)


def bundle_limit(value: str) -> int:
   limit = int(value)

   if limit < 1:
      raise argparse.ArgumentTypeError("a bundle limit is at least 1")

   return limit


def add_doctor_parser(commands: Subcommands) -> None:
   doctor = commands.add_parser(
      "doctor",
      help="check every stored doc_id against the site's compiled bundles, a dry run by default",
      description=(
         "Loads the inbox and home documents, reads the bundles they name for the doc_id each "
         "operation compiles to, and replays each read once. Writes and companions are compared "
         "with the bundle and never sent. Without --live nothing is sent and the plan is "
         "printed. Exits 12 on any drift, 13 when no id drifted but a replay failed."
      ),
   )
   doctor.add_argument(
      "--live",
      action="store_true",
      help="send the requests the plan lists, after printing it on stderr",
   )
   doctor.add_argument(
      "--bundle-limit",
      type=bundle_limit,
      default=DEFAULT_BUNDLE_LIMIT,
      metavar="N",
      help=f"fetch at most N bundles, default {DEFAULT_BUNDLE_LIMIT}",
   )
   add_request_options(doctor)
