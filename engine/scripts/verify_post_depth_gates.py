"""Break E2 batch 4, post depth, watch each gate go red, restore.

Same harness and same rule as ``verify_follow_lists_gates.py``: one mutation per entry below,
only the gate that should catch it is run, every anchor must be found exactly once, and every
file is restored from an in-memory copy in a ``finally`` so an interrupted run cannot leave a
mutation behind.

The mutations cover the reply page's mapper and terminator, both reply requests, the likers,
the post read by media pk and what it leaves empty, the more posts from the author, the location,
tags and collaborators every post read now carries, both reply walks, the commands, the canary's
new steps and the namespace parity gates for the new methods.

Run from ``engine/`` with ``uv run python scripts/verify_post_depth_gates.py``. Writes its
result to ``engine/logs/``.
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
REQUESTS = "dumpstagram/_private/web/requests/media.py"
DOCUMENTS = "dumpstagram/_private/web/documents/media.py"
CANARY = "dumpstagram/_private/web/canary.py"
CORE_POSTS = "dumpstagram/_core/posts.py"
CORE_COMMENTS = "dumpstagram/_core/comments.py"
NAMESPACE = "dumpstagram/namespaces/media.py"
COMMANDS_MEDIA = "dumpstagram/_cli/commands/media.py"
COMMANDS = "dumpstagram/_cli/commands/post_depth.py"
GATES = "tests/test_post_depth.py"
DOCTOR_GATES = "tests/test_doctor.py"
PARITY_GATES = "tests/test_facade_parity.py"


def gate(name: str) -> str:
   return f"{GATES}::{name}"


def parity(name: str, qualified: str) -> str:
   return f"{PARITY_GATES}::{name}[{qualified}]"


REPLY_MAP = gate("test_a_reply_page_maps_every_reply_in_order_with_its_own_terminator")
REPLY_SHAPE = gate("test_a_reply_is_a_comment_with_no_count_of_its_own_read_from_its_own_keys")
REPLY_PARENT = gate("test_a_reply_without_its_parent_is_a_schema_change")
FIRST_REQUEST = gate("test_the_first_reply_page_sends_the_variables_replayed_live")
NEXT_REQUEST = gate("test_a_later_reply_page_is_the_pagination_query_on_the_cursor")
REPLY_REFUSALS = gate("test_replies_refuse_the_id_form_and_a_comment_id_that_is_not_digits")
ASYNC_WALK = gate(
   "test_the_async_reply_walk_crosses_to_the_next_page_query_on_the_first_pages_cursor"
)
BLOCKING_WALK = gate("test_the_blocking_reply_walk_crosses_to_the_next_page_query")
LIKERS_MAP = gate("test_likers_are_list_rows_in_the_upstream_order_with_every_flag_they_carry")
LIKERS_AND_STRIP = gate("test_the_likers_and_the_strip_send_the_variables_replayed_live")
STRIP_MAP = gate("test_the_strip_maps_each_post_as_a_thumbnail_from_its_own_keys")
BY_ID_GAPS = gate("test_a_post_read_by_media_pk_leaves_empty_what_its_item_does_not_carry")
BY_ID_REQUEST = gate("test_a_post_read_by_media_pk_is_the_media_id_query_on_its_own_path")
REEL_BY_ID = gate(
   "test_a_reel_read_by_media_pk_maps_and_an_original_sound_without_its_flag_is_unknown"
)
SHORTCODE_STRICT = gate(
   "test_a_post_read_by_shortcode_still_refuses_an_author_without_the_picture_key"
)
HOME_FIELDS = gate(
   "test_a_home_post_carries_its_location_tags_and_collaborators_from_their_own_keys"
)
TAG_BY_ID = gate("test_a_tag_is_read_by_its_id_because_some_tags_carry_no_pk")
NULL_OR_ABSENT = gate("test_a_null_is_no_tags_or_collaborators_and_an_absent_key_is_unknown")
LOCATION_PK = gate("test_a_location_pk_sent_as_a_number_reads_as_a_string")
DUMPSTA_REPLIES = gate(
   "test_dumpsta_replies_walks_on_the_pages_own_cursor_and_stops_on_its_terminator"
)
DUMPSTA_BY_ID = gate("test_dumpsta_post_by_id_reads_by_the_pk_and_refuses_a_shortcode")
DUMPSTA_LISTS = gate("test_dumpsta_likers_and_more_from_author_print_every_account_and_post")
CANARY_REPLIES = (
   f"{DOCTOR_GATES}::test_the_replies_are_replayed_on_a_learned_comment_and_skipped_without_one"
)

MUTATIONS: list[dict[str, object]] = [
   {
      "gate": REPLY_MAP,
      "defect": "the reply page drops its cursor",
      "edits": [
         (
            PARSE,
            "Page(items=replies, has_next_page=has_next_page, end_cursor=end_cursor)",
            "Page(items=replies, has_next_page=has_next_page, end_cursor=None)",
         )
      ],
   },
   {
      "gate": REPLY_MAP,
      "defect": "the reply page says it is the last one",
      "edits": [
         (
            PARSE,
            "Page(items=replies, has_next_page=has_next_page, end_cursor=end_cursor)",
            "Page(items=replies, has_next_page=False, end_cursor=end_cursor)",
         )
      ],
   },
   {
      "gate": REPLY_MAP,
      "defect": "the reply page drops its first reply",
      "edits": [
         (
            PARSE,
            "Page(items=replies, has_next_page=has_next_page, end_cursor=end_cursor)",
            "Page(items=replies[1:], has_next_page=has_next_page, end_cursor=end_cursor)",
         )
      ],
   },
   {
      "gate": REPLY_SHAPE,
      "defect": "a reply's null count is required, as on the comment page",
      "edits": [
         (
            PARSE,
            'reply_count=_optional_integer(node, "child_comment_count", path),',
            'reply_count=_required_integer(node, "child_comment_count", path),',
         )
      ],
   },
   {
      "gate": REPLY_SHAPE,
      "defect": "a reply's like count is not read",
      "edits": [
         (
            PARSE,
            'like_count=_required_integer(node, "comment_like_count", path),\n'
            '      reply_count=_optional_integer(node, "child_comment_count", path),',
            "like_count=0,\n"
            '      reply_count=_optional_integer(node, "child_comment_count", path),',
         )
      ],
   },
   {
      "gate": REPLY_SHAPE,
      "defect": "a reply's like state defaults to liked",
      "edits": [
         (
            PARSE,
            'parent_comment_id=_required_string(node, "parent_comment_id", path),\n'
            '      has_liked=_required_flag(node, "has_liked_comment", path),',
            'parent_comment_id=_required_string(node, "parent_comment_id", path),\n'
            "      has_liked=True,",
         )
      ],
   },
   {
      "gate": REPLY_PARENT,
      "defect": "a reply without its parent is passed on",
      "edits": [
         (
            PARSE,
            'parent_comment_id=_required_string(node, "parent_comment_id", path),',
            'parent_comment_id=_optional_string(node, "parent_comment_id", path)'
            ' if "parent_comment_id" in node else None,',
         )
      ],
   },
   {
      "gate": FIRST_REQUEST,
      "defect": "the first reply page asks for the later pages' size",
      "edits": [(REQUESTS, "REPLIES_FIRST_PAGE_SIZE = 3\n", "REPLIES_FIRST_PAGE_SIZE = 10\n")],
   },
   {
      "gate": FIRST_REQUEST,
      "defect": "the replies are asked for newest first",
      "edits": [(REQUESTS, '"is_chronological": True,', '"is_chronological": False,')],
   },
   {
      "gate": NEXT_REQUEST,
      "defect": "a later reply page is sent as the first page query",
      "edits": [
         (
            REQUESTS,
            "query = COMMENT_REPLIES_NEXT_PAGE if is_a_later_page else COMMENT_REPLIES",
            "query = COMMENT_REPLIES",
         )
      ],
   },
   {
      "gate": NEXT_REQUEST,
      "defect": "a later reply page keeps the first page's size",
      "edits": [(REQUESTS, "REPLIES_NEXT_PAGE_SIZE = 10\n", "REPLIES_NEXT_PAGE_SIZE = 3\n")],
   },
   {
      "gate": REPLY_REFUSALS,
      "defect": "a comment id that is not digits reaches the request",
      "edits": [(CORE_COMMENTS, "   if not is_a_comment_id(comment_id):\n", "   if False:\n")],
   },
   {
      "gate": ASYNC_WALK,
      "defect": "the async walk passes no cursor",
      "edits": [
         (
            NAMESPACE,
            "lambda cursor: self.replies(post_pk, comment_id, after=cursor)",
            "lambda cursor: self.replies(post_pk, comment_id, after=None)",
         )
      ],
   },
   {
      "gate": BLOCKING_WALK,
      "defect": "the blocking walk passes no cursor",
      "edits": [
         (
            NAMESPACE,
            "client._impl.media.replies(post_pk, comment_id, after=cursor),",
            "client._impl.media.replies(post_pk, comment_id, after=None),",
         )
      ],
   },
   {
      "gate": LIKERS_MAP,
      "defect": "the likers drop their first account",
      "edits": [
         (
            PARSE,
            '_account_row(node, f"{connection_path}.nodes[{index}]") for index, node in '
            "enumerate(nodes)",
            '_account_row(node, f"{connection_path}.nodes[{index}]") for index, node in '
            "enumerate(nodes[1:])",
         )
      ],
   },
   {
      "gate": LIKERS_AND_STRIP,
      "defect": "the likers are asked for by the id form",
      "edits": [(REQUESTS, '{"media_id": post_pk},', '{"media_id": f"{post_pk}_0"},')],
   },
   {
      "gate": LIKERS_AND_STRIP,
      "defect": "the strip asks for another count",
      "edits": [(REQUESTS, "MORE_FROM_AUTHOR_COUNT = 6\n", "MORE_FROM_AUTHOR_COUNT = 12\n")],
   },
   {
      "gate": LIKERS_AND_STRIP,
      "defect": "the strip is keyed on the viewer rather than the author",
      "edits": [
         (REQUESTS, '"media_owner_id": author_id,', '"media_owner_id": session.ds_user_id,')
      ],
   },
   {
      "gate": LIKERS_AND_STRIP,
      "defect": "the strip's root field header names another root",
      "edits": [
         (
            DOCUMENTS,
            '   root_field="xdt_api__v1__profile_timeline",\n',
            '   root_field="xdt_api__v1__feed__user_timeline_graphql_connection",\n',
         )
      ],
   },
   {
      "gate": LIKERS_AND_STRIP,
      "defect": "the likers read takes the id form",
      "edits": [
         (
            CORE_POSTS,
            "   refuse_what_is_not_a_media_pk(post_pk)\n\n"
            "   async def attempt() -> tuple[ProfileSummary, ...]:\n",
            "   async def attempt() -> tuple[ProfileSummary, ...]:\n",
         )
      ],
   },
   {
      "gate": LIKERS_AND_STRIP,
      "defect": "the strip takes a username",
      "edits": [(CORE_POSTS, "   refuse_what_is_not_a_user_id(author_id)\n", "")],
   },
   {
      "gate": STRIP_MAP,
      "defect": "a thumbnail's author is read off the post",
      "edits": [
         (
            PARSE,
            'author_id=_required_string(author, "pk", author_path),',
            'author_id=_required_string(node, "pk", path),',
         )
      ],
   },
   {
      "gate": STRIP_MAP,
      "defect": "a thumbnail's slide count is dropped",
      "edits": [
         (
            PARSE,
            'carousel_media_count=_optional_integer(node, "carousel_media_count", path),\n'
            "      images=_images(node, path),\n   )\n\n\ndef parse_more_from_author",
            "carousel_media_count=None,\n"
            "      images=_images(node, path),\n   )\n\n\ndef parse_more_from_author",
         )
      ],
   },
   {
      "gate": BY_ID_REQUEST,
      "defect": "the media id variable is sent in the other case",
      "edits": [(REQUESTS, '{"mediaId": post_pk},', '{"media_id": post_pk},')],
   },
   {
      "gate": BY_ID_REQUEST,
      "defect": "the post read by media pk is sent to the other path",
      "edits": [
         (
            DOCUMENTS,
            '   url=GRAPHQL_QUERY_URL,\n   root_field="xdt_api__v1__media__media_id_web_info",\n',
            '   root_field="xdt_api__v1__media__media_id_web_info",\n',
         )
      ],
   },
   {
      "gate": BY_ID_REQUEST,
      "defect": "the answer is read with the shortcode read's mapper",
      "edits": [
         (
            CORE_POSTS,
            "return parse_post_by_media_id(classify(response))",
            "return parse_post_detail(classify(response))",
         )
      ],
   },
   {
      "gate": BY_ID_GAPS,
      "defect": "the item's slides are read as full slides",
      "edits": [
         (
            PARSE,
            "      location=_location(node, path),\n"
            "      user_tags=_user_tags(node, path),\n"
            "      collaborators=_collaborators(node, path),\n"
            "   )\n\n\ndef parse_reply(",
            "      carousel_children=_carousel_children(node, path),\n"
            "      location=_location(node, path),\n"
            "      user_tags=_user_tags(node, path),\n"
            "      collaborators=_collaborators(node, path),\n"
            "   )\n\n\ndef parse_reply(",
         )
      ],
   },
   {
      "gate": BY_ID_GAPS,
      "defect": "the author is read as if it carried the picture key",
      "edits": [
         (
            PARSE,
            "author=_post_author(node, path, hd_picture_if_carried=True),",
            "author=_post_author(node, path),",
         )
      ],
   },
   {
      "gate": BY_ID_GAPS,
      "defect": "an image description the item does not carry reads as empty text",
      "edits": [
         (PARSE, "accessibility_caption=accessibility_caption,", 'accessibility_caption="",')
      ],
   },
   {
      "gate": REEL_BY_ID,
      "defect": "the post read by media pk requires the original sound's explicit flag",
      "edits": [
         (
            PARSE,
            "audio=_audio(node, path, original_sound_without_flag_is_unknown=True),",
            "audio=_audio(node, path),",
         )
      ],
   },
   {
      "gate": REEL_BY_ID,
      "defect": "every read lets the original sound's explicit flag go missing",
      "edits": [
         (
            PARSE,
            "*, original_sound_without_flag_is_unknown: bool = False",
            "*, original_sound_without_flag_is_unknown: bool = True",
         )
      ],
   },
   {
      "gate": SHORTCODE_STRICT,
      "defect": "every post read lets the author's picture key go missing",
      "edits": [
         (
            PARSE,
            "node: dict[str, Any], path: str, *, hd_picture_if_carried: bool = False",
            "node: dict[str, Any], path: str, *, hd_picture_if_carried: bool = True",
         )
      ],
   },
   {
      "gate": NULL_OR_ABSENT,
      "defect": "absent collaborators read as none",
      "edits": [
         (
            PARSE,
            '   if "coauthor_producers" not in node:\n      return None\n',
            '   if "coauthor_producers" not in node:\n      return ()\n',
         )
      ],
   },
   {
      "gate": NULL_OR_ABSENT,
      "defect": "null collaborators read as unknown",
      "edits": [
         (
            PARSE,
            '   raw = node["coauthor_producers"]\n\n   if raw is None:\n      return ()\n',
            '   raw = node["coauthor_producers"]\n\n   if raw is None:\n      return None\n',
         )
      ],
   },
   {
      "gate": NULL_OR_ABSENT,
      "defect": "absent tags read as none",
      "edits": [
         (
            PARSE,
            '   if "usertags" not in node:\n      return None\n',
            '   if "usertags" not in node:\n      return ()\n',
         )
      ],
   },
   {
      "gate": TAG_BY_ID,
      "defect": "a tagged account is read by pk",
      "edits": [
         (
            PARSE,
            'id=_required_string(user, "id", path),',
            'id=_required_string(user, "pk", path),',
         )
      ],
   },
   {
      "gate": HOME_FIELDS,
      "defect": "a tag's position is dropped",
      "edits": [(PARSE, "position=_tag_position(entry, path),", "position=None,")],
   },
   {
      "gate": HOME_FIELDS,
      "defect": "a slide's tags are dropped",
      "edits": [
         (
            PARSE,
            "      user_tags=_user_tags(node, path),\n   )\n\n\ndef _carousel_children(",
            "      user_tags=None,\n   )\n\n\ndef _carousel_children(",
         )
      ],
   },
   {
      "gate": HOME_FIELDS,
      "defect": "the first collaborator is dropped",
      "edits": [
         (
            PARSE,
            "for index, producer in enumerate(raw)",
            "for index, producer in enumerate(raw[1:])",
         )
      ],
   },
   {
      "gate": HOME_FIELDS,
      "defect": "a post's location is dropped",
      "edits": [(PARSE, '   raw = node.get("location")\n', "   raw = None\n")],
   },
   {
      "gate": LOCATION_PK,
      "defect": "a location pk sent as a number is refused",
      "edits": [
         (
            PARSE,
            "   if is_a_number:\n      return str(raw)\n",
            "   if False:\n      return str(raw)\n",
         )
      ],
   },
   {
      "gate": LOCATION_PK,
      "defect": "latitude is read from the longitude",
      "edits": [
         (
            PARSE,
            'lat=_coordinate(raw, "lat", location_path),',
            'lat=_coordinate(raw, "lng", location_path),',
         )
      ],
   },
   {
      "gate": DUMPSTA_REPLIES,
      "defect": "the command reads past a last page",
      "edits": [
         (
            COMMANDS,
            "      reached_the_last_page = not page.has_next_page\n",
            "      reached_the_last_page = False\n",
         )
      ],
   },
   {
      "gate": DUMPSTA_BY_ID,
      "defect": "post --by-id reads by the shortcode",
      "edits": [
         (
            COMMANDS_MEDIA,
            "post = client.media.by_id(media_pk_argument(arguments.code))",
            "post = client.post(arguments.code)",
         )
      ],
   },
   {
      "gate": DUMPSTA_BY_ID,
      "defect": "post --by-id passes a shortcode on as a pk",
      "edits": [(COMMANDS_MEDIA, "      return media_pk(value)\n", "      return value\n")],
   },
   {
      "gate": DUMPSTA_LISTS,
      "defect": "more-from-author takes a username",
      "edits": [
         (
            COMMANDS,
            'metavar="AUTHOR_ID", type=account_id,',
            'metavar="AUTHOR_ID",',
         )
      ],
   },
   {
      "gate": CANARY_REPLIES,
      "defect": "the canary picks a comment with no replies",
      "edits": [
         (
            CANARY,
            "      has_replies = (comment.reply_count or 0) > 0\n",
            "      has_replies = True\n",
         )
      ],
   },
   {
      "gate": CANARY_REPLIES,
      "defect": "the canary's reply next page is sent on another cursor",
      "edits": [
         (
            CANARY,
            "      arguments.replies_cursor = page.end_cursor\n",
            '      arguments.replies_cursor = "C0"\n',
         )
      ],
   },
   {
      "gate": CANARY_REPLIES,
      "defect": "the canary keys the strip on the post rather than its author",
      "edits": [
         (
            CANARY,
            "         arguments.author_id = item.post.author.id\n",
            "         arguments.author_id = item.post.pk\n",
         )
      ],
   },
   {
      "gate": parity(
         "test_a_namespace_method_reaches_the_core_capability_the_table_names", "media.replies"
      ),
      "defect": "replies reaches the comment page's core function",
      "edits": [
         (
            NAMESPACE,
            "         read_replies_page(\n"
            "            client._sender,\n"
            "            client._session,\n"
            "            post_pk,\n"
            "            comment_id,\n",
            "         read_comment_page(\n"
            "            client._sender,\n"
            "            client._session,\n"
            "            post_pk,\n",
         )
      ],
   },
   {
      "gate": parity(
         "test_a_namespace_method_reaches_the_core_capability_the_table_names", "media.by_id"
      ),
      "defect": "by_id reaches the shortcode read",
      "edits": [
         (
            NAMESPACE,
            "         read_post_by_id(\n            client._sender,\n",
            "         read_post(\n            client._sender,\n",
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
   log_path = LOG_DIR / f"mutation-post-depth-{stamp}.json"
   log_path.write_text(
      json.dumps({"every_gate_fired": every_gate_fired, "gates": results}, indent=2) + "\n",
      encoding="utf-8",
   )

   for entry in results:
      fired = entry["red_under_mutation"] and entry["green_after_restore"]
      status = "red then green" if fired else "DID NOT FIRE"
      print(f"{status}: {entry['gate'].split('::')[1]}  ({entry['defect']})")

   fired_count = sum(
      1 for entry in results if entry["red_under_mutation"] and entry["green_after_restore"]
   )
   print(f"fired {fired_count} of {len(results)}")
   print(f"log written to {log_path}")

   return 0 if every_gate_fired else 1


if __name__ == "__main__":
   raise SystemExit(main())
