"""The recent searches, the accounts a query matches and a hashtag's header, in both output
forms."""

from __future__ import annotations

from typing import Any

from dumpstagram._cli.render.profiles import describe_profile_summary, render_profile_summaries
from dumpstagram.models import Hashtag, ProfileSummary, RecentSearch, RecentSearchKind

__all__ = [
   "describe_hashtag",
   "describe_recent_searches",
   "describe_search_accounts",
   "render_hashtag",
   "render_recent_searches",
   "render_search_accounts",
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
