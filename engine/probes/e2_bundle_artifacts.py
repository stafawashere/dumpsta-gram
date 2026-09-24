"""Cookieless. At most 80 bundle fetches from static.cdninstagram.com, no Instagram API request.

The E2 preparation evidence. The census of 2026-09-23 named every E2 operation with its argument
names and a one level root selection, read in the browser. This reads the same compiled
artifacts over plain HTTP, the way ``dumpsta doctor`` reads id modules, for three things the
census did not keep: each argument's compiled default, the fields the whole normalization
selection names, and any operation or REST path a lazily loaded chunk carries that no page load
parsed, such as the likers dialog, the activity feed and the stories page.

No page document is fetched. The bundle URLs come from the home document recorded in
``skills/reverse-engineer/var/captures/run-2026-09-23-011707-home-document.jsonl``: first the
chunks its bootloader ``compMap`` lists for the lazily loaded dialogs named in
:data:`LAZY_COMPONENTS` that the recorded load did not fetch, then the bundles the recorded load
fetched, in load order. Every fetch goes through a cookieless transport pinned to the static
host, never through the account's own, and no session file is opened. Fetches are 1.2 s apart.
The run stops at the first status other than 200, and at the second transport failure. A
transport failure on one bundle is recorded and that bundle skipped, because the static host
stalled a read once on 2026-09-23 while answering every other bundle. ``--start`` resumes a plan
where an earlier run stopped, and ``--budget`` is what is left of the 80 fetches, so two runs
together never pass the cap. An earlier extraction in the run directory is merged, not replaced.

Bundles are public, static and immutable, and hold no account data. The full extraction,
``doc_id`` values included, goes to the reverse-engineer run directory named by ``--run``,
which is local and never committed. The log in ``engine/logs/`` carries counts, sizes and
operation names only.

Run it from `engine/` with:

   uv run python probes/e2_bundle_artifacts.py --run <run-id>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from typing import Any

from _probe_support import ENGINE_ROOT, report_run

from dumpstagram._private.transport import HttpxTransport
from dumpstagram._private.web.bundles import (
   STATIC_BUNDLE_HOST,
   build_bundle_request,
   compiled_operations,
)
from dumpstagram.errors import DumpstagramError

REPOSITORY_ROOT = ENGINE_ROOT.parent
SKILL_ROOT = REPOSITORY_ROOT / "skills" / "reverse-engineer"
HOME_DOCUMENT_CAPTURE = (
   SKILL_ROOT / "var" / "captures" / "run-2026-09-23-011707-home-document.jsonl"
)
CENSUS_PATH = SKILL_ROOT / "knowledge" / "census.md"

FETCH_CAP = 80
FETCH_SPACING_SECONDS = 1.2

LAZY_COMPONENTS = (
   "PolarisLikedByListContainer.react",
   "PolarisPostLikedByListDialogRoot.react",
   "PolarisCommentLikedByListContainer.react",
   "PolarisActivityFeed.react",
   "PolarisActivityFeedV2Stories.react",
   "PolarisDesktopStoriesPage.react",
   "PolarisPostFastTaggedModal.next.react",
   "PolarisUserHoverCardContentV2.react",
)

ARTIFACT_START = re.compile(r'__d\("([A-Za-z0-9_]+)\.graphql",')
MODULE_START = re.compile(r'__d\("')
LOCAL_ARGUMENT = re.compile(r'defaultValue:(.{0,80}?),kind:"LocalArgument",name:"([A-Za-z0-9_]+)"')
LINKED_FIELD = re.compile(r'kind:"LinkedField",name:"([A-Za-z0-9_]+)"')
SCALAR_FIELD = re.compile(r'kind:"ScalarField",name:"([A-Za-z0-9_]+)"')
CONCRETE_TYPE = re.compile(r'concreteType:"([A-Za-z0-9_]+)"')
FIELD_VARIABLE = re.compile(
   r'kind:"Variable",name:"([A-Za-z0-9_]+)",variableName:"([A-Za-z0-9_]+)"'
)
FIELD_LITERAL = re.compile(r'kind:"Literal",name:"([A-Za-z0-9_]+)",value:([^}]{0,60})\}')
PROVIDER = re.compile(r"__relay_internal__pv__[A-Za-z0-9_]+")
OPERATION_KIND = re.compile(r'name:"([A-Za-z0-9_]+)",operationKind:"(query|mutation|subscription)"')
METADATA = re.compile(r"metadata:\{([^{}]{0,300})\}")
REST_PATH = re.compile(r'"(/?api/v1/[A-Za-z0-9_/{}:.\-]*)"')

INTERESTING_REST_WORDS = (
   "friendships",
   "followers",
   "following",
   "news",
   "likers",
   "feed",
   "discover",
   "explore",
   "clips",
   "music",
   "tags",
   "locations",
   "fbsearch",
   "archive",
   "collections",
   "saved",
   "highlights",
   "stories",
   "reel",
   "users",
   "direct_v2",
   "blocked",
   "close_friends",
   "besties",
)


def read_home_document_capture() -> tuple[str, list[str]]:
   records = [
      json.loads(line)
      for line in HOME_DOCUMENT_CAPTURE.read_text(encoding="utf-8").splitlines()
      if line.strip()
   ]
   documents = [
      record
      for record in records
      if record.get("url", "").rstrip("/") == "https://www.instagram.com"
   ]
   fetched = []

   for record in records:
      url = record.get("url", "")
      is_static_bundle = f"//{STATIC_BUNDLE_HOST}/" in url and url.endswith(".js")

      if is_static_bundle and url not in fetched:
         fetched.append(url)

   return documents[0]["response_body"], fetched


def bootloader_maps(html: str) -> tuple[dict[str, Any], dict[str, Any]]:
   decoder = json.JSONDecoder()
   resources: dict[str, Any] = {}
   components: dict[str, Any] = {}

   for key, target in (("rsrcMap", resources), ("compMap", components)):
      for match in re.finditer(rf'"{key}":\{{', html):
         parsed, _ = decoder.raw_decode(html[match.end() - 1 :])
         target.update(parsed)

   return resources, components


def plan_fetches(html: str, fetched_by_the_load: list[str]) -> list[tuple[str, str]]:
   resources, components = bootloader_maps(html)
   plan: list[tuple[str, str]] = []
   planned: set[str] = set()

   for component in LAZY_COMPONENTS:
      for resource_hash in components.get(component, {}).get("r", []):
         resource = resources.get(resource_hash)
         is_script = isinstance(resource, dict) and resource.get("type") == "js"

         if not is_script:
            continue

         url = resource["src"]
         is_new = url not in planned and url not in fetched_by_the_load

         if is_new:
            plan.append((url, f"lazy:{component}"))
            planned.add(url)

   for url in fetched_by_the_load:
      if url not in planned:
         plan.append((url, "home load"))
         planned.add(url)

   return plan[:FETCH_CAP]


def e2_operations() -> set[str]:
   names = set()

   for line in CENSUS_PATH.read_text(encoding="utf-8").splitlines():
      is_e2_row = line.startswith("| `") and "| E2 |" in line

      if is_e2_row:
         names.add(line.split("`")[1])

   return names


def module_spans(text: str) -> list[tuple[str, str]]:
   starts = [match.start() for match in MODULE_START.finditer(text)]
   spans = []

   for match in ARTIFACT_START.finditer(text):
      following = [start for start in starts if start > match.start()]
      end = following[0] if following else len(text)
      spans.append((match.group(1), text[match.start() : end]))

   return spans


def describe_artifact(module_text: str) -> dict[str, Any]:
   kinds = OPERATION_KIND.findall(module_text)

   return {
      "operation_kind": kinds[0][1] if kinds else None,
      "arguments": [
         {"name": name, "default": default.strip()}
         for default, name in LOCAL_ARGUMENT.findall(module_text)
      ],
      "providers": sorted(set(PROVIDER.findall(module_text))),
      "linked_fields": sorted(set(LINKED_FIELD.findall(module_text))),
      "scalar_fields": sorted(set(SCALAR_FIELD.findall(module_text))),
      "concrete_types": sorted(set(CONCRETE_TYPE.findall(module_text))),
      "field_variables": sorted(
         {f"{name}=${variable}" for name, variable in FIELD_VARIABLE.findall(module_text)}
      ),
      "field_literals": sorted(
         {f"{name}={value.strip()}" for name, value in FIELD_LITERAL.findall(module_text)}
      ),
      "metadata": sorted(set(METADATA.findall(module_text)))[:4],
      "chars": len(module_text),
   }


def interesting_rest_paths(text: str) -> set[str]:
   found = set()

   for path in REST_PATH.findall(text):
      if any(word in path for word in INTERESTING_REST_WORDS):
         found.add(path)

   return found


async def run(run_id: str, start: int, budget: int) -> int:
   run_dir = SKILL_ROOT / "var" / "runs" / run_id

   report: dict[str, Any] = {
      "run": run_id,
      "page_documents_fetched": 0,
      "cookies_sent": False,
      "session_file_opened": False,
      "fetch_cap": FETCH_CAP,
      "fetch_spacing_seconds": FETCH_SPACING_SECONDS,
   }

   if not run_dir.is_dir():
      report["failed_with"] = "no such run directory, open one with new_run.py"
      report_run("e2-bundle-artifacts-failed", report)

      return 2

   html, fetched_by_the_load = read_home_document_capture()
   plan = plan_fetches(html, fetched_by_the_load)[start:][: min(budget, FETCH_CAP)]
   wanted = e2_operations()

   report["plan_start"] = start
   report["budget"] = budget
   report["bundles_planned"] = len(plan)
   report["planned_lazy"] = sum(1 for _, source in plan if source.startswith("lazy:"))
   report["e2_operations_in_census"] = len(wanted)

   transport = HttpxTransport(allowed_host=STATIC_BUNDLE_HOST, cookieless=True)
   extraction_path = run_dir / "bundle-artifacts.json"
   earlier: dict[str, Any] = {}

   if extraction_path.exists():
      earlier = json.loads(extraction_path.read_text(encoding="utf-8"))

   artifacts: dict[str, Any] = earlier.get("artifacts", {})
   doc_ids: dict[str, list[str]] = earlier.get("doc_ids", {})
   rest_paths: dict[str, list[str]] = earlier.get("rest_paths", {})
   transport_failures: list[dict[str, Any]] = []
   per_bundle: list[dict[str, Any]] = []
   spent = 0
   started_at = time.monotonic()

   try:
      for offset, (url, source) in enumerate(plan):
         index = start + offset

         if offset:
            await asyncio.sleep(FETCH_SPACING_SECONDS)

         spent += 1

         try:
            answer = await transport.send(build_bundle_request(url))
         except DumpstagramError as failure:
            cause = failure.__cause__
            transport_failures.append(
               {
                  "index": index,
                  "source": source,
                  "failed_with": type(failure).__name__,
                  "cause": type(cause).__name__ if cause else None,
               }
            )

            if len(transport_failures) >= 2:
               break

            continue

         if answer.status_code != 200:
            report["stopped_on_status"] = answer.status_code
            report["stopped_at_bundle"] = index

            break

         text = answer.text
         compiled = compiled_operations(text)

         for operation, ids in compiled.doc_ids.items():
            doc_ids.setdefault(operation, [])
            doc_ids[operation] = sorted(set(doc_ids[operation]) | set(ids))

         names_here = []

         for name, module_text in module_spans(text):
            names_here.append(name)
            artifacts.setdefault(name, describe_artifact(module_text) | {"source": source})

         for path in interesting_rest_paths(text):
            rest_paths.setdefault(path, [])

            if source not in rest_paths[path]:
               rest_paths[path].append(source)

         per_bundle.append(
            {
               "index": index,
               "source": source,
               "chars": len(text),
               "artifacts": len(names_here),
               "e2_artifacts": sorted(name for name in names_here if name in wanted),
            }
         )
   except DumpstagramError as failure:
      report["failed_with"] = type(failure).__name__
      report["failure_text"] = str(failure)[:200]
   finally:
      await transport.aclose()

   found_e2 = sorted(name for name in wanted if name in artifacts)
   lazy_only = sorted(
      name
      for name, artifact in artifacts.items()
      if artifact["source"].startswith("lazy:") and artifact["operation_kind"]
   )

   extraction = {
      "run": run_id,
      "artifacts": artifacts,
      "doc_ids": doc_ids,
      "rest_paths": rest_paths,
   }
   extraction_path.write_text(
      json.dumps(extraction, indent=1, sort_keys=True) + "\n", encoding="utf-8"
   )

   report["bundles_fetched"] = spent
   report["transport_failures"] = transport_failures
   report["elapsed_ms"] = int((time.monotonic() - started_at) * 1000)
   report["artifacts_seen"] = len(artifacts)
   report["e2_artifacts_found"] = found_e2
   report["e2_artifacts_missing"] = sorted(wanted - set(found_e2))
   report["operations_from_lazy_chunks"] = lazy_only
   report["interesting_rest_paths"] = len(rest_paths)
   report["per_bundle"] = per_bundle

   report_run("e2-bundle-artifacts", report)

   return 0


if __name__ == "__main__":
   parser = argparse.ArgumentParser()
   parser.add_argument("--run", required=True)
   parser.add_argument("--start", type=int, default=0)
   parser.add_argument("--budget", type=int, default=FETCH_CAP)
   arguments = parser.parse_args()

   sys.exit(asyncio.run(run(arguments.run, arguments.start, arguments.budget)))
