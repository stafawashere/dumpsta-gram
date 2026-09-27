"""The recent searches, what the search box offers for a query, the accounts a query matches, a
hashtag's header and the keyword grid, in both output forms."""

from __future__ import annotations

from typing import Any

from dumpstagram._cli.render.profiles import describe_profile_summary, render_profile_summaries
from dumpstagram.models import (
   Hashtag,
   KeywordResults,
   ProfileSummary,
   RecentSearch,
   RecentSearchKind,
   SearchPost,
   SearchResult,
   SearchResultKind,
   SearchResults,
)

__all__ = [
   "describe_hashtag",
   "describe_keyword_results",
   "describe_recent_searches",
   "describe_search_accounts",
   "describe_search_results",
   "render_hashtag",
   "render_keyword_results",
   "render_recent_searches",
   "render_search_accounts",
   "render_search_results",
]


def _describe_recent_search(entry: RecentSearch) -> dict[str, Any]:
   account = describe_profile_summary(entry.account) if entry.account is not None else None

   return {"kind": entry.kind.value, "account": account, "keyword": entry.keyword}


def describe_recent_searches(entries: tuple[RecentSearch, ...]) -> dict[str, Any]:
   return {
      "entry_count": len(entries),
      "entries": [_describe_recent_search(entry) for entry in entries],
   }


def _recent_search_line(entry: RecentSearch) -> str:
   account = entry.account

   if account is not None:
      return f"account  {account.id}  {account.username}  {account.full_name}"

   if entry.kind is RecentSearchKind.KEYWORD:
      return f"keyword  {entry.keyword}"

   return entry.kind.name.lower()


def render_recent_searches(entries: tuple[RecentSearch, ...]) -> str:
   """One line per entry in the upstream's order, its kind first, then how many."""

   lines = [_recent_search_line(entry) for entry in entries]
   lines.append(f"recent searches: {len(entries)}")

   return "\n".join(lines)


def describe_search_accounts(accounts: tuple[ProfileSummary, ...]) -> dict[str, Any]:
   return {
      "account_count": len(accounts),
      "accounts": [describe_profile_summary(account) for account in accounts],
   }


def render_search_accounts(accounts: tuple[ProfileSummary, ...]) -> str:
   return render_profile_summaries(accounts)


def describe_hashtag(hashtag: Hashtag) -> dict[str, Any]:
   return {"id": hashtag.id, "name": hashtag.name}


def render_hashtag(hashtag: Hashtag) -> str:
   return f"#{hashtag.name}  id {hashtag.id}"


def _describe_search_result(result: SearchResult) -> dict[str, Any]:
   account = describe_profile_summary(result.account) if result.account is not None else None

   return {
      "kind": result.kind.value,
      "position": result.position,
      "account": account,
      "keyword": result.keyword,
   }


def describe_search_results(results: SearchResults) -> dict[str, Any]:
   kinds: dict[str, int] = {}

   for result in results.results:
      kinds[result.kind.value] = kinds.get(result.kind.value, 0) + 1

   return {
      "result_count": len(results.results),
      "kinds": dict(sorted(kinds.items())),
      "results": [_describe_search_result(result) for result in results.results],
   }


def _search_result_line(result: SearchResult) -> str:
   account = result.account

   if account is not None:
      return f"account  {account.id}  {account.username}  {account.full_name}"

   if result.kind is SearchResultKind.KEYWORD:
      return f"keyword  {result.keyword}"

   return result.kind.name.lower()


def render_search_results(results: SearchResults) -> str:
   """One line per row in the order the box shows them, its kind first, then how many."""

   lines = [_search_result_line(result) for result in results.results]
   lines.append(f"results: {len(results.results)}")

   return "\n".join(lines)


def _describe_search_post(post: SearchPost) -> dict[str, Any]:
   """The JSON form of one keyword grid post. Every key is part of the CLI's contract."""

   return {
      "id": post.id,
      "pk": post.pk,
      "code": post.code,
      "taken_at": post.taken_at.isoformat(),
      "author": {
         "id": post.author.id,
         "username": post.author.username,
         "full_name": post.author.full_name,
         "is_private": post.author.is_private,
         "is_verified": post.author.is_verified,
         "profile_pic_url": post.author.profile_pic_url,
      },
      "media_type": post.media_type,
      "like_count": post.like_count,
      "comment_count": post.comment_count,
      "like_and_view_counts_disabled": post.like_and_view_counts_disabled,
      "caption": post.caption,
      "accessibility_caption": post.accessibility_caption,
      "original_width": post.original_width,
      "original_height": post.original_height,
      "carousel_media_count": post.carousel_media_count,
      "images": [
         {"url": image.url, "width": image.width, "height": image.height} for image in post.images
      ],
      "video_duration": post.video_duration,
      "has_audio": post.has_audio,
      "view_count": post.view_count,
   }


def describe_keyword_results(results: KeywordResults) -> dict[str, Any]:
   return {
      "post_count": len(results.posts),
      "more_available": results.has_more,
      "posts": [_describe_search_post(post) for post in results.posts],
   }


def render_keyword_results(results: KeywordResults) -> str:
   """One line per post in the grid's order, then the trailer."""

   lines = []

   for post in results.posts:
      caption = post.caption.splitlines()[0] if post.caption else ""
      lines.append(
         f"{post.code}  {post.author.username}  likes {post.like_count}  "
         f"comments {post.comment_count}  {caption}"
      )

   lines.append(f"posts: {len(results.posts)}  more_available: {results.has_more}")

   return "\n".join(lines)
