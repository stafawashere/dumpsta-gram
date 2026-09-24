"""The posting commands: publish a photo, publish a carousel, and delete the viewer's own post.

Each one confirms itself with a read in the same process. A publish reads the new post back by
its code and reports whether the read shows the viewer's post with the same ``pk``. A delete
reads the post by its code again and reports it gone only when that read is refused, which is
how the upstream answered a deleted post's read on all five deletes read back, with the code
those five carried.

A publish that applied is printed even when the read after it fails, so the post's ``pk`` and
code are never lost to a failed confirmation. The exit code is then the read's.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TextIO

from dumpstagram._cli.commands.common import (
   Client,
   ClientFactory,
   Subcommands,
   UsageError,
   add_request_options,
   emit,
   resolve_session_path,
)
from dumpstagram._cli.commands.media import media_pk
from dumpstagram._cli.exits import EXIT_BY_ERROR, EXIT_OK, exit_code_for
from dumpstagram._cli.render.media import describe_post_detail, describe_published_post
from dumpstagram.errors import DumpstagramError, UpstreamRejected
from dumpstagram.models import PostDetail, PublishedPost

__all__ = ["POSTING_COMMANDS", "add_posting_parsers", "run_posting_command"]

POSTING_COMMANDS = ("publish-photo", "publish-carousel", "delete-post")

MIN_CAROUSEL_IMAGES = 2

DELETED_POST_READ_REFUSAL = "1675030"
"""The code a post read was refused with on each of the five deleted posts read, a generic
query error with ``data`` null. Finding ``delete-my-own-post`` in the knowledge base. A read
refused with any other code says nothing about the post, so it is reported as unknown."""

EXIT_STILL_READABLE = EXIT_BY_ERROR[UpstreamRejected]
"""The exit code when a delete was answered as done and the post still reads back."""


def run_posting_command(
   arguments: argparse.Namespace,
   environment: Mapping[str, str],
   stdout: TextIO,
   client_factory: ClientFactory,
) -> int:
   names_too_few_slides = (
      arguments.command == "publish-carousel" and len(arguments.images) < MIN_CAROUSEL_IMAGES
   )

   if names_too_few_slides:
      raise UsageError("a carousel needs at least two images, publish-photo takes one")

   path = resolve_session_path(arguments.session, environment)
   client = client_factory(path, user_agent=arguments.user_agent)
   token_before_the_call = client.session.fb_dtsg

   try:
      if arguments.command == "delete-post":
         payload, text, exit_code = _delete_and_confirm(client, arguments.pk, arguments.code)
      else:
         payload, text, exit_code = _publish_and_confirm(client, arguments)

      harvested_a_new_token = client.session.fb_dtsg != token_before_the_call
      may_write_back = not arguments.no_session_writeback

      if harvested_a_new_token and may_write_back:
         client.session.save(path)
   finally:
      client.close()

   emit(payload, text, as_json=arguments.json, stream=stdout)

   return exit_code


def _publish_and_confirm(
   client: Client, arguments: argparse.Namespace
) -> tuple[dict[str, Any], str, int]:
   is_carousel = arguments.command == "publish-carousel"
   images = [Path(image) for image in arguments.images]

   try:
      if is_carousel:
         published = client.media.publish_carousel(images, caption=arguments.caption)
      else:
         published = client.media.publish_photo(images[0], caption=arguments.caption)
   except ValueError as refusal:
      raise UsageError(str(refusal)) from refusal

   payload: dict[str, Any] = {
      "command": arguments.command,
      "post": describe_published_post(published),
      "read_back": None,
      "confirmed": False,
   }
   text = f"published {published.pk}  code: {published.code}"

   try:
      detail = client.media.by_code(published.code)
   except DumpstagramError as failure:
      payload["read_back_error"] = type(failure).__name__

      return payload, f"{text}  read back failed: {type(failure).__name__}", exit_code_for(failure)

   confirmed = _is_the_published_post(detail, published, client.session.ds_user_id)
   payload["read_back"] = describe_post_detail(detail)
   payload["confirmed"] = confirmed

   return payload, f"{text}  confirmed by a read: {confirmed}", EXIT_OK


def _delete_and_confirm(client: Client, pk: str, code: str) -> tuple[dict[str, Any], str, int]:
   client.media.delete_post(pk, code)

   payload: dict[str, Any] = {"command": "delete-post", "pk": pk, "code": code, "deleted": True}

   try:
      client.media.by_code(code)
   except UpstreamRejected as refusal:
      is_the_deleted_post_refusal = refusal.code == DELETED_POST_READ_REFUSAL
      payload["read_refused_with"] = refusal.code

      if is_the_deleted_post_refusal:
         payload["gone"] = True

         return payload, f"deleted {pk}  gone: the read of {code} is refused", EXIT_OK

      payload["gone"] = None

      return payload, f"deleted {pk}  gone: unknown, the read was refused", exit_code_for(refusal)
   except DumpstagramError as failure:
      payload["gone"] = None
      payload["read_back_error"] = type(failure).__name__

      return payload, f"deleted {pk}  gone: unknown, the read failed", exit_code_for(failure)

   payload["gone"] = False

   return payload, f"deleted {pk}  but {code} still reads back", EXIT_STILL_READABLE


def _is_the_published_post(detail: PostDetail, published: PublishedPost, viewer_id: str) -> bool:
   is_the_same_post = detail.pk == published.pk and detail.code == published.code
   is_the_viewers = detail.author.id == viewer_id
   is_the_same_kind = detail.media_type == published.media_type

   return is_the_same_post and is_the_viewers and is_the_same_kind


def add_posting_parsers(commands: Subcommands) -> None:
   publish_photo = commands.add_parser(
      "publish-photo",
      help="publish one JPEG as a post and read it back, two writes and one read",
      description=(
         "Writes to the account: uploads IMAGE and publishes it as a post everyone who can see "
         "the account sees, then reads it back by its code. Each write is sent once and never "
         "retried. There is no prompt. If the publish fails after the upload, the upload is "
         "orphaned and the error says so. If the outcome is unknown, read dumpsta profile "
         "--by-id with the viewer's id and compare media_count before publishing again."
      ),
   )
   publish_photo.add_argument("images", metavar="IMAGE", nargs=1, help="a JPEG file")
   _add_caption_option(publish_photo)
   add_request_options(publish_photo)

   publish_carousel = commands.add_parser(
      "publish-carousel",
      help="publish JPEGs as one carousel post and read it back, one write each and one more",
      description=(
         "Writes to the account: uploads every IMAGE, in order, and publishes them as one "
         "carousel post, then reads it back by its code. Each write is sent once and never "
         "retried. Uploads that applied before a failure are orphaned and the error names them."
      ),
   )
   publish_carousel.add_argument(
      "images", metavar="IMAGE", nargs="+", help="two or more JPEG files, in slide order"
   )
   _add_caption_option(publish_carousel)
   add_request_options(publish_carousel)

   delete_post = commands.add_parser(
      "delete-post",
      help="delete one of the viewer's own posts and confirm it is gone, one write and one read",
      description=(
         "Writes to the account: deletes the viewer's own post whose pk is PK and shortcode "
         "CODE, then reads CODE again and reports the post gone only when that read is "
         "refused. There is no prompt and no default target."
      ),
   )
   delete_post.add_argument("pk", metavar="PK", type=media_pk, help="the post's pk, digits only")
   delete_post.add_argument("code", metavar="CODE", help="the post's shortcode")
   add_request_options(delete_post)


def _add_caption_option(command: argparse.ArgumentParser) -> None:
   command.add_argument(
      "--caption",
      metavar="TEXT",
      default="",
      help="the caption, empty unless given",
   )
