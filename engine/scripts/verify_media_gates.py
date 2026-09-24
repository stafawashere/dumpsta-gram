"""Break the media model, the download and the CDN pin, watch each gate go red, restore.

E1 item 6 of the web parity plan. Same harness and same rule as ``verify_host_pin_gates.py``:
one mutation per gate, only the gate that should catch it is run, every anchor must be found
exactly once, and every file is restored from an in-memory copy in a ``finally`` so an
interrupted run cannot leave a mutation behind.

Run from ``engine/`` with ``uv run python scripts/verify_media_gates.py``. Writes its result to
``engine/logs/``.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
LOG_DIR = ENGINE / "logs"


PARSE = "dumpstagram/_private/web/parse/media.py"
COMMON = "dumpstagram/_private/web/parse/common.py"
DOWNLOADS = "dumpstagram/_core/downloads.py"
CDN = "dumpstagram/_private/web/cdn.py"
TRANSPORT = "dumpstagram/_private/transport.py"
CLIENT = "dumpstagram/aio.py"
NAMESPACE = "dumpstagram/namespaces/media.py"
MODEL_GATES = "tests/test_media_model.py"
DOWNLOAD_GATES = "tests/test_downloads.py"
PARITY_GATES = "tests/test_facade_parity.py"
MISSING = f"{MODEL_GATES}::test_a_missing_named_key_raises_schema_changed_naming_it"
POST_QUERY = (
   f"{MODEL_GATES}::test_the_post_query_maps_a_reel_and_a_carousel_the_way_the_timeline_does"
)
DECLARED_LENGTH = (
   f"{DOWNLOAD_GATES}::test_a_body_that_is_not_the_declared_length_is_refused_and_leaves_nothing"
)
FORWARDS = (
   f"{PARITY_GATES}::"
   "test_a_blocking_namespace_method_forwards_every_argument_on_the_loop_thread[media.download]"
)
SEAM_NOTE = (
   f"{PARITY_GATES}::"
   "test_a_blocking_namespace_method_raises_the_async_exception_under_its_own_name"
   "[media.download]"
)
REACHES_CORE = (
   f"{PARITY_GATES}::"
   "test_a_namespace_method_reaches_the_core_capability_the_table_names[media.download]"
)

MUTATIONS: list[dict[str, object]] = [
   {
      "gate": f"{MODEL_GATES}::test_a_reel_maps_its_renditions_with_their_size_and_type_in_order",
      "defect": "a reel's renditions are dropped",
      "edits": [
         (PARSE, '   versions = _required(node, "video_versions", path)\n', "   versions = None\n")
      ],
   },
   {
      "gate": f"{MODEL_GATES}::test_a_reel_maps_its_renditions_with_their_size_and_type_in_order",
      "defect": "a rendition's type is read from its width",
      "edits": [
         (
            PARSE,
            'version_type=_required_integer(entry, "type", entry_path),',
            'version_type=_required_integer(entry, "width", entry_path),',
         )
      ],
   },
   {
      "gate": f"{MODEL_GATES}::test_a_reel_reads_its_duration_from_the_manifest",
      "defect": "the duration is truncated to whole seconds",
      "edits": [(PARSE, "+ float(seconds or 0)", "+ int(float(seconds or 0))")],
   },
   {
      "gate": f"{MODEL_GATES}::test_a_manifest_duration_is_read_in_hours_minutes_and_seconds",
      "defect": "the hours of a duration are ignored",
      "edits": [(PARSE, "int(hours or 0) * SECONDS_PER_HOUR", "0 * SECONDS_PER_HOUR")],
   },
   {
      "gate": f"{MODEL_GATES}::test_a_duration_outside_the_root_element_is_not_read",
      "defect": "the whole manifest is searched rather than its root tag",
      "edits": [
         (
            PARSE,
            "duration = MANIFEST_DURATION.search(root.group(0)) if root is not None else None",
            "duration = MANIFEST_DURATION.search(manifest)",
         )
      ],
   },
   {
      "gate": f"{MODEL_GATES}::test_a_manifest_without_a_duration_raises",
      "defect": "a manifest without a duration reads as a zero length video",
      "edits": [
         (
            PARSE,
            "   if duration is None:\n      raise SchemaChanged(",
            "   if duration is None:\n      return 0.0\n      raise SchemaChanged(",
         )
      ],
   },
   {
      "gate": f"{MODEL_GATES}::test_a_licensed_song_names_its_title_and_display_artist",
      "defect": "a licensed song is labelled an original sound",
      "edits": [(PARSE, "      kind=AudioKind.MUSIC,", "      kind=AudioKind.ORIGINAL_SOUND,")],
   },
   {
      "gate": f"{MODEL_GATES}::test_an_original_sound_names_the_account_that_made_it",
      "defect": "an original sound loses the id of the account that made it",
      "edits": [
         (PARSE, 'artist_id=_required_string(artist, "id", artist_path),', "artist_id=None,")
      ],
   },
   {
      "gate": f"{MODEL_GATES}::test_a_reel_with_both_audio_slots_filled_raises",
      "defect": "both audio slots filled picks the song",
      "edits": [(PARSE, "   if has_both:\n", "   if False:\n")],
   },
   {
      "gate": f"{MODEL_GATES}::test_a_carousel_maps_every_slide_with_its_own_kind",
      "defect": "a carousel's slides are dropped",
      "edits": [
         (PARSE, '   children = _required(node, "carousel_media", path)\n', "   children = None\n")
      ],
   },
   {
      "gate": f"{MODEL_GATES}::test_a_video_slide_maps_its_renditions_and_duration",
      "defect": "every slide is taken to be a photo",
      "edits": [
         (
            PARSE,
            '      media_type=_required_integer(node, "media_type", path),\n'
            '      product_type=_required_string(node, "product_type", path),\n'
            "      original_width=",
            "      media_type=1,\n"
            '      product_type=_required_string(node, "product_type", path),\n'
            "      original_width=",
         )
      ],
   },
   {
      "gate": f"{MODEL_GATES}::test_a_video_slide_maps_its_renditions_and_duration",
      "defect": "a slide's video renditions are never read",
      "edits": [
         (
            PARSE,
            "   videos = _videos(node, path)\n\n   return CarouselChild(",
            "   videos: tuple[VideoRendition, ...] = ()\n\n   return CarouselChild(",
         )
      ],
   },
   {
      "gate": POST_QUERY,
      "defect": "a slide demands the has_audio the post query's slides do not carry",
      "edits": [
         (
            PARSE,
            "   return CarouselChild(\n",
            '   _optional_flag(node, "has_audio", path)\n\n   return CarouselChild(\n',
         )
      ],
   },
   {
      "gate": POST_QUERY,
      "defect": "the post read is left without its video renditions",
      "edits": [
         (
            PARSE,
            "   videos = _videos(node, path)\n\n   return PostDetail(",
            "   videos = ()\n\n   return PostDetail(",
         )
      ],
   },
   {
      "gate": f"{MISSING}[has_audio]",
      "defect": "a missing has_audio is read as null",
      "edits": [
         (
            COMMON,
            "def _optional_flag(node: dict[str, Any], key: str, path: str) -> bool | None:\n"
            "   value = _required(node, key, path)\n",
            "def _optional_flag(node: dict[str, Any], key: str, path: str) -> bool | None:\n"
            "   value = node.get(key)\n",
         )
      ],
   },
   {
      "gate": f"{MISSING}[clips_metadata]",
      "defect": "a missing clips_metadata is read as no audio",
      "edits": [
         (
            PARSE,
            '   metadata = _required(node, "clips_metadata", path)\n',
            '   metadata = node.get("clips_metadata")\n',
         )
      ],
   },
   {
      "gate": f"{DOWNLOAD_GATES}::test_the_destination_does_not_exist_until_the_body_is_complete",
      "defect": "the body is written straight onto the destination",
      "edits": [
         (
            DOWNLOADS,
            '   return os.fdopen(descriptor, "wb"), Path(name)',
            "   os.close(descriptor)\n"
            "   os.unlink(name)\n"
            '   return open(destination, "wb"), destination',
         )
      ],
   },
   {
      "gate": f"{DOWNLOAD_GATES}::test_an_existing_file_is_refused_before_anything_is_sent",
      "defect": "an existing file is not refused",
      "edits": [(DOWNLOADS, "refuses = is_taken and not overwrite", "refuses = False")],
   },
   {
      "gate": f"{DOWNLOAD_GATES}::test_a_file_that_appears_while_the_body_arrives_is_not_replaced",
      "defect": "the finished file is renamed over whatever took the name meanwhile",
      "edits": [
         (DOWNLOADS, "   if overwrite:\n      os.replace(", "   if True:\n      os.replace(")
      ],
   },
   {
      "gate": DECLARED_LENGTH,
      "defect": "the declared length is never compared",
      "edits": [
         (
            DOWNLOADS,
            "is_short_or_long = declared is not None and received != declared",
            "is_short_or_long = False",
         )
      ],
   },
   {
      "gate": f"{DOWNLOAD_GATES}::test_a_body_with_no_declared_length_is_written_whole",
      "defect": "a body with no declared length is refused",
      "edits": [
         (
            DOWNLOADS,
            "   if raw is None:\n      return None\n",
            '   if raw is None:\n      raise TransportFailure("no length")\n',
         )
      ],
   },
   {
      "gate": f"{DOWNLOAD_GATES}::test_a_body_that_stops_midway_leaves_nothing",
      "defect": "the temporary file is left behind on a failure",
      "edits": [(DOWNLOADS, "            _discard(temporary)", "            pass")],
   },
   {
      "gate": f"{DOWNLOAD_GATES}::test_a_refused_url_raises_not_found_and_writes_nothing",
      "defect": "an error status is saved as the rendition",
      "edits": [(DOWNLOADS, "   if status_code == SUCCESS_STATUS:\n      return\n", "   return\n")],
   },
   {
      "gate": f"{DOWNLOAD_GATES}::test_an_encoded_body_is_refused",
      "defect": "an encoded body is saved as the rendition",
      "edits": [(DOWNLOADS, "if encoding not in UNENCODED:", "if False:")],
   },
   {
      "gate": f"{DOWNLOAD_GATES}::test_a_url_that_is_not_https_is_refused_before_anything_is_sent",
      "defect": "a rendition URL in the clear is fetched",
      "edits": [(CDN, 'if scheme != "https":', "if False:")],
   },
   {
      "gate": f"{DOWNLOAD_GATES}::test_an_async_download_sends_no_cookie_to_the_cdn",
      "defect": "the download drops the referer the measured fetches carried",
      "edits": [(CDN, '"referer": MEDIA_REFERER, ', "")],
   },
   {
      "gate": f"{DOWNLOAD_GATES}::test_the_family_pin_refuses_a_host_outside_the_cdn",
      "defect": "the family pin lets every host through",
      "edits": [(TRANSPORT, "is_allowed = is_in_the_family and is_https", "is_allowed = True")],
   },
   {
      "gate": f"{DOWNLOAD_GATES}::test_the_family_pin_refuses_a_host_outside_the_cdn",
      "defect": "the family pin matches without a label boundary",
      "edits": [
         (
            TRANSPORT,
            'host.endswith(f".{self._allowed_host_family}")',
            'host.endswith(f"{self._allowed_host_family}")',
         )
      ],
   },
   {
      "gate": f"{DOWNLOAD_GATES}::test_the_family_pin_refuses_a_host_outside_the_cdn",
      "defect": "the family pin lets plain http through",
      "edits": [(TRANSPORT, 'is_https = request.url.scheme == "https"', "is_https = True")],
   },
   {
      "gate": f"{DOWNLOAD_GATES}::test_the_family_pin_refuses_a_host_outside_the_cdn",
      "defect": "the family pin is never installed",
      "edits": [(TRANSPORT, "      if pins_a_family:\n", "      if False:\n")],
   },
   {
      "gate": f"{DOWNLOAD_GATES}::test_the_cdn_transport_never_follows_a_redirect",
      "defect": "the stream follows redirects",
      "edits": [
         (
            TRANSPORT,
            "response = await self._client.send(built, stream=True, follow_redirects=False)",
            "response = await self._client.send(built, stream=True, follow_redirects=True)",
         )
      ],
   },
   {
      "gate": f"{DOWNLOAD_GATES}::test_a_cookieless_stream_refuses_a_cookie_header",
      "defect": "the stream never checks for a cookie header",
      "edits": [
         (
            TRANSPORT,
            'undecoded.\n      """\n\n      self._refuse_a_cookie_header(request)\n',
            'undecoded.\n      """\n\n',
         )
      ],
   },
   {
      "gate": f"{DOWNLOAD_GATES}::test_a_transport_takes_one_pin_or_the_other",
      "defect": "a transport given both pins honours one quietly",
      "edits": [(TRANSPORT, "      if names_both_pins:\n", "      if False:\n")],
   },
   {
      "gate": f"{DOWNLOAD_GATES}::test_an_async_download_sends_no_cookie_to_the_cdn",
      "defect": "the client's CDN pool is handed the account's cookie jar",
      "edits": [
         (
            CLIENT,
            "      max_connections=CDN_MAX_CONNECTIONS,\n      cookieless=True,\n",
            "      max_connections=CDN_MAX_CONNECTIONS,\n      cookies=cookies_for(session),\n",
         )
      ],
   },
   {
      "gate": f"{DOWNLOAD_GATES}::test_the_client_refuses_a_rendition_outside_the_cdn",
      "defect": "the client's CDN pool is unpinned",
      "edits": [(CLIENT, "      allowed_host_family=CDN_HOST_FAMILY,\n", "")],
   },
   {
      "gate": f"{DOWNLOAD_GATES}::test_the_client_cdn_pool_is_cookieless_pinned_and_bounded",
      "defect": "the client's CDN pool is unbounded",
      "edits": [(CLIENT, "      max_connections=CDN_MAX_CONNECTIONS,\n", "")],
   },
   {
      "gate": f"{DOWNLOAD_GATES}::test_the_client_cdn_pool_is_cookieless_pinned_and_bounded",
      "defect": "the pool limit never reaches the httpx transport that builds the pool",
      "edits": [(TRANSPORT, "            limits=_limits(max_connections),\n", "")],
   },
   {
      "gate": f"{DOWNLOAD_GATES}::test_closing_the_client_closes_the_cdn_pool",
      "defect": "the CDN pool is never closed",
      "edits": [(CLIENT, "                  await self._cdn.aclose()", "                  pass")],
   },
   {
      "gate": f"{DOWNLOAD_GATES}::test_a_scoped_client_downloads_through_the_same_cdn_pool",
      "defect": "a scoped client builds a CDN pool of its own",
      "edits": [
         (
            CLIENT,
            "      scoped._cdn = self._cdn\n",
            "      scoped._cdn = cdn_transport_for(self._session)\n",
         )
      ],
   },
   {
      "gate": f"{DOWNLOAD_GATES}::test_a_download_takes_no_turn_from_the_account_pacer",
      "defect": "a download waits for a pacer slot",
      "edits": [
         (
            NAMESPACE,
            "      return await download_rendition(\n",
            "      async with client._sender.pacer.slot(client._sender.pacing):\n"
            "         pass\n\n"
            "      return await download_rendition(\n",
         )
      ],
   },
   {
      "gate": FORWARDS,
      "defect": "the blocking download drops overwrite",
      "edits": [
         (
            NAMESPACE,
            "self._client._impl.media.download(rendition, path, overwrite=overwrite),",
            "self._client._impl.media.download(rendition, path),",
         )
      ],
   },
   {
      "gate": SEAM_NOTE,
      "defect": "the blocking download's seam note names another method",
      "edits": [
         (
            NAMESPACE,
            'operation="SyncClient.media.download",',
            'operation="SyncClient.media.by_code",',
         )
      ],
   },
   {
      "gate": REACHES_CORE,
      "defect": "the async download reaches no core capability",
      "edits": [
         (
            NAMESPACE,
            "      return await download_rendition(\n         client._cdn,",
            "      raise NotImplementedError\n\n"
            "      return await download_rendition(\n         client._cdn,",
         )
      ],
   },
]


def run_gate(gate: str) -> subprocess.CompletedProcess[str]:
   """Run one gate in a subprocess that cannot read a stale `.pyc`.

   The reason is the one ``verify_cli_gates.py`` records: CPython validates cached bytecode
   against the source's size and its mtime in whole seconds, so a same-length edit applied and
   undone inside one second is invisible to that check.
   """

   environment = dict(os.environ)
   environment["PYTHONDONTWRITEBYTECODE"] = "1"

   for cached in ENGINE.glob("**/__pycache__"):
      shutil.rmtree(cached, ignore_errors=True)

   return subprocess.run(
      [sys.executable, "-B", "-m", "pytest", gate, "-q", "--no-header", "-p", "no:cacheprovider"],
      cwd=ENGINE,
      capture_output=True,
      text=True,
      env=environment,
   )


def apply_edits(edits: list[tuple[str, str, str]], gate: str) -> dict[Path, str]:
   originals: dict[Path, str] = {}

   try:
      for relative, find, replace in edits:
         path = ENGINE / relative
         originals.setdefault(path, path.read_text(encoding="utf-8"))
         current = path.read_text(encoding="utf-8")

         occurrences = current.count(find)

         if occurrences != 1:
            raise SystemExit(
               f"mutation anchor found {occurrences} times in {relative} for {gate}, "
               "expected exactly once"
            )

         path.write_text(current.replace(find, replace, 1), encoding="utf-8")
   except BaseException:
      restore(originals)

      raise

   return originals


def restore(originals: dict[Path, str]) -> None:
   for path, original in originals.items():
      path.write_text(original, encoding="utf-8")


def main() -> int:
   results = []

   for mutation in MUTATIONS:
      gate = str(mutation["gate"])
      edits = mutation["edits"]
      assert isinstance(edits, list)

      originals = apply_edits(edits, gate)

      try:
         mutated = run_gate(gate)
      finally:
         restore(originals)

      restored = run_gate(gate)

      results.append(
         {
            "gate": gate,
            "defect": mutation["defect"],
            "mutated_files": sorted({relative for relative, _, _ in edits}),
            "red_under_mutation": mutated.returncode != 0,
            "green_after_restore": restored.returncode == 0,
            "mutated_tail": mutated.stdout.strip().splitlines()[-1:],
         }
      )

   every_gate_fired = bool(results) and all(
      entry["red_under_mutation"] and entry["green_after_restore"] for entry in results
   )

   LOG_DIR.mkdir(parents=True, exist_ok=True)
   stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
   log_path = LOG_DIR / f"mutation-media-{stamp}.json"
   log_path.write_text(
      json.dumps({"every_gate_fired": every_gate_fired, "gates": results}, indent=2) + "\n",
      encoding="utf-8",
   )

   for entry in results:
      fired = entry["red_under_mutation"] and entry["green_after_restore"]
      status = "red then green" if fired else "DID NOT FIRE"
      print(f"{status}: {entry['gate'].split('::')[1]}  ({entry['defect']})")

   print(f"log written to {log_path}")

   return 0 if every_gate_fired else 1


if __name__ == "__main__":
   raise SystemExit(main())
