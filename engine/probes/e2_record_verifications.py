"""No requests. Records the E2 replay probes' passes into the local knowledge base.

Reads the newest log of each ``e2_*`` probe named below from ``../logs/`` and, for every replay
whose label maps to a hypothesis finding, calls the skill's ``verify_finding.py`` once with the
status, the size, the roots and the log's path. A replay that answered 200 with a non-null root
is a pass, one that failed or answered only null roots is a fail. The mapping from a probe's
labels to finding ids is the one table here, so a rerun of a probe is recorded the same way.

Run it from the repository root with the reverse-engineer run id the replays belong to:

   uv run --no-project python engine/probes/e2_record_verifications.py run-2026-09-27-014102

Name probe kinds after the run id, such as ``e2-next-pages``, to record only those logs.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
LOGS = REPOSITORY / "engine" / "logs"
VERIFY = REPOSITORY / "skills" / "reverse-engineer" / "scripts" / "verify_finding.py"

LABEL_TO_FINDING = {
   "e2-profile-tabs": {
      "posts grid next page": "profile-posts-grid-next-page",
      "highlights tray next page": "profile-highlights-tray-next-page",
      "suggested beside the profile": "profile-suggested-users-on-demand",
      "suggested accounts": "home-suggested-accounts",
   },
   "e2-follow-lists": {
      "followers page two": "read-an-account-s-followers",
      "followers page": "read-an-account-s-followers",
      "show_many": "friendship-statuses-for-many-accounts",
   },
   "e2-post-depth": {
      "replies next page": "read-comment-replies-next-page",
      "replies": "read-comment-replies",
      "likers": "read-a-post-s-likers",
      "post by media pk": "read-a-post-by-media-id",
      "post modal context": "read-a-post-modal-context",
      "more posts from the account": "read-more-posts-from-an-account",
   },
   "e2-stories": {
      "own highlight": "read-one-account-s-stories-or-a-highlight",
      "own reel": "read-one-account-s-stories-or-a-highlight",
      "third party reel": "read-one-account-s-stories-or-a-highlight",
      "highlights gallery": "read-the-stories-gallery",
   },
   "e2-own-account": {
      "pending follow requests": "pending-follow-requests",
      "activity feed": "activity-feed-inbox",
      "saved collections next page": "read-saved-collections-next-page",
      "saved collections": "read-saved-collections",
   },
   "e2-discovery-feeds": {
      "explore grid": "read-the-explore-grid",
      "location header": "read-a-location-s-info",
      "location grid next page": "read-a-location-page-tab-next-page",
      "location grid": "read-a-location-page-tab",
      "new feed posts check": "check-for-new-feed-posts",
   },
   "e2-search": {
      "recent searches": "read-recent-searches",
      "non-personalised typeahead": "search-typeahead-non-personalised",
      "hashtag header": "read-a-hashtag-header",
   },
   "e2-next-pages": {
      "posts grid next page": "profile-posts-grid-next-page",
      "highlights tray next page": "profile-highlights-tray-next-page",
      "replies next page": "read-comment-replies-next-page",
      "replies": "read-comment-replies",
   },
   "e2-page-models": {
      "post page first comments": "read-a-post-page-first-comments",
      "liked by line": "read-the-liked-by-line",
      "ad responses tab": "read-whether-the-ad-responses-tab-shows",
      "suggested threadline reels": "read-suggested-threads-reels",
   },
   "e2-capture-replays": {
      "profile reels tab": "read-a-profile-s-reels-tab",
      "profile tagged tab": "read-a-profile-s-tagged-tab",
      "following first page": "read-an-account-s-following",
      "following next page": "read-an-account-s-following",
      "personalised typeahead": "search-typeahead-personalised-as-sent",
      "keyword results": "read-keyword-search-results",
      "reels feed first page": "read-the-reels-tab-first-page",
      "reels feed next page": "read-the-reels-tab-next-page",
      "saved collections tab": "read-saved-posts",
      "all saved posts": "read-all-saved-posts",
      "close friends list": "read-the-close-friends-list",
      "post page document": "read-a-post-page-document",
   },
   "e2-last-reads-replay": {
      "explore grid next page": "read-the-explore-grid-next-page",
      "audio page next page": "read-an-audio-page-next-page",
      "audio page": "read-an-audio-page",
      "mutual followers page": "read-mutual-followers",
   },
}


def newest_log(kind: str) -> Path:
   candidates = sorted(LOGS.glob(f"{kind}-2*.json"))

   return candidates[-1]


def finding_for(label: str, table: dict[str, str]) -> str | None:
   for prefix, finding in table.items():
      if label.startswith(prefix):
         return finding

   return None


def describe(replay: dict, log: Path) -> tuple[str, str]:
   failed = replay.get("failed_with")
   kept_partial = replay.get("partial_answer_kept", False)
   null_roots = replay.get("null_roots") or []
   roots = replay.get("root_fields") or replay.get("top_keys") or []
   every_root_null = bool(roots) and len(null_roots) == len(roots)
   is_pass = replay.get("status") == 200 and (not failed or kept_partial) and not every_root_null
   partial = ""

   if kept_partial:
      partial = f", {replay.get('errors_count')} field errors beside the data"

   detail = (
      f"engine replay '{replay['label']}': {replay.get('status')}, {replay.get('bytes')} bytes, "
      f"roots {', '.join(roots[:6]) or 'none'}{partial}, "
      f"log {log.relative_to(REPOSITORY / 'engine')}"
   )

   return ("pass" if is_pass else "fail"), detail


def main(run_id: str, kinds: list[str]) -> int:
   recorded = 0

   for kind, table in LABEL_TO_FINDING.items():
      if kinds and kind not in kinds:
         continue

      log = newest_log(kind)
      report = json.loads(log.read_text(encoding="utf-8"))

      for replay in report["replays"]:
         finding = finding_for(replay["label"], table)

         if finding is None:
            continue

         result, detail = describe(replay, log)
         subprocess.run(
            [
               sys.executable,
               str(VERIFY),
               "--id",
               finding,
               "--run",
               run_id,
               "--result",
               result,
               "--detail",
               detail,
            ],
            check=True,
         )
         recorded += 1
         print(f"{finding}: {result}")

   print(f"{recorded} verifications recorded")

   return 0


if __name__ == "__main__":
   sys.exit(main(sys.argv[1], sys.argv[2:]))
