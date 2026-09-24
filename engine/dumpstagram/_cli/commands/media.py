"""The post commands: read a post, like and unlike it, and read, write and delete its comments."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from typing import TextIO

from dumpstagram._cli.commands.common import (
   ClientFactory,
   Subcommands,
   add_request_options,
   emit,
   resolve_session_path,
)
from dumpstagram._cli.exits import EXIT_OK
from dumpstagram._cli.render.media import (
   describe_comment,
   describe_comment_page,
   describe_post_detail,
   render_comment_page,
   render_post_detail,
)

__all__ = [
   "add_comment_parsers",
   "add_like_parsers",
   "add_post_parser",
   "comment_id",
   "media_pk",
   "run_comment_command",
   "run_like_write",
   "run_post",
]


def media_pk(value: str) -> str:
   is_all_digits = value.isascii() and value.isdigit()

   if not is_all_digits:
      raise argparse.ArgumentTypeError(
         "a post is named by its pk, digits only, not by the <pk>_<author id> form"
      )

   return value


def comment_id(value: str) -> str:
   is_all_digits = value.isascii() and value.isdigit()

   if not is_all_digits:
      raise argparse.ArgumentTypeError("a comment is named by its id, digits only")

   return value


def run_post(
   arguments: argparse.Namespace,
   environment: Mapping[str, str],
   stdout: TextIO,
   client_factory: ClientFactory,
) -> int:
   path = resolve_session_path(arguments.session, environment)
   client = client_factory(path, user_agent=arguments.user_agent)
   token_before_the_read = client.session.fb_dtsg

   try:
      post = client.post(arguments.code)

      harvested_a_new_token = client.session.fb_dtsg != token_before_the_read
      may_write_back = not arguments.no_session_writeback

      if harvested_a_new_token and may_write_back:
         client.session.save(path)
   finally:
      client.close()

   payload = {"command": "post", "post": describe_post_detail(post)}

   emit(payload, render_post_detail(post), as_json=arguments.json, stream=stdout)

   return EXIT_OK


def run_like_write(
   arguments: argparse.Namespace,
   environment: Mapping[str, str],
   stdout: TextIO,
   client_factory: ClientFactory,
) -> int:
   path = resolve_session_path(arguments.session, environment)
   client = client_factory(path, user_agent=arguments.user_agent)
   token_before_the_write = client.session.fb_dtsg
   is_like = arguments.command == "like"

   try:
      if is_like:
         client.like(arguments.pk)
      else:
         client.unlike(arguments.pk)

      harvested_a_new_token = client.session.fb_dtsg != token_before_the_write
      may_write_back = not arguments.no_session_writeback

      if harvested_a_new_token and may_write_back:
         client.session.save(path)
   finally:
      client.close()

   payload = {"command": arguments.command, "pk": arguments.pk, "has_liked": is_like}

   emit(
      payload,
      f"{arguments.command}d {arguments.pk}  has_liked: {is_like}",
      as_json=arguments.json,
      stream=stdout,
   )

   return EXIT_OK


def run_comment_command(
   arguments: argparse.Namespace,
   environment: Mapping[str, str],
   stdout: TextIO,
   client_factory: ClientFactory,
) -> int:
   path = resolve_session_path(arguments.session, environment)
   client = client_factory(path, user_agent=arguments.user_agent)
   token_before_the_call = client.session.fb_dtsg

   try:
      if arguments.command == "comments":
         page = client.comments(arguments.pk, after=arguments.after)
         payload = {"command": "comments", "pk": arguments.pk, **describe_comment_page(page)}
         text = render_comment_page(page)
      elif arguments.command == "comment":
         created = client.comment(arguments.pk, arguments.text)
         payload = {"command": "comment", "pk": arguments.pk, "comment": describe_comment(created)}
         text = f"commented {created.id} on {arguments.pk}"
      else:
         client.delete_comment(arguments.pk, arguments.comment_id)
         payload = {
            "command": "delete-comment",
            "pk": arguments.pk,
            "comment_id": arguments.comment_id,
            "deleted": True,
         }
         text = f"deleted {arguments.comment_id} on {arguments.pk}"

      harvested_a_new_token = client.session.fb_dtsg != token_before_the_call
      may_write_back = not arguments.no_session_writeback

      if harvested_a_new_token and may_write_back:
         client.session.save(path)
   finally:
      client.close()

   emit(payload, text, as_json=arguments.json, stream=stdout)

   return EXIT_OK


def add_post_parser(commands: Subcommands) -> None:
   post = commands.add_parser(
      "post",
      help="read one post by its shortcode, one live request",
      description=(
         "Reads the post whose web address carries CODE and prints its pk, which like and "
         "unlike take, and whether the viewer likes it."
      ),
   )
   post.add_argument("code", metavar="CODE", help="the shortcode from the post's web address")
   add_request_options(post)


def add_like_parsers(commands: Subcommands) -> None:
   for verb, effect in (("like", "like"), ("unlike", "remove the viewer's like from")):
      write = commands.add_parser(
         verb,
         help=f"{effect} one post, one write, sent once and never retried",
         description=(
            f"Writes to the account: {effect} the post whose pk is PK. There is no prompt and "
            "no default target. If the outcome is unknown, read the post with dumpsta post "
            "before sending again."
         ),
      )
      write.add_argument("pk", metavar="PK", type=media_pk, help="the post's pk, digits only")
      add_request_options(write)


def add_comment_parsers(commands: Subcommands) -> None:
   comments = commands.add_parser(
      "comments",
      help="read one page of a post's comments, one live request",
      description=(
         "Reads one page of the comments on the post whose pk is PK and prints each comment's "
         "id, which delete-comment takes, and whether more pages exist."
      ),
   )
   comments.add_argument("pk", metavar="PK", type=media_pk, help="the post's pk, digits only")
   comments.add_argument("--after", metavar="CURSOR", help="an end_cursor from an earlier page")
   add_request_options(comments)

   comment = commands.add_parser(
      "comment",
      help="comment on one post, one write, sent once and never retried",
      description=(
         "Writes to the account: posts TEXT as a comment on the post whose pk is PK, where "
         "everyone who can see the post sees it. There is no prompt and no default target. If "
         "the outcome is unknown, read dumpsta comments PK before sending again, because a "
         "second send is a second comment."
      ),
   )
   comment.add_argument("pk", metavar="PK", type=media_pk, help="the post's pk, digits only")
   comment.add_argument("text", metavar="TEXT", help="the comment, as it should appear")
   add_request_options(comment)

   delete_comment = commands.add_parser(
      "delete-comment",
      help="delete one comment on a post, one write, sent once and never retried",
      description=(
         "Writes to the account: deletes the comment COMMENT_ID on the post whose pk is PK. "
         "There is no prompt and no default target. If the outcome is unknown, read dumpsta "
         "comments PK: a comment no longer listed is gone."
      ),
   )
   delete_comment.add_argument("pk", metavar="PK", type=media_pk, help="the post's pk, digits only")
   delete_comment.add_argument(
      "comment_id", metavar="COMMENT_ID", type=comment_id, help="the comment's id, digits only"
   )
   add_request_options(delete_comment)
