"""Follow an account, read the relationship back, and unfollow. Writes.

Live requests: the profile by username, 7 under parity or 2 with --quick, then a follow, a
relationship read and an unfollow, 3 more. An account already followed or requested is left
alone, and so is the viewer's own.

   uv run python docs/demo/follow_cycle.py someaccount --quick
"""

from __future__ import annotations

import argparse
import sys

from _common import Demo, build_parser, line, run, yes_no


def tour(demo: Demo, arguments: argparse.Namespace) -> None:
   username = arguments.username

   demo.tour.section(
      "Follow cycle",
      f'target = client.profiles.by_username("{username}")',
      "client.social.follow(target.id)",
      "client.profiles.by_id(target.id).friendship_status",
      "client.social.unfollow(target.id)",
   )

   with demo.client() as client:
      target = client.profiles.by_username(username)
      relationship = target.friendship_status

      is_own_account = relationship is None
      is_following = relationship is not None and relationship.following
      is_pending = relationship is not None and relationship.outgoing_request
      should_skip = is_own_account or is_following or is_pending

      if should_skip:
         line("the account is the viewer's own or already followed, so the cycle stops")
         return

      client.social.follow(target.id)
      after_follow = client.profiles.by_id(target.id).friendship_status

      if after_follow is not None:
         line(
            f"following {yes_no(after_follow.following)}, "
            f"request pending {yes_no(after_follow.outgoing_request)}"
         )

      client.social.unfollow(target.id)
      line("unfollowed")
      demo.report["follow_cycle"] = True


if __name__ == "__main__":
   parser = build_parser("Follow an account, then unfollow it.")
   parser.add_argument("username", help="the account to follow")

   sys.exit(run("follow-cycle", parser, tour))
