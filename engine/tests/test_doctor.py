"""Gates on the rotation canary, E1 item 7, which never runs in the suite against the network.

The bundle parser is held to a recorded, trimmed bundle and a trimmed document from 2026-09-23
captures. The canary itself runs over a fake site: a sender that answers each document and each
read with a payload the capability's own mapper accepts, and a bundle sender that serves bundles
built in the recorded module shape. The account's sender is a real ``PacedSender`` on a fake
clock, so what departs is what the canary sent through the pacer. The command's gates drive
``main`` with factories that never reach a network.
"""

from __future__ import annotations

import asyncio
import importlib
import io
import json
import pkgutil
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

import pytest

import dumpstagram._private.web.documents as documents_package
from dumpstagram._cli.exits import EXIT_DRIFT, EXIT_OK, EXIT_REPLAY_FAILED
from dumpstagram._cli.main import main
from dumpstagram._core.doctor import (
   BundleVerdict,
   DoctorReport,
   OperationCheck,
   QueryRole,
   ReplayVerdict,
   RotationDoctor,
   doctor_plan,
)
from dumpstagram._core.pacer import Pacer
from dumpstagram._core.requesting import PacedSender
from dumpstagram._private.transport import Request, Response
from dumpstagram._private.web.bootstrap import BOOTSTRAP_URL
from dumpstagram._private.web.bundles import STATIC_BUNDLE_HOST, bundle_urls, compiled_operations
from dumpstagram._private.web.canary import REPLAY_STEPS
from dumpstagram._private.web.documents.catalog import (
   COMPANION_QUERIES,
   READ_QUERIES,
   WRITE_QUERIES,
)
from dumpstagram._private.web.documents.common import PersistedQuery
from dumpstagram._private.web.documents.direct import DIRECT_INBOX, THREAD_DETAIL
from dumpstagram._private.web.documents.media import LIKE_MEDIA
from dumpstagram._private.web.documents.notes import INBOX_TRAY
from dumpstagram._private.web.preload import HOME_DOCUMENT_URL
from dumpstagram.aio import AsyncClient, _rotation_doctor
from dumpstagram.errors import CheckpointRequired
from dumpstagram.session import Session
from tests.test_comments import page_payload as comment_page_payload
from tests.test_feed import item as feed_item
from tests.test_feed import payload as feed_payload
from tests.test_inbox_listing import listing_payload, listing_row, message_edge
from tests.test_likes import post_item, post_payload
from tests.test_notes import tray_payload
from tests.test_parse import payload as thread_page_payload
from tests.test_profiles import profile_payload, timeline_payload
from tests.test_smoke import FakeClock
from tests.test_thread_route import detail_payload

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "doctor"
RECORDED_BUNDLE = FIXTURES / "bundle_recorded_trimmed.js"
RECORDED_DOCUMENT = FIXTURES / "document_trimmed.html"

VIEWER_ID = "1234567890"
THREAD_FBID = "17800000000000001"
DEVICE_ID = "0b6f2c1e-8d7a-4c55-9e3f-2a1b0c9d8e7f"
ROTATED_DOC_ID = "11111111111111111"

EVERY_QUERY = (*READ_QUERIES, *COMPANION_QUERIES, *WRITE_QUERIES)
WRITE_NAMES = frozenset(query.friendly_name for query in WRITE_QUERIES)
WRITE_DOC_IDS = frozenset(query.doc_id for query in WRITE_QUERIES)


def static_url(name: str) -> str:
   return f"https://{STATIC_BUNDLE_HOST}/rsrc.php/v4/yF/r/{name}.js"


def relay_operation_module(operation: str, doc_id: str) -> str:
   """One id module in the shape recorded for ``usePolarisPostDeleteCommentMutation``."""

   return (
      f'__d("{operation}_instagramRelayOperation",[],'
      f'(function(t,n,r,o,a,i){{a.exports="{doc_id}"}}),null);'
   )


def artifact_module(operation: str) -> str:
   return (
      f'__d("{operation}.graphql",["{operation}_instagramRelayOperation"],'
      '(function(t,n,r,o,a,i){"use strict";}),null);'
   )


def bundle_compiling(queries: list[PersistedQuery], *, rotated: str | None = None) -> str:
   lines = []

   for query in queries:
      doc_id = ROTATED_DOC_ID if query.friendly_name == rotated else query.doc_id
      lines.append(artifact_module(query.friendly_name))
      lines.append(relay_operation_module(query.friendly_name, doc_id))

   return "\n".join(lines)


def document(urls: list[str]) -> str:
   """A page document carrying the tokens the bootstrap reads and the bundles it names."""

   escaped = [url.replace("/", "\\/") for url in urls[1:]]
   rsrc_map = ",".join(
      f'"h{index}":{{"type":"js","src":"{url}","c":1}}' for index, url in enumerate(escaped)
   )

   return (
      "<!DOCTYPE html><html><head>"
      f'<link rel="preload" href="{urls[0]}" as="script" crossorigin="anonymous" />'
      '<script>["DTSGInitialData",[],{"token":"a-fresh-token"}],'
      '["LSD",[],{"token":"a-fresh-lsd"}],'
      '["WebBloksVersioningID",[],{"versioningID":"0a1b2c3d"}],'
      f'["IGDMqttWebDeviceID",[],{{"clientId":"{DEVICE_ID}"}}]</script>'
      f'<script type="application/json" data-sjs>{{"rsrcMap":{{{rsrc_map}}}}}</script>'
      "</head></html>"
   )


def json_response(payload: Any, url: str) -> Response:
   return Response(
      status_code=200,
      headers={"content-type": "application/json"},
      content=json.dumps(payload).encode("utf-8"),
      final_url=url,
   )


def html_response(html: str, url: str) -> Response:
   return Response(
      status_code=200,
      headers={"content-type": "text/html; charset=utf-8"},
      content=html.encode("utf-8"),
      final_url=url,
   )


def answers_for_every_read() -> dict[str, Any]:
   """A payload per read that the capability's own mapper accepts."""

   inbox = listing_payload(
      [
         listing_row(
            thread_fbid=THREAD_FBID,
            thread_key="17800000000000901",
            activity_ms="1790153242519",
            message_edges=[message_edge("mid.$newest", "1790153242519")],
         )
      ]
   )

   return {
      "PolarisDirectInboxQuery": inbox,
      "IGDInboxTrayQuery": tray_payload([]),
      "IGDThreadDetailQuery": detail_payload([]),
      "IGDMessageListOffMsysQuery": thread_page_payload([]),
      "useIGDMessageListPaginationQuery": thread_page_payload([]),
      "PolarisFeedRootPaginationCachedQuery_subscribe": feed_payload([feed_item()]),
      "PolarisPostRootQuery": post_payload([post_item()]),
      "PolarisPostCommentsPaginationQuery": comment_page_payload(
         [], has_next_page=False, end_cursor=None
      ),
      "PolarisProfilePageContentQuery": profile_payload(),
      "PolarisProfilePostsQuery": timeline_payload(),
   }


@dataclass
class FakeSite:
   """The account's side of the site: two documents and the GraphQL gateway.

   A write reaching it fails the test on the spot, whatever the canary does with the error.
   """

   documents: Mapping[str, str]
   answers: dict[str, Any]
   checkpoint_on: str | None = None
   sent: list[str] = field(default_factory=list)
   writes_seen: list[str] = field(default_factory=list)

   async def send(self, request: Request) -> Response:
      if request.method == "GET":
         self.sent.append(request.url)

         return html_response(self.documents[request.url], request.url)

      body = parse_qs((request.content or b"").decode("utf-8"))
      name = body["fb_api_req_friendly_name"][0]
      doc_id = body["doc_id"][0]
      is_a_write = name in WRITE_NAMES or doc_id in WRITE_DOC_IDS

      self.sent.append(name)

      if is_a_write:
         self.writes_seen.append(name)
         pytest.fail(f"the canary sent the write {name}")

      if name == self.checkpoint_on:
         return json_response({"error": "checkpoint_required"}, request.url)

      return json_response(self.answers[name], request.url)


@dataclass
class FakeBundles:
   bundles: Mapping[str, str]
   fetched: list[str] = field(default_factory=list)

   async def send(self, request: Request) -> Response:
      self.fetched.append(request.url)
      text = self.bundles.get(request.url)

      if text is None:
         return Response(status_code=404, headers={}, content=b"", final_url=request.url)

      return Response(
         status_code=200,
         headers={"content-type": "application/x-javascript; charset=utf-8"},
         content=text.encode("utf-8"),
         final_url=request.url,
      )


def a_session() -> Session:
   return Session(sessionid="sessionid-value", ds_user_id=VIEWER_ID, csrftoken="csrf-value")


def a_site(
   bundles: dict[str, str],
   *,
   answers: dict[str, Any] | None = None,
   checkpoint_on: str | None = None,
) -> FakeSite:
   urls = list(bundles)
   half = max(1, len(urls) // 2)

   return FakeSite(
      documents={
         BOOTSTRAP_URL: document(urls[:half]),
         HOME_DOCUMENT_URL: document(urls[half:] or urls[:1]),
      },
      answers=answers_for_every_read() if answers is None else answers,
      checkpoint_on=checkpoint_on,
   )


def run_doctor(site: FakeSite, bundles: FakeBundles, *, bundle_limit: int = 1000) -> DoctorReport:
   clock = FakeClock()
   pacer = Pacer(clock=clock, sleep=clock.sleep, jitter=lambda: 0.0)
   doctor = RotationDoctor(
      PacedSender(site, pacer), bundles, a_session(), bundle_limit=bundle_limit
   )

   return asyncio.run(doctor.run())


def check_for(report: DoctorReport, query: PersistedQuery) -> OperationCheck:
   return next(check for check in report.checks if check.operation == query.friendly_name)


def every_query_compiled(*, rotated: str | None = None) -> dict[str, str]:
   """Every stored operation compiled across two bundles, one per document."""

   first = list(EVERY_QUERY[:15])
   second = list(EVERY_QUERY[15:])

   return {
      static_url("aaaaaaaaaaa"): bundle_compiling(first, rotated=rotated),
      static_url("bbbbbbbbbbb"): bundle_compiling(second, rotated=rotated),
   }


def test_the_recorded_bundle_yields_the_operation_and_the_doc_id_it_compiles() -> None:
   """Catches an id module the parser no longer matches, and a name or id read off the wrong
   group, on the one id module a bundle was recorded carrying."""

   found = compiled_operations(RECORDED_BUNDLE.read_text(encoding="utf-8"))

   assert found.doc_ids == {"usePolarisPostDeleteCommentMutation": frozenset({"27034318419564986"})}
   assert found.artifacts == frozenset(
      {"usePolarisPostDeleteCommentMutation", "IGDirectTextSendMutation"}
   )


def test_every_bundle_the_document_names_is_found_once_in_document_order() -> None:
   """Catches the escaped bootloader form going unread, a stylesheet or another host taken for
   a bundle, and a bundle named twice being fetched twice."""

   urls = bundle_urls(RECORDED_DOCUMENT.read_text(encoding="utf-8"))

   assert urls == (
      "https://static.cdninstagram.com/rsrc.php/v4/y1/r/gw3JwYvxWUJ.js",
      "https://static.cdninstagram.com/rsrc.php/v4ix-z4/yV/l/en_US-j/zESKSn3qFiS.js",
      "https://static.cdninstagram.com/rsrc.php/v4iwJv4/yu/l/en_US-j/k2MzgetyNzr.js",
      "https://static.cdninstagram.com/rsrc.php/v4/yL/r/vOnll8taeez.js",
   )


def test_every_stored_operation_the_bundles_compile_unchanged_is_ok() -> None:
   """The positive control for the drift and missing gates: nothing rotated, nothing flagged."""

   bundles = every_query_compiled()
   report = run_doctor(a_site(bundles), FakeBundles(bundles))

   assert [check.bundle for check in report.checks] == [BundleVerdict.OK] * len(EVERY_QUERY)
   assert report.drifted == ()
   assert report.missing == ()


def test_an_operation_whose_compiled_id_differs_is_drift_with_both_ids_reported() -> None:
   """Catches a rotated id reported as fine, and a drift that does not say what it drifted to."""

   bundles = every_query_compiled(rotated=THREAD_DETAIL.friendly_name)
   report = run_doctor(a_site(bundles), FakeBundles(bundles))
   check = check_for(report, THREAD_DETAIL)

   assert check.bundle is BundleVerdict.DRIFT
   assert check.stored_doc_id == THREAD_DETAIL.doc_id
   assert check.compiled_doc_ids == (ROTATED_DOC_ID,)
   assert report.drifted == (check,)


def test_an_operation_no_bundle_compiles_is_missing_and_not_ok() -> None:
   """Catches an operation absent from every scanned bundle reported as matching."""

   compiled_elsewhere = [query for query in EVERY_QUERY if query is not LIKE_MEDIA]
   bundles = {static_url("ccccccccccc"): bundle_compiling(compiled_elsewhere)}
   report = run_doctor(a_site(bundles), FakeBundles(bundles))
   check = check_for(report, LIKE_MEDIA)

   assert check.bundle is BundleVerdict.MISSING
   assert check.compiled_doc_ids == ()
   assert report.missing == (check,)


def test_the_canary_never_sends_a_write_and_checks_every_write_by_artifact() -> None:
   """Catches a write replayed like a read. The fake site fails the test on any write, and the
   read side is the control: every read departs, so the run reached the replays."""

   bundles = every_query_compiled()
   site = a_site(bundles)
   report = run_doctor(site, FakeBundles(bundles))
   writes = [check for check in report.checks if check.role is QueryRole.WRITE]
   replayed = [name for name in site.sent if name not in (BOOTSTRAP_URL, HOME_DOCUMENT_URL)]

   assert site.writes_seen == []
   assert [check.replay for check in writes] == [ReplayVerdict.ARTIFACT_ONLY] * len(WRITE_QUERIES)
   assert [check.operation for check in writes] == [query.friendly_name for query in WRITE_QUERIES]
   assert replayed == [query.friendly_name for query in READ_QUERIES]
   assert WRITE_NAMES.isdisjoint(replayed)


def test_every_replay_step_is_a_catalogued_read_and_none_is_a_write() -> None:
   """Catches a write added to the replay steps, where a missing argument would skip it in
   the dynamic gate, and a read added to the catalog with no step to replay it."""

   step_queries = [step.query for step in REPLAY_STEPS]

   assert step_queries == list(READ_QUERIES)
   assert set(WRITE_QUERIES).isdisjoint(step_queries)
   assert set(COMPANION_QUERIES).isdisjoint(step_queries)


def test_the_catalog_lists_every_registry_query_exactly_once() -> None:
   """Catches a query added to a domain module and never checked, and a mutation catalogued as a
   read. The mutation suffix is the census's own operation kind, read from each name here."""

   registry = []

   for module_info in pkgutil.iter_modules(documents_package.__path__):
      module = importlib.import_module(f"{documents_package.__name__}.{module_info.name}")
      is_the_catalog = module_info.name == "catalog"

      if is_the_catalog:
         continue

      registry.extend(value for value in vars(module).values() if isinstance(value, PersistedQuery))

   catalogued = list(EVERY_QUERY)

   assert len(registry) == 30
   assert sorted(catalogued, key=id) == sorted(set(registry), key=id)
   assert len(set(catalogued)) == len(catalogued)
   assert all(query.friendly_name.endswith("Mutation") for query in WRITE_QUERIES)
   assert not any(query.friendly_name.endswith("Mutation") for query in READ_QUERIES)
   assert not any(query.friendly_name.endswith("Mutation") for query in COMPANION_QUERIES)


def test_a_checkpoint_on_a_replay_ends_the_run_and_nothing_departs_after_it() -> None:
   """Catches a checkpoint recorded as one failed replay and the run carried on into it."""

   bundles = every_query_compiled()
   site = a_site(bundles, checkpoint_on=INBOX_TRAY.friendly_name)

   with pytest.raises(CheckpointRequired):
      run_doctor(site, FakeBundles(bundles))

   assert site.sent[-1] == INBOX_TRAY.friendly_name
   assert site.sent.count(INBOX_TRAY.friendly_name) == 1
   assert site.sent == [
      BOOTSTRAP_URL,
      HOME_DOCUMENT_URL,
      DIRECT_INBOX.friendly_name,
      INBOX_TRAY.friendly_name,
   ]


def test_a_failed_replay_is_reported_with_its_classified_error_and_the_run_goes_on() -> None:
   """Catches an error envelope reported as a passing replay, and one failure ending the run."""

   bundles = every_query_compiled()
   answers = answers_for_every_read()
   answers[INBOX_TRAY.friendly_name] = {"errors": [{"code": 1675030, "message": "a failure"}]}
   site = a_site(bundles, answers=answers)
   report = run_doctor(site, FakeBundles(bundles))
   check = check_for(report, INBOX_TRAY)

   assert check.replay is ReplayVerdict.FAILED
   assert check.replay_error == "UpstreamRejected"
   assert check.replay_code == "1675030"
   assert report.failed_replays == (check,)
   assert site.sent[-1] == READ_QUERIES[-1].friendly_name


def test_a_read_whose_argument_was_never_learned_is_skipped_and_not_sent() -> None:
   """Catches a thread read sent with no thread to read, when the inbox listed none."""

   bundles = every_query_compiled()
   answers = answers_for_every_read()
   answers[DIRECT_INBOX.friendly_name] = listing_payload([], has_next_page=False, end_cursor=None)
   site = a_site(bundles, answers=answers)
   report = run_doctor(site, FakeBundles(bundles))
   thread_reads = ("IGDThreadDetailQuery", "IGDMessageListOffMsysQuery")
   thread_reads += ("useIGDMessageListPaginationQuery",)
   skipped = [check for check in report.checks if check.operation in thread_reads]

   assert [check.replay for check in skipped] == [ReplayVerdict.SKIPPED] * 3
   assert set(thread_reads).isdisjoint(site.sent)
   assert report.reads_sent == len(READ_QUERIES) - 3


def test_the_bundle_scan_stops_once_every_stored_operation_is_located() -> None:
   """Catches a scan that fetches every bundle a document names after it already has its
   answer. The home document names a bundle the scan never needs."""

   bundles = every_query_compiled()
   unneeded = static_url("zzzzzzzzzzz")
   named = {**bundles, unneeded: bundle_compiling([])}
   fetcher = FakeBundles(named)

   run_doctor(a_site(named), fetcher)

   assert fetcher.fetched == list(bundles)


def test_the_bundle_scan_fetches_no_more_than_its_limit() -> None:
   """Catches the limit ignored, which lets one document turn a run into thousands of fetches."""

   bundles = every_query_compiled()
   fetcher = FakeBundles(bundles)
   report = run_doctor(a_site(bundles), fetcher, bundle_limit=1)

   assert fetcher.fetched == list(bundles)[:1]
   assert report.bundles_named == 2
   assert report.bundles_fetched == 1


def test_the_bundle_transport_is_cookieless_and_pinned_to_the_static_host() -> None:
   """Catches the account's cookies reaching the static host, or bundles leaving through an
   unpinned transport."""

   async def assemble() -> tuple[str | None, bool]:
      client = AsyncClient(a_session())
      doctor = _rotation_doctor(client)
      transport = doctor._bundle_sender

      try:
         return transport.allowed_host, transport.cookieless  # type: ignore[attr-defined]
      finally:
         await doctor.aclose()
         await client.aclose()

   assert asyncio.run(assemble()) == (STATIC_BUNDLE_HOST, True)


class RefusingFactory:
   def __call__(self, path: Path, *, user_agent: str | None, bundle_limit: int) -> Any:
      raise AssertionError("a dry run opened a client")


def test_a_dry_run_sends_nothing_opens_no_client_and_states_the_plan() -> None:
   """Catches the command going live without --live, the one flag that consents to traffic."""

   out = io.StringIO()
   code = main(
      ["--json", "doctor"],
      environment={},
      doctor_factory=RefusingFactory(),
      stdout=out,
      stderr=io.StringIO(),
   )
   payload = json.loads(out.getvalue())

   assert code == EXIT_OK
   assert payload["live"] is False
   assert payload["plan"]["documents"] == 2
   assert payload["plan"]["reads"] == [query.friendly_name for query in READ_QUERIES]
   assert payload["plan"]["paced_requests_at_most"] == 12
   assert payload["plan"]["writes_checked_by_artifact"] == [
      query.friendly_name for query in WRITE_QUERIES
   ]
   assert "operations" not in payload


@dataclass
class CannedDoctor:
   """Stands in for a live canary, and notes what stderr held when its run began."""

   report: DoctorReport
   stderr: io.StringIO
   stderr_when_run_began: list[str] = field(default_factory=list)
   session: Session = field(default_factory=a_session)

   def plan(self) -> Any:
      return doctor_plan()

   async def run(self) -> DoctorReport:
      self.stderr_when_run_began.append(self.stderr.getvalue())

      return self.report

   async def aclose(self) -> None:
      return None


def a_check(bundle: BundleVerdict, replay: ReplayVerdict = ReplayVerdict.OK) -> OperationCheck:
   return OperationCheck(
      operation="AnOperationQuery",
      role=QueryRole.READ,
      stored_doc_id="22222222222222222",
      compiled_doc_ids=("22222222222222222",),
      artifact_seen=True,
      bundle=bundle,
      replay=replay,
   )


def a_report(*checks: OperationCheck) -> DoctorReport:
   return DoctorReport(
      checks=checks,
      documents_loaded=2,
      bundles_named=1,
      bundles_fetched=1,
      bundles_failed=0,
      reads_sent=1,
   )


def live_run(report: DoctorReport) -> tuple[int, CannedDoctor]:
   stderr = io.StringIO()
   doctor = CannedDoctor(report, stderr)

   def factory(path: Path, *, user_agent: str | None, bundle_limit: int) -> CannedDoctor:
      return doctor

   code = main(
      ["--session", "unused.json", "doctor", "--live"],
      environment={},
      doctor_factory=factory,
      stdout=io.StringIO(),
      stderr=stderr,
   )

   return code, doctor


@pytest.mark.parametrize(
   ("checks", "expected"),
   [
      ((a_check(BundleVerdict.OK),), EXIT_OK),
      ((a_check(BundleVerdict.MISSING),), EXIT_OK),
      ((a_check(BundleVerdict.DRIFT),), EXIT_DRIFT),
      ((a_check(BundleVerdict.OK, ReplayVerdict.FAILED),), EXIT_REPLAY_FAILED),
      ((a_check(BundleVerdict.DRIFT), a_check(BundleVerdict.OK, ReplayVerdict.FAILED)), EXIT_DRIFT),
   ],
)
def test_drift_exits_12_a_failed_replay_13_and_a_missing_operation_alone_0(
   checks: tuple[OperationCheck, ...], expected: int
) -> None:
   """Catches drift exiting 0, which is the one outcome a script running the canary must see,
   and a failed replay hiding a drift reported beside it."""

   code, _ = live_run(a_report(*checks))

   assert code == expected


def test_a_live_run_states_what_it_will_send_on_stderr_before_it_sends() -> None:
   """Catches the request count going unstated, or stated only after the run has sent it."""

   _, doctor = live_run(a_report(a_check(BundleVerdict.OK)))
   stated = doctor.stderr_when_run_began[0]

   assert "2 documents and at most 10 reads" in stated
   assert "at most 1000 cookieless bundle fetches" in stated
