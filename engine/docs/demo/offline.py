"""The surface that spends no request: the session, the behavior presets, the errors, the clients.

Live requests: 0. Building a client opens no connection, so everything here runs offline.

   uv run python docs/demo/offline.py
"""

from __future__ import annotations

import argparse
import dataclasses
import sys

from _common import EXIT_CODES, QUICK, Demo, build_parser, line, preview, run, show_call, yes_no

from dumpstagram import (
   EXPORT,
   FAST,
   PARITY,
   RETRYABLE,
   SCHEMA_VERSION,
   AuthenticationFailed,
   Behavior,
   CheckpointRequired,
   DumpstagramError,
   NotFound,
   OperationCancelled,
   OutcomeUnknown,
   ProxyConfig,
   RateLimited,
   SchemaChanged,
   Session,
   Spacing,
   TransportFailure,
   UpstreamRejected,
)

ERROR_CLASSES: tuple[type[DumpstagramError], ...] = (
   AuthenticationFailed,
   CheckpointRequired,
   RateLimited,
   UpstreamRejected,
   NotFound,
   SchemaChanged,
   TransportFailure,
   OperationCancelled,
   OutcomeUnknown,
)

NAMESPACE_ALIASES = (
   ("profile(username)", "profiles.by_username(username)"),
   ("profile_by_id(user_id)", "profiles.by_id(user_id)"),
   ("feed(after=...)", "feeds.home(after=...)"),
   ("post(code)", "media.by_code(code)"),
   ("comments(post_pk)", "media.comments(post_pk)"),
   ("like(post_pk), unlike", "media.like(post_pk), media.unlike"),
   ("comment, delete_comment", "media.comment, media.delete_comment"),
   ("follow(user_id), unfollow", "social.follow(user_id), social.unfollow"),
   ("thread_messages(fbid)", "direct.messages(fbid)"),
   ("send_message, unsend_message", "direct.send, direct.unsend"),
   ("notes(), set_note, delete_note", "direct.notes(), direct.set_note, direct.delete_note"),
)

NAMESPACE_ONLY = (
   "feeds.iter_home, media.iter_comments, direct.iter_messages",
   "media.download",
   "media.publish_photo, media.publish_carousel, media.delete_post",
)


def show_session(demo: Demo) -> None:
   demo.tour.section(
      "Session",
      demo.session_call,
      "Session.from_dict(session.to_dict()) == session",
   )

   session = demo.session
   restored = Session.from_dict(session.to_dict())

   line(f"account {session.ds_user_id}, schema version {SCHEMA_VERSION}")
   line(f"page tokens {yes_no(session.fb_dtsg is not None)}")
   line(f"bootstrapped at {session.bootstrapped_at or 'never'}")
   line(f"checkpoint {yes_no(session.checkpoint_active)}")
   line(f"round trip through a dict is equal: {yes_no(restored == session)}")

   print()
   show_call('dataclasses.replace(session, proxy=ProxyConfig(url="http://127.0.0.1:8080"))')

   proxied = dataclasses.replace(session, proxy=ProxyConfig(url="http://127.0.0.1:8080"))
   line(f"a copy routed through {proxied.proxy.url}, verify_tls={proxied.proxy.verify_tls}")


def show_behaviors(demo: Demo) -> None:
   demo.tour.section("Behavior presets", "SyncClient(session, behavior=PARITY)")

   presets = {"PARITY": PARITY, "EXPORT": EXPORT, "FAST": FAST, "QUICK": QUICK}

   for name, behavior in presets.items():
      read_gap = behavior.spacing.floor_seconds + behavior.spacing.mean_jitter_seconds
      write_gap = behavior.write_spacing.floor_seconds + behavior.write_spacing.mean_jitter_seconds
      routes = "browser routes" if behavior.page_load_companions else "direct queries"

      line(f"{name:<7} reads {read_gap:>4.2f} s, writes {write_gap:>5.2f} s mean gap, {routes}")

   line("QUICK is dataclasses.replace(PARITY, ...), built in _common.py")

   print()
   show_call("Behavior(spacing=Spacing(floor_seconds=2.0, mean_jitter_seconds=1.0),")
   show_call("...      write_budget_per_hour=10, poll_interval_seconds=30.0)")

   custom = Behavior(
      spacing=Spacing(floor_seconds=2.0, mean_jitter_seconds=1.0),
      write_budget_per_hour=10,
      poll_interval_seconds=30.0,
   )

   line(f"feed first page {custom.feed_first_page.name}, profile route {custom.profile_route.name}")
   line(f"thread first page {custom.thread_first_page.name}, cookie sync {custom.cookie_sync}")
   line(
      f"{custom.write_budget_per_hour} writes an hour, stop after an unrecognised rejection "
      f"{yes_no(custom.stop_writes_after_unrecognised_rejection)}"
   )


def show_errors(demo: Demo) -> None:
   demo.tour.section(
      "Errors",
      "except RETRYABLE: ...",
      "except DumpstagramError as failure: ...",
   )

   retryable_names = ", ".join(error_class.__name__ for error_class in RETRYABLE)
   line(f"RETRYABLE is ({retryable_names}), and nothing else is safe to send again")

   for error_class in ERROR_CLASSES:
      is_retryable = issubclass(error_class, RETRYABLE)
      marker = "retryable" if is_retryable else ""

      line(f"{error_class.__name__:<21} exit {EXIT_CODES[error_class]:>2}  {marker}", depth=2)

   line("CheckpointRequired is never retried, OutcomeUnknown means a write may have applied")


def show_clients(demo: Demo) -> None:
   demo.tour.section(
      "Clients and namespaces",
      "with SyncClient(session) as client:",
      "...     export_client = client.with_behavior(EXPORT)",
   )

   with demo.client() as client:
      export_client = client.with_behavior(EXPORT)
      shares_session = export_client.session is client.session

      line(f"user agent {preview(client.user_agent)}")
      line(f"with_behavior shares the session and the pacer: {yes_no(shares_session)}")
      line(f"export client spacing {export_client.behavior.spacing.floor_seconds} s floor")

      export_client.close()
      line(f"closed on its own: {yes_no(export_client.closed)}")
      line(f"parent still open: {yes_no(not client.closed)}")

   line(f"parent closed on exit: {yes_no(client.closed)}")

   print()
   show_call('SyncClient.from_session_file("state/session.json", behavior=QUICK)')
   line("the same client, built straight from a saved session")

   print()
   line("every flat method has one namespace alias with the same parameters")

   for flat_call, namespace_call in NAMESPACE_ALIASES:
      line(f"client.{flat_call:<31} client.{namespace_call}", depth=2)

   line("and some live only on a namespace")

   for namespace_calls in NAMESPACE_ONLY:
      line(namespace_calls, depth=2)

   line("AsyncClient carries the same names, awaited, and async iterators for iter_ methods")


def tour(demo: Demo, arguments: argparse.Namespace) -> None:
   show_session(demo)
   show_behaviors(demo)
   show_errors(demo)
   show_clients(demo)


if __name__ == "__main__":
   parser = build_parser("The public surface that spends no request.")
   sys.exit(run("offline", parser, tour, saves_session=False))
