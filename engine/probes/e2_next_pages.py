"""Read only. Ran on 2026-09-27, 10 spent. Nine requests, and up to four more, conditional.

The E2 next page reads the owner's own account could not reach on 2026-09-27, because his grid
fits one page, his highlights tray holds one highlight, and no reply thread on the post
``e2_post_depth.py`` chose ran past one page. Each is read here on a public account the owner's
home timeline already shows, which W43 allows, and each hypothesis read is replayed twice.

   1  the inbox document, for fresh tokens (the bootstrap)
   2  the home timeline's first page, a verified read, for an author and a post
   3  the author's grid first page, the verified PolarisProfilePostsQuery at twelve
   4  the grid's next page, PolarisProfilePostsTabContentQuery_connection, twice
   6  the author's highlights tray, the verified PolarisProfileStoryHighlightsTrayContentQuery
   7  the most commented post's first comment page, a verified read
   8  the replies under its comment with the most replies, PolarisPostChildCommentsQuery, once
   9  the replies' next page, PolarisPostCommentsChildrenPaginationtQuery, twice when there is one

Conditional: the tray's next page, ProfileStoryHighlightsTrayContentQuery_connection, twice when
the author's tray has one, and the second replies page's pair when the declared nine are spent.
The author is the first one on the timeline whose account is public. No username, caption,
comment or id reaches the log beyond the four character prefix of a first item.

Run it from `engine/` with:

   uv run python probes/e2_next_pages.py
"""

from __future__ import annotations

import asyncio
import sys

from _e2_support import E2Replay, dig, id_prefix, page_info_of, run_probe
from e2_post_depth import REPLIES_ROOT, pick_post
from e2_profile_tabs import GRID_PAGE_SIZE, PROFILE_POSTS_TEMPLATE

from dumpstagram._private.web.bootstrap import ORIGIN
from dumpstagram._private.web.documents.profiles import PROFILE_HIGHLIGHTS, PROFILE_POSTS
from dumpstagram._private.web.requests.common import build_graphql_request
from dumpstagram._private.web.requests.feed import build_feed_page_request
from dumpstagram._private.web.requests.media import build_comment_page_request
from dumpstagram._private.web.requests.profiles import _profile_posts_variables

PLANNED = 9
CONDITIONAL = 4
GRID_ROOT = "xdt_api__v1__feed__user_timeline_graphql_connection"
COMMENTS_ROOT = "xdt_api__v1__media__media_id__comments__connection"
LOGGED_IN = {"__relay_internal__pv__PolarisIsLoggedInrelayprovider": True}


def public_author(feed: object) -> dict[str, object] | None:
   edges = dig(feed, "data", "xdt_api__v1__feed__timeline__connection", "edges") or []

   for edge in edges:
      author = dig(edge, "node", "media", "user")
      is_public = isinstance(author, dict) and author.get("is_private") is False

      if is_public and author.get("username") and author.get("pk"):
         return author

   return None


def comment_with_most_replies(page: object) -> dict[str, object] | None:
   edges = dig(page, "data", COMMENTS_ROOT, "edges") or []
   comments = [dig(edge, "node") for edge in edges]
   comments = [comment for comment in comments if isinstance(comment, dict)]

   if not comments:
      return None

   return max(comments, key=lambda comment: comment.get("child_comment_count") or 0)


async def body(replay: E2Replay) -> None:
   await replay.bootstrap()

   feed = await replay.engine_read(
      "home timeline first page", build_feed_page_request(replay.session)
   )
   author = public_author(feed)

   if author is not None:
      await grid_and_tray(replay, str(author["username"]), str(author["pk"]))
   else:
      replay.record("grid", "skipped, no public author on the timeline's first page")

   post = pick_post(feed)

   if post is not None:
      await reply_pages(replay, str(post["pk"]))


async def grid_and_tray(replay: E2Replay, username: str, user_id: str) -> None:
   profile_page = f"{ORIGIN}/{username}/"
   first_grid = await replay.engine_read(
      "author grid first page",
      build_graphql_request(
         replay.session,
         PROFILE_POSTS,
         _profile_posts_variables(username, GRID_PAGE_SIZE),
         referer=profile_page,
         user_agent=replay.user_agent,
      ),
   )
   grid = dig(first_grid, "data", GRID_ROOT)
   replay.record("author_grid_first_page", page_info_of(grid))
   grid_cursor = dig(grid, "page_info", "end_cursor")
   grid_has_more = bool(dig(grid, "page_info", "has_next_page")) and bool(grid_cursor)

   if grid_has_more:
      variables = {**PROFILE_POSTS_TEMPLATE, "after": grid_cursor, "username": username}

      for attempt in (1, 2):
         page = await replay.graphql(
            "profile-posts-grid-next-page",
            variables,
            referer=profile_page,
            label=f"posts grid next page {attempt}",
            try_other_path_on_null=attempt == 1,
         )
         connection = dig(page, "data", GRID_ROOT)
         first_node = dig(connection, "edges", 0, "node")
         replay.record(
            f"grid_next_page_{attempt}",
            page_info_of(connection) | {"first_item_prefix": id_prefix(dig(first_node, "pk"))},
         )

         if page is not None:
            replay.shape("posts_grid_next_page", connection)

   first_tray = await replay.engine_read(
      "author highlights tray",
      build_graphql_request(
         replay.session,
         PROFILE_HIGHLIGHTS,
         {"user_id": user_id},
         referer=profile_page,
         user_agent=replay.user_agent,
      ),
   )
   tray = dig(first_tray, "data", "highlights")
   replay.record("author_tray_first_page", page_info_of(tray))
   tray_cursor = dig(tray, "page_info", "end_cursor")
   tray_has_more = bool(dig(tray, "page_info", "has_next_page")) and bool(tray_cursor)

   if not tray_has_more:
      return

   tray_variables = {
      "after": tray_cursor,
      "before": None,
      "first": 12,
      "last": None,
      "max_highlights_to_fetch_on_pagination": 12,
      "user_id": user_id,
   }

   for attempt in (1, 2):
      page = await replay.graphql(
         "profile-highlights-tray-next-page",
         tray_variables,
         referer=profile_page,
         label=f"highlights tray next page {attempt}",
      )
      replay.record(f"tray_next_page_{attempt}", page_info_of(dig(page, "data", "highlights")))

      if page is not None:
         replay.shape("highlights_tray_next_page", dig(page, "data"))


async def reply_pages(replay: E2Replay, post_pk: str) -> None:
   comments = await replay.engine_read(
      "first comment page", build_comment_page_request(replay.session, post_pk)
   )
   comment = comment_with_most_replies(comments)
   reply_count = (comment or {}).get("child_comment_count") or 0
   replay.record("chosen_comment", {"child_comment_count": reply_count})

   if not reply_count:
      replay.record("replies", "skipped, no comment on the first page has replies")

      return

   variables = {
      "after": None,
      "before": None,
      "media_id": post_pk,
      "parent_comment_id": str(comment["pk"]),
      "is_chronological": True,
      "first": 3,
      "last": None,
      **LOGGED_IN,
   }
   page = await replay.graphql(
      "read-comment-replies", variables, referer=f"{ORIGIN}/", label="replies 1"
   )
   connection = dig(page, "data", REPLIES_ROOT)
   replay.record("replies_1", page_info_of(connection))
   cursor = dig(connection, "page_info", "end_cursor")
   has_next_page = bool(dig(connection, "page_info", "has_next_page")) and bool(cursor)

   if not has_next_page:
      replay.record("replies_next_page", "skipped, the replies fit one page")

      return

   next_variables = {**variables, "after": cursor, "first": 10}

   for attempt in (1, 2):
      next_page = await replay.graphql(
         "read-comment-replies-next-page",
         next_variables,
         referer=f"{ORIGIN}/",
         label=f"replies next page {attempt}",
         try_other_path_on_null=attempt == 1,
      )
      replay.record(
         f"replies_next_page_{attempt}", page_info_of(dig(next_page, "data", REPLIES_ROOT))
      )

      if next_page is not None:
         replay.shape("replies_next_page", dig(next_page, "data", REPLIES_ROOT))


if __name__ == "__main__":
   sys.exit(asyncio.run(run_probe("e2-next-pages", PLANNED, CONDITIONAL, body)))
