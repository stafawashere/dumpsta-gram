"""Read only. Not yet run. Thirteen requests, and up to seven more, conditional.

E2 batch 4, post depth, on one post of the owner's home timeline: threaded comment replies and
their next page, the likers, the post read by media pk, the post modal's context, and the more
posts from this account grid. User tags, location and collaborators have no operation of their
own; the post read by media pk answers with the item those fields sit on, and its key union is
the evidence the model needs.

   1  the inbox document, for fresh tokens (the bootstrap)
   2  the home timeline's first page, a verified read, for a post with the most comments
   3  that post's first comment page, a verified read, for a comment that has replies
   4  the replies under that comment, PolarisPostChildCommentsQuery, twice
   6  the replies' next page, PolarisPostCommentsChildrenPaginationtQuery, twice
   8  the likers, PolarisPostLikedByListDialogQuery, twice
  10  the post by media pk, PolarisPostActionLoadPostQueryMediaIdQuery, twice
  12  the post modal's context, PolarisPostModalContextQuery, twice

Conditional: the more posts from this account grid, PolarisDesktopPostPageRelatedMediaGridQuery,
twice, sent only when the declared thirteen leave room, which they do when steps 6 and 7 are
skipped because the replies fit one page, and each hypothesis query's first replay sent once
more on the other GraphQL path when every root is null. Steps 4 to 7 are skipped when no
comment on the page has replies.

Every post, comment and account read here is one the owner's timeline already shows, and a read
of likers or replies is visible to nobody. No caption, comment text, username or id is logged.

Run it from `engine/` with:

   uv run python probes/e2_post_depth.py
"""

from __future__ import annotations

import asyncio
import sys

from _e2_support import E2Replay, dig, id_prefix, page_info_of, run_probe

from dumpstagram._private.web.bootstrap import ORIGIN
from dumpstagram._private.web.requests.feed import build_feed_page_request
from dumpstagram._private.web.requests.media import build_comment_page_request

PLANNED = 13
CONDITIONAL = 7
REPLIES_ROOT = (
   "xdt_api__v1__media__media_id__comments__parent_comment_id__child_comments__connection"
)
LOGGED_IN = {"__relay_internal__pv__PolarisIsLoggedInrelayprovider": True}


def pick_post(feed: object) -> dict[str, object] | None:
   edges = dig(feed, "data", "xdt_api__v1__feed__timeline__connection", "edges") or []
   posts = [dig(edge, "node", "media") for edge in edges]
   posts = [post for post in posts if isinstance(post, dict) and post.get("pk")]

   if not posts:
      return None

   return max(posts, key=lambda post: post.get("comment_count") or 0)


def pick_comment(page: object) -> dict[str, object] | None:
   edges = dig(page, "data", "xdt_api__v1__media__media_id__comments__connection", "edges") or []
   comments = [dig(edge, "node") for edge in edges]
   with_replies = [
      comment
      for comment in comments
      if isinstance(comment, dict) and (comment.get("child_comment_count") or 0) > 0
   ]

   return with_replies[0] if with_replies else None


async def body(replay: E2Replay) -> None:
   await replay.bootstrap()

   feed = await replay.engine_read(
      "home timeline first page", build_feed_page_request(replay.session)
   )
   post = pick_post(feed)

   if post is None:
      replay.record("skipped", "no post on the timeline's first page")

      return

   post_pk = str(post["pk"])
   owner_id = str(dig(post, "user", "pk") or "")
   replay.record(
      "post",
      {"pk_prefix": id_prefix(post_pk), "comment_count": post.get("comment_count")},
   )

   comments = await replay.engine_read(
      "first comment page", build_comment_page_request(replay.session, post_pk)
   )
   comment = pick_comment(comments)

   if comment is not None:
      await replies(replay, post_pk, str(comment.get("pk")))
   else:
      replay.record("replies", "skipped, no comment on the first page has replies")

   for attempt in (1, 2):
      likers = await replay.graphql(
         "read-a-post-s-likers",
         {"media_id": post_pk},
         referer=f"{ORIGIN}/",
         label=f"likers {attempt}",
         try_other_path_on_null=attempt == 1,
      )
      nodes = dig(likers, "data", "fetch__XDTMediaDict", "likers_connection", "nodes") or []
      replay.record(f"likers_{attempt}", {"nodes": len(nodes)})

      if likers is not None:
         replay.shape("likers", dig(likers, "data"))

   for attempt in (1, 2):
      by_id = await replay.graphql(
         "read-a-post-by-media-id",
         {"mediaId": post_pk},
         referer=f"{ORIGIN}/",
         label=f"post by media pk {attempt}",
         try_other_path_on_null=attempt == 1,
      )
      item = dig(by_id, "data", "xdt_api__v1__media__media_id_web_info", "items", 0)
      replay.record(
         f"post_by_id_{attempt}",
         {
            "pk_matches": dig(item, "pk") is not None and str(dig(item, "pk")) == post_pk,
            "has_usertags_key": isinstance(item, dict) and "usertags" in item,
            "has_location_key": isinstance(item, dict) and "location" in item,
            "has_coauthor_producers_key": isinstance(item, dict) and "coauthor_producers" in item,
         },
      )

      if by_id is not None:
         replay.shape("post_by_media_id_item", item)

   for attempt in (1, 2):
      context = await replay.graphql(
         "read-a-post-modal-context",
         {"pk": post_pk},
         referer=f"{ORIGIN}/",
         label=f"post modal context {attempt}",
         try_other_path_on_null=attempt == 1,
      )

      if context is not None:
         replay.shape("post_modal_context", dig(context, "data"))

   room_left = replay.planned + replay.conditional - replay.spent
   has_room_for_the_grid = room_left >= 2 and owner_id

   if not has_room_for_the_grid:
      replay.record("related_grid", "skipped, no room left in the declared count")

      return

   for attempt in (1, 2):
      grid = await replay.graphql(
         "read-more-posts-from-an-account",
         {
            "media_owner_id": owner_id,
            "count": 6,
            "__relay_internal__pv__PolarisShortDramaEnabledrelayprovider": False,
         },
         referer=f"{ORIGIN}/",
         label=f"more posts from the account {attempt}",
      )

      if grid is not None:
         replay.shape("related_grid", dig(grid, "data"))


async def replies(replay: E2Replay, post_pk: str, comment_pk: str) -> None:
   variables = {
      "after": None,
      "before": None,
      "media_id": post_pk,
      "parent_comment_id": comment_pk,
      "is_chronological": True,
      "first": 3,
      "last": None,
      **LOGGED_IN,
   }
   cursor = None

   for attempt in (1, 2):
      page = await replay.graphql(
         "read-comment-replies",
         variables,
         referer=f"{ORIGIN}/",
         label=f"replies {attempt}",
         try_other_path_on_null=attempt == 1,
      )
      connection = dig(page, "data", REPLIES_ROOT)
      replay.record(f"replies_{attempt}", page_info_of(connection))
      cursor = cursor or dig(connection, "page_info", "end_cursor")
      more = dig(connection, "page_info", "has_next_page")

      if page is not None:
         replay.shape("replies", connection)

   has_next_page = bool(more) and bool(cursor)

   if not has_next_page:
      replay.record("replies_next_page", "skipped, the replies fit one page")

      return

   next_variables = {**variables, "after": cursor, "first": 10}

   for attempt in (1, 2):
      page = await replay.graphql(
         "read-comment-replies-next-page",
         next_variables,
         referer=f"{ORIGIN}/",
         label=f"replies next page {attempt}",
         try_other_path_on_null=attempt == 1,
      )
      replay.record(f"replies_next_page_{attempt}", page_info_of(dig(page, "data", REPLIES_ROOT)))


if __name__ == "__main__":
   sys.exit(asyncio.run(run_probe("e2-post-depth", PLANNED, CONDITIONAL, body)))
