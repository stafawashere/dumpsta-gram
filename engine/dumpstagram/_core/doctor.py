"""The rotation canary: does every ``doc_id`` the engine stores still match what the site compiles.

A rotated ``doc_id`` is the failure this library is least able to see. The old id often keeps
answering for a while, and when it stops it answers with an error envelope under HTTP 200. So
the canary asks the site itself. It loads the two pages the engine already loads, the inbox the
bootstrap reads and home, collects every bundle those documents name, and reads each bundle for
the operation to ``doc_id`` pairs it compiles, stopping as soon as every stored operation has
been found. Then it replays each read once through the capability's own builder and mapper.

What it never does is send a write. A mutation is compared with the bundle and nothing more, and
so is a companion, whose answer nothing reads. The two documents and the replays are paced like
any read on this account. The bundles are static assets fetched through a cookieless transport
pinned to the static host, and like a CDN download they take no pacer slot.

A checkpoint ends the run at once, and nothing is sent again. A replay that fails
in any other way is reported with its classified error and the run goes on, because the next
operation's answer does not depend on it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum

from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import Response, Sender
from dumpstagram._private.web.bootstrap import (
   DEFAULT_USER_AGENT,
   apply_tokens,
   build_bootstrap_request,
   build_document_request,
   tokens_from,
)
from dumpstagram._private.web.bundles import (
   build_bundle_request,
   bundle_urls,
   compiled_operations,
)
from dumpstagram._private.web.canary import REPLAY_STEPS, ReplayArguments, ReplayStep
from dumpstagram._private.web.classify import classify, classify_checkpoint_only
from dumpstagram._private.web.documents.catalog import (
   COMPANION_QUERIES,
   READ_QUERIES,
   WRITE_QUERIES,
)
from dumpstagram._private.web.documents.common import PersistedQuery
from dumpstagram._private.web.preload import HOME_DOCUMENT_URL, read_iris_device_id
from dumpstagram.errors import (
   CheckpointRequired,
   DumpstagramError,
   TransportFailure,
   UpstreamRejected,
)
from dumpstagram.session import Session

__all__ = [
   "DEFAULT_BUNDLE_LIMIT",
   "DOCUMENTS_LOADED",
   "BundleVerdict",
   "DoctorPlan",
   "DoctorReport",
   "OperationCheck",
   "QueryRole",
   "ReplayVerdict",
   "RotationDoctor",
   "doctor_plan",
]

DOCUMENTS_LOADED = 2
"""The inbox document the bootstrap reads, and the home document."""

DEFAULT_BUNDLE_LIMIT = 1000
"""The most bundles one run fetches when the caller names no limit.

The home document of 2026-09-23 named 541 distinct bundles, of which a cold load fetched 66, so
two documents stay under this with room, and a document that suddenly named thousands would not
turn one run into thousands of fetches.
"""

_STATIC_OK = 200


class QueryRole(StrEnum):
   """What sending a query does, which decides whether the canary sends it."""

   READ = "read"
   COMPANION = "companion"
   WRITE = "write"


class BundleVerdict(StrEnum):
   OK = "ok"
   DRIFT = "drift"
   MISSING = "missing"


class ReplayVerdict(StrEnum):
   OK = "ok"
   FAILED = "failed"
   SKIPPED = "skipped"
   ARTIFACT_ONLY = "artifact_only"


@dataclass(frozen=True)
class OperationCheck:
   """One stored operation against the bundle, and its replay when it is a read.

   ``compiled_doc_ids`` holds every id the scanned bundles gave the operation, sorted. The
   verdict is ``OK`` only when that is exactly the stored id. ``artifact_seen`` says whether its
   ``.graphql`` artifact was in a scanned bundle, which tells a missing id module from an
   operation no scanned bundle holds.
   """

   operation: str
   role: QueryRole
   stored_doc_id: str
   compiled_doc_ids: tuple[str, ...]
   artifact_seen: bool
   bundle: BundleVerdict
   replay: ReplayVerdict
   replay_error: str | None = None
   replay_code: str | None = None
   replay_note: str | None = None


@dataclass(frozen=True)
class DoctorPlan:
   """What a run would send, stated before anything is sent."""

   documents: int
   reads: tuple[str, ...]
   companions: tuple[str, ...]
   writes: tuple[str, ...]
   bundle_limit: int

   @property
   def paced_requests_at_most(self) -> int:
      return self.documents + len(self.reads)


@dataclass(frozen=True)
class DoctorReport:
   checks: tuple[OperationCheck, ...]
   documents_loaded: int
   bundles_named: int
   bundles_fetched: int
   bundles_failed: int
   reads_sent: int

   @property
   def drifted(self) -> tuple[OperationCheck, ...]:
      return tuple(check for check in self.checks if check.bundle is BundleVerdict.DRIFT)

   @property
   def missing(self) -> tuple[OperationCheck, ...]:
      return tuple(check for check in self.checks if check.bundle is BundleVerdict.MISSING)

   @property
   def failed_replays(self) -> tuple[OperationCheck, ...]:
      return tuple(check for check in self.checks if check.replay is ReplayVerdict.FAILED)


@dataclass(frozen=True)
class _ReplayOutcome:
   verdict: ReplayVerdict
   error: str | None = None
   code: str | None = None
   note: str | None = None


def doctor_plan(bundle_limit: int = DEFAULT_BUNDLE_LIMIT) -> DoctorPlan:
   return DoctorPlan(
      documents=DOCUMENTS_LOADED,
      reads=tuple(step.query.friendly_name for step in REPLAY_STEPS),
      companions=tuple(query.friendly_name for query in COMPANION_QUERIES),
      writes=tuple(query.friendly_name for query in WRITE_QUERIES),
      bundle_limit=bundle_limit,
   )


def _roles() -> list[tuple[PersistedQuery, QueryRole]]:
   return [
      *((query, QueryRole.READ) for query in READ_QUERIES),
      *((query, QueryRole.COMPANION) for query in COMPANION_QUERIES),
      *((query, QueryRole.WRITE) for query in WRITE_QUERIES),
   ]


class RotationDoctor:
   """One run of the canary over one account.

   ``sender`` is the account's paced sender, which the canary does not own. ``bundle_sender`` is
   the cookieless transport pinned to the static host, and the canary closes it in
   :meth:`aclose` only when ``owns_bundle_sender`` says it was made for this run.
   """

   def __init__(
      self,
      sender: PacedSender,
      bundle_sender: Sender,
      session: Session,
      *,
      user_agent: str = DEFAULT_USER_AGENT,
      bundle_limit: int = DEFAULT_BUNDLE_LIMIT,
      owns_bundle_sender: bool = False,
   ) -> None:
      if bundle_limit < 1:
         raise ValueError("a bundle limit is at least 1")

      self._sender = sender
      self._bundle_sender = bundle_sender
      self._session = session
      self._user_agent = user_agent
      self._bundle_limit = bundle_limit
      self._owns_bundle_sender = owns_bundle_sender

   def plan(self) -> DoctorPlan:
      return doctor_plan(self._bundle_limit)

   async def run(self) -> DoctorReport:
      inbox_html = await self._load_inbox_document()
      home_html = await self._load_home_document()

      named = self._bundles_named_by(inbox_html, home_html)
      within_the_limit = named[: self._bundle_limit]
      compiled, artifacts, fetched, failed = await self._scan_bundles(within_the_limit)

      device_id = read_iris_device_id(inbox_html) or str(uuid.uuid4())
      replays, reads_sent = await self._replay_reads(device_id)

      checks = tuple(
         self._check(query, role, compiled, artifacts, replays) for query, role in _roles()
      )

      return DoctorReport(
         checks=checks,
         documents_loaded=DOCUMENTS_LOADED,
         bundles_named=len(named),
         bundles_fetched=fetched,
         bundles_failed=failed,
         reads_sent=reads_sent,
      )

   async def _load_inbox_document(self) -> str:
      response = await self._sender.send(build_bootstrap_request(self._user_agent))
      apply_tokens(self._session, tokens_from(response))

      return response.text

   async def _load_home_document(self) -> str:
      request = build_document_request(HOME_DOCUMENT_URL, self._user_agent)
      response = await self._sender.send(request)
      classify_checkpoint_only(response)

      return response.text

   def _bundles_named_by(self, *documents: str) -> tuple[str, ...]:
      ordered: dict[str, None] = {}

      for html in documents:
         for url in bundle_urls(html):
            ordered.setdefault(url, None)

      return tuple(ordered)

   async def _scan_bundles(
      self, urls: tuple[str, ...]
   ) -> tuple[dict[str, set[str]], set[str], int, int]:
      wanted = {query.friendly_name for query, _ in _roles()}
      compiled: dict[str, set[str]] = {}
      artifacts: set[str] = set()
      fetched = 0
      failed = 0

      for url in urls:
         every_operation_located = wanted <= compiled.keys()

         if every_operation_located:
            break

         response = await self._fetch_bundle(url)
         fetched += 1

         if response is None:
            failed += 1
            continue

         found = compiled_operations(response.text)
         artifacts |= found.artifacts

         for operation, doc_ids in found.doc_ids.items():
            compiled.setdefault(operation, set()).update(doc_ids)

      return compiled, artifacts, fetched, failed

   async def _fetch_bundle(self, url: str) -> Response | None:
      """One bundle, or ``None`` when it did not arrive as a bundle.

      A static asset has no error envelope, so its status is what says it arrived. A bundle
      that did not is counted in the report as failed, never read, and never retried.
      """

      try:
         response = await self._bundle_sender.send(build_bundle_request(url, self._user_agent))
      except TransportFailure:
         return None

      arrived = response.status_code == _STATIC_OK

      return response if arrived else None

   async def _replay_reads(self, device_id: str) -> tuple[dict[str, _ReplayOutcome], int]:
      arguments = ReplayArguments(device_id=device_id, viewer_id=self._session.ds_user_id)
      outcomes: dict[str, _ReplayOutcome] = {}
      sent = 0

      for step in REPLAY_STEPS:
         needs_an_argument = step.requires is not None
         learned = getattr(arguments, step.requires) if step.requires is not None else None
         missing_argument = needs_an_argument and learned is None

         if missing_argument:
            outcomes[step.query.friendly_name] = _ReplayOutcome(
               ReplayVerdict.SKIPPED, note=f"no {step.requires} was learned to replay it with"
            )
            continue

         sent += 1
         outcomes[step.query.friendly_name] = await self._replay(step, arguments)

      return outcomes, sent

   async def _replay(self, step: ReplayStep, arguments: ReplayArguments) -> _ReplayOutcome:
      request = step.build(self._session, arguments, self._user_agent)

      try:
         response = await self._sender.send(request)
         step.read(classify(response), arguments)
      except CheckpointRequired:
         raise
      except DumpstagramError as failure:
         code = failure.code if isinstance(failure, UpstreamRejected) else None

         return _ReplayOutcome(ReplayVerdict.FAILED, error=type(failure).__name__, code=code)

      return _ReplayOutcome(ReplayVerdict.OK)

   def _check(
      self,
      query: PersistedQuery,
      role: QueryRole,
      compiled: dict[str, set[str]],
      artifacts: set[str],
      replays: dict[str, _ReplayOutcome],
   ) -> OperationCheck:
      found = compiled.get(query.friendly_name, set())

      if not found:
         bundle = BundleVerdict.MISSING
      elif found == {query.doc_id}:
         bundle = BundleVerdict.OK
      else:
         bundle = BundleVerdict.DRIFT

      is_replayed = role is QueryRole.READ
      replay = replays.get(query.friendly_name) if is_replayed else None

      if replay is None:
         replay = _ReplayOutcome(ReplayVerdict.ARTIFACT_ONLY)

      return OperationCheck(
         operation=query.friendly_name,
         role=role,
         stored_doc_id=query.doc_id,
         compiled_doc_ids=tuple(sorted(found)),
         artifact_seen=query.friendly_name in artifacts,
         bundle=bundle,
         replay=replay.verdict,
         replay_error=replay.error,
         replay_code=replay.code,
         replay_note=replay.note,
      )

   async def aclose(self) -> None:
      if not self._owns_bundle_sender:
         return

      closer = getattr(self._bundle_sender, "aclose", None)

      if closer is not None:
         await closer()
