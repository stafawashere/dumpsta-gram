"""The rotation canary's plan and report, in both output forms.

The report's types live behind the package's private boundary, so they are described here by
what the renderer reads of them rather than imported.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

__all__ = [
   "DoctorPlanView",
   "DoctorReportView",
   "OperationCheckView",
   "describe_plan",
   "describe_report",
   "render_dry_run",
   "render_plan_line",
   "render_report",
]


class DoctorPlanView(Protocol):
   @property
   def documents(self) -> int: ...

   @property
   def reads(self) -> Sequence[str]: ...

   @property
   def companions(self) -> Sequence[str]: ...

   @property
   def writes(self) -> Sequence[str]: ...

   @property
   def bundle_limit(self) -> int: ...

   @property
   def paced_requests_at_most(self) -> int: ...


class OperationCheckView(Protocol):
   @property
   def operation(self) -> str: ...

   @property
   def role(self) -> str: ...

   @property
   def stored_doc_id(self) -> str: ...

   @property
   def compiled_doc_ids(self) -> Sequence[str]: ...

   @property
   def artifact_seen(self) -> bool: ...

   @property
   def bundle(self) -> str: ...

   @property
   def replay(self) -> str: ...

   @property
   def replay_error(self) -> str | None: ...

   @property
   def replay_code(self) -> str | None: ...

   @property
   def replay_note(self) -> str | None: ...


class DoctorReportView(Protocol):
   @property
   def checks(self) -> Sequence[OperationCheckView]: ...

   @property
   def documents_loaded(self) -> int: ...

   @property
   def bundles_named(self) -> int: ...

   @property
   def bundles_fetched(self) -> int: ...

   @property
   def bundles_failed(self) -> int: ...

   @property
   def reads_sent(self) -> int: ...

   @property
   def drifted(self) -> Sequence[OperationCheckView]: ...

   @property
   def missing(self) -> Sequence[OperationCheckView]: ...

   @property
   def failed_replays(self) -> Sequence[OperationCheckView]: ...


def describe_plan(plan: DoctorPlanView) -> dict[str, Any]:
   return {
      "documents": plan.documents,
      "reads": list(plan.reads),
      "paced_requests_at_most": plan.paced_requests_at_most,
      "bundle_limit": plan.bundle_limit,
      "companions_checked_by_artifact": list(plan.companions),
      "writes_checked_by_artifact": list(plan.writes),
   }


def describe_check(check: OperationCheckView) -> dict[str, Any]:
   return {
      "operation": check.operation,
      "role": str(check.role),
      "bundle": str(check.bundle),
      "stored_doc_id": check.stored_doc_id,
      "compiled_doc_ids": list(check.compiled_doc_ids),
      "artifact_seen": check.artifact_seen,
      "replay": str(check.replay),
      "replay_error": check.replay_error,
      "replay_code": check.replay_code,
      "replay_note": check.replay_note,
   }


def describe_report(report: DoctorReportView) -> dict[str, Any]:
   return {
      "summary": {
         "documents_loaded": report.documents_loaded,
         "bundles_named": report.bundles_named,
         "bundles_fetched": report.bundles_fetched,
         "bundles_failed": report.bundles_failed,
         "reads_sent": report.reads_sent,
         "drift": len(report.drifted),
         "missing": len(report.missing),
         "replay_failed": len(report.failed_replays),
      },
      "operations": [describe_check(check) for check in report.checks],
   }


def render_plan_line(plan: DoctorPlanView) -> str:
   return (
      f"doctor: sending {plan.documents} documents and at most {len(plan.reads)} reads, paced, "
      f"then at most {plan.bundle_limit} cookieless bundle fetches. "
      f"{len(plan.writes)} writes and {len(plan.companions)} companions are checked by artifact "
      "only and never sent"
   )


def render_dry_run(plan: DoctorPlanView) -> str:
   lines = [
      "dry run, nothing sent. With --live the doctor would send:",
      f"  {plan.documents} page documents, the inbox and home, paced",
      f"  at most {len(plan.reads)} reads, one replay each, paced:",
      *(f"    {name}" for name in plan.reads),
      f"  at most {plan.bundle_limit} bundle fetches to the static host, cookieless, no pacer slot",
      f"and compare by artifact only, never sending them, {len(plan.writes)} writes:",
      *(f"    {name}" for name in plan.writes),
      f"and {len(plan.companions)} companions:",
      *(f"    {name}" for name in plan.companions),
      f"paced requests at most: {plan.paced_requests_at_most}",
   ]

   return "\n".join(lines)


def render_check(check: OperationCheckView) -> str:
   compiled = ",".join(check.compiled_doc_ids) or "-"
   line = (
      f"{check.bundle!s:<7}  {check.replay!s:<13}  {check.role!s:<9}  {check.operation}  "
      f"stored {check.stored_doc_id}  compiled {compiled}"
   )

   missing_with_artifact = str(check.bundle) == "missing" and check.artifact_seen

   if missing_with_artifact:
      line += "  artifact present, no id module read"

   if check.replay_error:
      line += f"  {check.replay_error}"

   if check.replay_code:
      line += f" code {check.replay_code}"

   if check.replay_note:
      line += f"  {check.replay_note}"

   return line


def render_report(report: DoctorReportView) -> str:
   summary = describe_report(report)["summary"]
   lines = [render_check(check) for check in report.checks]
   lines.append(
      f"documents: {summary['documents_loaded']}  bundles fetched: {summary['bundles_fetched']} "
      f"of {summary['bundles_named']} named, {summary['bundles_failed']} failed  "
      f"reads sent: {summary['reads_sent']}  drift: {summary['drift']}  "
      f"missing: {summary['missing']}  replay failed: {summary['replay_failed']}"
   )

   return "\n".join(lines)
