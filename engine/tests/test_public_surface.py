"""Gates for the public surface snapshot, which ADR-0011 makes the API contract.

Three things have to hold before the committed file means anything. The generator has to
produce the same bytes every run, or the diff is noise and people learn to regenerate without
reading. It has to notice a new public name and a changed annotation, or it guards nothing.
And the committed file has to match what the package currently exposes.

The stability check runs in subprocesses with different hash seeds on purpose. Set and
dictionary iteration order is what usually makes a generated artifact unstable, and it is
invisible inside one process.

Regenerating `tests/public_surface.txt` is deliberate and belongs in the same change as the
surface edit it records. It is never how a red test here is turned green.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

ENGINE_ROOT = Path(__file__).resolve().parent.parent
GENERATOR_PATH = ENGINE_ROOT / "scripts" / "snapshot_surface.py"
SNAPSHOT_PATH = ENGINE_ROOT / "tests" / "public_surface.txt"


def load_generator() -> ModuleType:
   specification = importlib.util.spec_from_file_location("snapshot_surface", GENERATOR_PATH)

   assert specification is not None and specification.loader is not None

   module = importlib.util.module_from_spec(specification)
   specification.loader.exec_module(module)

   return module


@pytest.fixture(scope="module")
def generator() -> ModuleType:
   return load_generator()


def render_in_a_subprocess(hash_seed: str) -> str:
   environment = dict(os.environ)
   environment["PYTHONHASHSEED"] = hash_seed

   finished = subprocess.run(
      [sys.executable, str(GENERATOR_PATH)],
      capture_output=True,
      text=True,
      check=True,
      env=environment,
   )

   return finished.stdout


def test_committed_snapshot_matches_the_package(generator: ModuleType) -> None:
   committed = SNAPSHOT_PATH.read_text(encoding="utf-8")

   assert generator.render_surface() == committed, (
      "the public surface changed. Regenerate with "
      "`uv run python scripts/snapshot_surface.py --write` as part of the change that moved it, "
      "and read the diff"
   )


def test_the_snapshot_covers_every_exported_name(generator: ModuleType) -> None:
   import dumpstagram

   committed = SNAPSHOT_PATH.read_text(encoding="utf-8")

   for name in dumpstagram.__all__:
      assert f"dumpstagram.{name}" in committed


def test_output_is_byte_identical_across_runs(generator: ModuleType) -> None:
   assert generator.render_surface() == generator.render_surface()


def test_output_is_byte_identical_under_different_hash_seeds() -> None:
   assert render_in_a_subprocess("0") == render_in_a_subprocess("1")


def test_a_new_public_name_changes_the_snapshot(generator: ModuleType) -> None:
   """The positive control. A check for an absence proves nothing until it is seen finding one."""

   import dumpstagram.errors

   before = generator.render_surface()
   dumpstagram.errors.SmuggledIn = 7
   dumpstagram.errors.__all__ = [*dumpstagram.errors.__all__, "SmuggledIn"]

   try:
      after = generator.render_surface()
   finally:
      dumpstagram.errors.__all__ = [
         name for name in dumpstagram.errors.__all__ if name != "SmuggledIn"
      ]
      del dumpstagram.errors.SmuggledIn

   assert after != before
   assert "data dumpstagram.errors.SmuggledIn: int = 7" in after
   assert generator.render_surface() == before


def test_a_changed_annotation_changes_the_snapshot(generator: ModuleType) -> None:
   """The other half of the control, because a rename and a retype fail differently."""

   import dumpstagram.session

   before = generator.render_surface()
   original = dumpstagram.session.Session.save.__annotations__["path"]
   dumpstagram.session.Session.save.__annotations__["path"] = "int"

   try:
      after = generator.render_surface()
   finally:
      dumpstagram.session.Session.save.__annotations__["path"] = original

   assert "def dumpstagram.session.Session.save(self, path: int) -> None" in after
   assert generator.render_surface() == before


def names(surface: str, forbidden: str) -> bool:
   """Whether ``forbidden`` appears anywhere in a rendered surface."""

   return forbidden in surface


def test_no_httpx_type_reaches_the_public_surface() -> None:
   """The HTTP client is a recorded implementation choice, not part of the contract.

   Leaking `httpx.Response` or `httpx.Timeout` into a signature makes a transport swap a major
   version bump. The second assertion is the positive control: zero hits means nothing until
   the same check is shown finding one.
   """

   committed = SNAPSHOT_PATH.read_text(encoding="utf-8")

   assert not names(committed, "httpx")
   assert names("def dumpstagram.aio.AsyncClient.send(r: httpx.Request) -> None", "httpx")


def test_no_internal_module_reaches_the_public_surface() -> None:
   """`_core` and `_private` may be reorganized in any release, so no public name may cite one.

   The match is on the dotted module citation rather than on the bare word, because the
   renderer writes every module fully qualified and a public field may legitimately be named
   after one of these words. `Profile.is_private` is such a field, and matching the bare word
   reported it as a leak on 2026-09-21.

   The last two assertions are the positive control: zero hits means nothing until the same
   check is shown finding one.
   """

   committed = SNAPSHOT_PATH.read_text(encoding="utf-8")

   assert not names(committed, "._private")
   assert not names(committed, "._core")
   assert names(
      "property dumpstagram.aio.AsyncClient.pacer -> dumpstagram._core.pacer.Pacer", "._core"
   )
   assert names(
      "def dumpstagram.aio.AsyncClient.send(r: dumpstagram._private.transport.Request) -> None",
      "._private",
   )
