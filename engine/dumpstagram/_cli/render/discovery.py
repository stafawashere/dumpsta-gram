"""Pages of the explore grid, a place's header and posts, the new posts check, pages of the reels
feed, and pages of an audio's page, in both output forms."""

from __future__ import annotations

from typing import Any

from dumpstagram._cli.render.media import describe_post
from dumpstagram._cli.render.post_depth import describe_post_thumbnail
from dumpstagram.models import AudioPage, ExploreGrid, LocationPosts, MediaAudio, Page, Place, Post

__all__ = [
   "describe_audio_pages",
   "describe_explore_grid",
   "describe_explore_pages",
   "describe_location_posts",
   "describe_place",
   "describe_reels_pages",
   "render_audio_pages",
   "render_explore_grid",
   "render_explore_pages",
   "render_location_posts",
   "render_new_posts",
   "render_place",
   "render_reels_pages",
]


def describe_explore_grid(grid: ExploreGrid) -> dict[str, Any]:
   return {
      "section_count": len(grid.sections),
      "post_count": len(grid.posts),
      "more_available": grid.more_available,
      "sections": [
         {
            "feed_type": section.feed_type,
            "featured": [describe_post(post) for post in section.featured],
            "posts": [describe_post(post) for post in section.posts],
         }
         for section in grid.sections
      ],
   }


def _post_line(post: Post) -> str:
   caption = post.caption.splitlines()[0] if post.caption else ""

   return (
      f"{post.code}  {post.author.username}  likes {post.like_count}  "
      f"comments {post.comment_count}  {caption}"
   )


def render_explore_grid(grid: ExploreGrid) -> str:
   """One line per post, section by section, each featured post marked, then the trailer."""

   lines = []

   for index, section in enumerate(grid.sections):
      lines.append(f"section {index + 1}  {section.feed_type}")
      lines.extend(f"  featured  {_post_line(post)}" for post in section.featured)
      lines.extend(f"  {_post_line(post)}" for post in section.posts)

   lines.append(
      f"sections: {len(grid.sections)}  posts: {len(grid.posts)}  "
      f"more_available: {grid.more_available}"
   )

   return "\n".join(lines)


def describe_place(place: Place) -> dict[str, Any]:
   """The JSON form of a place's header. Every key is part of the CLI's contract."""

   return {
      "id": place.id,
      "name": place.name,
      "category": place.category,
      "lat": place.lat,
      "lng": place.lng,
      "media_count": place.media_count,
      "slug": place.slug,
      "address": place.address,
      "city": place.city,
      "zip_code": place.zip_code,
      "phone": place.phone,
      "price_range": place.price_range,
   }


def render_place(place: Place) -> str:
   lines = [
      f"{place.name}  id {place.id}  {place.category}",
      f"posts: {place.media_count}  at {place.lat}, {place.lng}",
   ]
   address = ", ".join(part for part in (place.address, place.city, place.zip_code) if part)

   if address:
      lines.append(address)

   if place.phone:
      lines.append(f"phone: {place.phone}")

   return "\n".join(lines)


def describe_location_posts(page: LocationPosts) -> dict[str, Any]:
   return {
      "post_count": len(page.posts),
      "more_available": page.has_more,
      "posts": [describe_post_thumbnail(post) for post in page.posts],
   }


def render_location_posts(page: LocationPosts) -> str:
   """One line per post in the grid's order, then the trailer."""

   lines = []

   for post in page.posts:
      caption = post.caption.splitlines()[0] if post.caption else ""
      lines.append(
         f"{post.code}  {post.author_username}  likes {post.like_count}  "
         f"comments {post.comment_count}  {caption}"
      )

   lines.append(f"posts: {len(page.posts)}  more_available: {page.has_more}")

   return "\n".join(lines)


def render_new_posts(has_new_posts: bool) -> str:
   return f"new_posts: {has_new_posts}"


def describe_reels_pages(pages: list[Page[Post]]) -> dict[str, Any]:
   """What was read, every reel with the whole post form, and the last page's own terminator and
   cursor."""

   last = pages[-1] if pages else None
   reels = [reel for page in pages for reel in page.items]

   return {
      "pages_read": len(pages),
      "reel_count": len(reels),
      "more_available": last.has_next_page if last is not None else False,
      "end_cursor": last.end_cursor if last is not None else None,
      "reels": [describe_post(reel) for reel in reels],
   }


def render_reels_pages(pages: list[Page[Post]]) -> str:
   """One line per reel in the feed's order, page after page, then the trailer."""

   lines = [_post_line(reel) for page in pages for reel in page.items]
   reel_count = sum(len(page.items) for page in pages)
   more_available = pages[-1].has_next_page if pages else False
   lines.append(f"pages: {len(pages)}  reels: {reel_count}  more_available: {more_available}")

   return "\n".join(lines)


def _merged_grid(grids: list[ExploreGrid]) -> ExploreGrid:
   """Every page read as one grid, its sections in order, with the last page's own terminator
   and cursor."""

   last = grids[-1] if grids else None

   return ExploreGrid(
      sections=tuple(section for grid in grids for section in grid.sections),
      more_available=last.more_available if last is not None else False,
      end_cursor=last.end_cursor if last is not None else None,
   )


def describe_explore_pages(grids: list[ExploreGrid]) -> dict[str, Any]:
   """The keys of a single page's form over every page read, with ``pages_read`` and the last
   page's ``end_cursor`` added."""

   merged = _merged_grid(grids)

   return {
      "pages_read": len(grids),
      **describe_explore_grid(merged),
      "end_cursor": merged.end_cursor,
   }


def render_explore_pages(grids: list[ExploreGrid]) -> str:
   """The sections of every page read in order, then the trailer :func:`render_explore_grid`
   prints, over all of them."""

   return render_explore_grid(_merged_grid(grids))


def _describe_audio(audio: MediaAudio | None) -> dict[str, Any] | None:
   if audio is None:
      return None

   return {
      "kind": audio.kind.value,
      "audio_id": audio.audio_id,
      "title": audio.title,
      "artist": audio.artist,
      "artist_id": audio.artist_id,
      "is_explicit": audio.is_explicit,
      "should_mute": audio.should_mute,
   }


def describe_audio_pages(audio_id: str, pages: list[AudioPage]) -> dict[str, Any]:
   """The track and the count from the first page read, every reel of every page with the whole
   post form, and the last page's own terminator and cursor. Every key is part of the CLI's
   contract."""

   first = pages[0] if pages else None
   last = pages[-1] if pages else None
   clips = [clip for page in pages for clip in page.clips]

   return {
      "audio_id": audio_id,
      "audio": _describe_audio(first.audio if first is not None else None),
      "clips_count": first.clips_count if first is not None else None,
      "is_restricted": first.is_restricted if first is not None else None,
      "pages_read": len(pages),
      "clip_count": len(clips),
      "more_available": last.more_available if last is not None else False,
      "end_cursor": last.end_cursor if last is not None else None,
      "clips": [describe_post(clip) for clip in clips],
   }


def render_audio_pages(pages: list[AudioPage]) -> str:
   """The track, then one line per reel in the page's order, page after page, then the
   trailer."""

   first = pages[0] if pages else None
   audio = first.audio if first is not None else None
   lines = []

   if audio is not None:
      lines.append(f"{audio.title}  {audio.artist}  {audio.kind.value}  id {audio.audio_id}")

   if first is not None:
      lines.append(f"reels using it: {first.clips_count}")

   lines.extend(_post_line(clip) for page in pages for clip in page.clips)
   clip_count = sum(len(page.clips) for page in pages)
   more_available = pages[-1].more_available if pages else False
   lines.append(f"pages: {len(pages)}  reels: {clip_count}  more_available: {more_available}")

   return "\n".join(lines)
