"""The explore grid, a place's header and posts, and the new posts check, in both output forms."""

from __future__ import annotations

from typing import Any

from dumpstagram._cli.render.media import describe_post
from dumpstagram._cli.render.post_depth import describe_post_thumbnail
from dumpstagram.models import ExploreGrid, LocationPosts, Place, Post

__all__ = [
   "describe_explore_grid",
   "describe_location_posts",
   "describe_place",
   "render_explore_grid",
   "render_location_posts",
   "render_new_posts",
   "render_place",
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
