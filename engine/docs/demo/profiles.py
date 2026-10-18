"""Profiles: the viewer's own by id, and another account by username with the relationship.

Live requests: 1 for the own profile, plus 1 if the session has no page token yet. With
--username, 7 more under parity or 2 with --quick, because the surface is keyed on the numeric
id and a username costs the profile page's queries.

   uv run python docs/demo/profiles.py
   uv run python docs/demo/profiles.py --username instagram --quick
"""

from __future__ import annotations

import argparse
import sys

from _common import Demo, build_parser, run, show_profile


def tour(demo: Demo, arguments: argparse.Namespace) -> None:
   with demo.client() as client:
      demo.tour.section("Profile by id", "client.profiles.by_id(client.session.ds_user_id)")

      show_profile(client.profiles.by_id(client.session.ds_user_id))
      demo.report["own_profile_read"] = True

      if arguments.username is None:
         return

      demo.tour.section(
         "Profile by username",
         f'client.profiles.by_username("{arguments.username}")',
      )

      show_profile(client.profiles.by_username(arguments.username))
      demo.report["named_profile_read"] = True


if __name__ == "__main__":
   parser = build_parser("Read profiles by id and by username.")
   parser.add_argument("--username", help="also read this account's profile by username")

   sys.exit(run("profiles", parser, tour))
