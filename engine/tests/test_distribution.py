"""Gates on the built artifacts, the Phase 2 rows gates.md still listed as ahead.

Each run builds a wheel and a source distribution with ``uv build --offline`` into a temporary
directory that is removed afterwards, then judges them from the outside: what each archive
holds, whether a consumer outside this checkout can import the package, construct a
``Session``, run ``dumpsta --help`` and type check against it, and whether any credential this
machine holds appears anywhere inside either archive.

The consumer runs use ``uv run --isolated --no-project --offline --with <wheel>`` from the
temporary directory, so the checkout cannot shadow the installed copy, which is the flat layout
risk ``docs/engineering/gates.md`` describes, and each prints the path the import resolved to.
Nothing here reaches the network. ``--offline`` holds uv to its cache, and the consumer script
refuses every socket connect before it imports anything.

The credential scan reads the values out of the repository's ``.env`` and the saved session
file, never prints one, and reports only which member held which key. Its positive control
plants each value into a copy of the archive's members and requires the same scan to find it.
"""

from __future__ import annotations

import ast
import gzip
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pytest

ENGINE_ROOT = Path(__file__).resolve().parent.parent
REPOSITORY_ROOT = ENGINE_ROOT.parent
PACKAGE = "dumpstagram"

ENV_CREDENTIAL_KEYS = ("IG_SESSIONID", "IG_CSRFTOKEN", "IG_MID", "IG_PASSWORD", "IG_EMAIL")
SESSION_CREDENTIAL_KEYS = ("sessionid", "csrftoken", "fb_dtsg", "lsd", "fr")
SHORTEST_SCANNED_VALUE = 8

FORBIDDEN_PARTS = frozenset({"logs", "probes", "state", "skills", "exports", ".claude"})
FORBIDDEN_NAMES = frozenset({".env", ".DS_Store"})
FORBIDDEN_PREFIXES = ("tests/fixtures/thread_oracle",)

CONSUMER_SCRIPT = """
import socket


def refuse(*arguments, **keywords):
   raise ConnectionRefusedError("the consumer run is offline")


socket.socket.connect = refuse
socket.create_connection = refuse

import importlib.resources
import dumpstagram
from dumpstagram import AsyncClient, Session, SyncClient

session = Session(sessionid="dummy-sessionid", ds_user_id="1", csrftoken="dummy-csrftoken")
marker = importlib.resources.files("dumpstagram").joinpath("py.typed")

print("resolved", dumpstagram.__file__)
print("py.typed", marker.is_file())
print("session", type(session).__name__, SyncClient.__name__, AsyncClient.__name__)
"""

TYPED_CONSUMER = """
from dumpstagram import Page, Profile, Session, SyncClient


def first_username(client: SyncClient) -> str:
   profile: Profile = client.profile_by_id("1")

   return profile.username


def page_size(page: Page[Profile]) -> int:
   return len(page.items)


session: Session = Session(sessionid="a", ds_user_id="1", csrftoken="b")
"""


@dataclass(frozen=True)
class Artifacts:
   directory: Path
   wheel: Path
   sdist: Path


def uv_environment() -> dict[str, str]:
   environment = dict(os.environ)

   for inherited in ("UV_PROJECT_ENVIRONMENT", "VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME"):
      environment.pop(inherited, None)

   return environment


def uv_executable() -> str:
   found = shutil.which("uv")

   if found is None:
      pytest.fail("uv is not on PATH, and it is the only toolchain that builds this package")

   return found


@pytest.fixture(scope="module")
def artifacts() -> Iterator[Artifacts]:
   with tempfile.TemporaryDirectory(prefix="dumpstagram-dist-") as directory:
      output = Path(directory) / "dist"
      built = subprocess.run(
         [uv_executable(), "build", "--offline", "--out-dir", str(output), str(ENGINE_ROOT)],
         cwd=directory,
         capture_output=True,
         text=True,
         env=uv_environment(),
      )

      assert built.returncode == 0, built.stderr[-2000:]

      wheels = sorted(output.glob("*.whl"))
      sdists = sorted(output.glob("*.tar.gz"))

      assert len(wheels) == 1 and len(sdists) == 1

      yield Artifacts(directory=Path(directory), wheel=wheels[0], sdist=sdists[0])


def wheel_members(wheel: Path) -> dict[str, bytes]:
   with zipfile.ZipFile(wheel) as archive:
      return {name: archive.read(name) for name in archive.namelist() if not name.endswith("/")}


def sdist_members(sdist: Path) -> dict[str, bytes]:
   members = {}

   with tarfile.open(sdist, "r:gz") as archive:
      for member in archive.getmembers():
         if not member.isfile():
            continue

         relative = PurePosixPath(*PurePosixPath(member.name).parts[1:]).as_posix()
         extracted = archive.extractfile(member)

         assert extracted is not None

         members[relative] = extracted.read()

   return members


def run_consumer(artifacts: Artifacts, *command: str) -> subprocess.CompletedProcess[str]:
   return subprocess.run(
      [
         uv_executable(),
         "run",
         "--isolated",
         "--no-project",
         "--offline",
         "--python",
         "3.12",
         "--with",
         str(artifacts.wheel),
         *command,
      ],
      cwd=artifacts.directory,
      capture_output=True,
      text=True,
      env=uv_environment(),
   )


def test_the_wheel_carries_the_package_and_nothing_else(artifacts: Artifacts) -> None:
   """Catches a test, a document, a log or any other file riding into the wheel, and a
   subpackage missing from it."""

   members = wheel_members(artifacts.wheel)
   dist_info = f"{artifacts.wheel.name.split('-')[0]}-{artifacts.wheel.name.split('-')[1]}"
   package_members = {name for name in members if name.startswith(f"{PACKAGE}/")}
   metadata_members = {name for name in members if name.startswith(f"{dist_info}.dist-info/")}
   anything_else = set(members) - package_members - metadata_members
   not_source = {
      name for name in package_members if not name.endswith(".py") and name != f"{PACKAGE}/py.typed"
   }
   source_tree = {
      path.relative_to(ENGINE_ROOT).as_posix() for path in (ENGINE_ROOT / PACKAGE).rglob("*.py")
   }

   assert f"{dist_info}.dist-info/METADATA" in metadata_members
   assert anything_else == set()
   assert not_source == set()
   assert {name for name in package_members if name.endswith(".py")} == source_tree


def test_the_wheel_carries_py_typed_and_a_consumer_type_checks_against_it(
   artifacts: Artifacts,
) -> None:
   """Catches the typing marker missing from the wheel, which mypy reports as missing library
   stubs, so a consumer silently gets ``Any`` everywhere.

   The consumer's interpreter has only the wheel installed, and the development environment's
   pinned mypy reads it through ``--python-executable``, since an offline run cannot install a
   second mypy.
   """

   consumer = artifacts.directory / "typed_consumer.py"
   consumer.write_text(TYPED_CONSUMER, encoding="utf-8")

   mypy = Path(sys.executable).parent / "mypy"
   driver = (
      "import subprocess, sys\n"
      f"arguments = [{str(mypy)!r}, '--strict', '--no-incremental']\n"
      f"arguments += ['--cache-dir', {os.devnull!r}]\n"
      f"arguments += ['--python-executable', sys.executable, {str(consumer)!r}]\n"
      "sys.exit(subprocess.run(arguments).returncode)\n"
   )

   checked = run_consumer(artifacts, "python", "-c", driver)

   assert checked.returncode == 0, checked.stdout[-2000:]
   assert "Success" in checked.stdout


def test_a_consumer_outside_the_checkout_imports_constructs_and_runs_the_command(
   artifacts: Artifacts,
) -> None:
   """Catches an import that only worked because the checkout was the working directory, a
   missing subpackage, and a console script that does not start."""

   consumer = artifacts.directory / "consumer.py"
   consumer.write_text(CONSUMER_SCRIPT, encoding="utf-8")

   imported = run_consumer(artifacts, "python", str(consumer))
   helped = run_consumer(artifacts, "dumpsta", "--help")

   assert imported.returncode == 0, imported.stderr[-2000:]

   resolved = next(line for line in imported.stdout.splitlines() if line.startswith("resolved "))
   resolved_path = Path(resolved.removeprefix("resolved ")).resolve()

   assert "site-packages" in resolved_path.parts
   assert not resolved_path.is_relative_to(REPOSITORY_ROOT)
   assert "py.typed True" in imported.stdout
   assert "session Session SyncClient AsyncClient" in imported.stdout
   assert helped.returncode == 0, helped.stderr[-2000:]
   assert helped.stdout.startswith("usage: dumpsta")


def ignored_by_git(paths: list[str]) -> set[str]:
   answered = subprocess.run(
      ["git", "check-ignore", "--stdin"],
      cwd=ENGINE_ROOT,
      input="\n".join(paths) + "\n",
      capture_output=True,
      text=True,
   )

   assert answered.returncode in (0, 1), answered.stderr

   return set(answered.stdout.split())


def is_forbidden(member: str) -> bool:
   path = PurePosixPath(member)
   has_forbidden_part = bool(FORBIDDEN_PARTS & set(path.parts))
   has_forbidden_name = path.name in FORBIDDEN_NAMES or path.name.startswith(".env")
   is_session_file = path.name.startswith("session") and path.suffix == ".json"
   is_credential_file = path.name.startswith("credentials") or path.suffix == ".session"
   is_oracle = member.startswith(FORBIDDEN_PREFIXES)

   return any(
      (has_forbidden_part, has_forbidden_name, is_session_file, is_credential_file, is_oracle)
   )


def test_the_sdist_ships_nothing_the_repository_keeps_local(artifacts: Artifacts) -> None:
   """Catches an agent document, the oracle fixtures, a log, a probe, the session state or an
   environment file in the source distribution. hatchling reads only ``engine/.gitignore``, so
   the root ignore list is asked directly, with a document it ignores as the control."""

   members = sorted(set(sdist_members(artifacts.sdist)) - {"PKG-INFO"})
   control = "docs/build-plan.md"
   ignored = ignored_by_git([*members, control])
   forbidden = [member for member in members if is_forbidden(member)]

   assert control in ignored
   assert f"{PACKAGE}/__init__.py" in members
   assert ignored - {control} == set()
   assert forbidden == []


def scripts_loaded_by(source: str) -> set[str]:
   """The ``scripts/`` modules a gate file loads, by file name or by import."""

   script_stems = {path.stem for path in (ENGINE_ROOT / "scripts").glob("*.py")}
   loaded = set()

   for node in ast.walk(ast.parse(source)):
      names_a_script_file = isinstance(node, ast.Constant) and isinstance(node.value, str)
      names_a_script_file = names_a_script_file and node.value.removesuffix(".py") in script_stems
      names_a_script_file = names_a_script_file and node.value.endswith(".py")

      if names_a_script_file:
         loaded.add(node.value)

      if isinstance(node, ast.Import):
         loaded.update(f"{alias.name}.py" for alias in node.names if alias.name in script_stems)

   return {f"scripts/{name}" for name in loaded}


def test_every_script_a_shipped_gate_loads_is_in_the_sdist(artifacts: Artifacts) -> None:
   """Catches a gate that loads ``scripts/snapshot_surface.py`` or another script shipping without
   it, so the suite fails with a missing file in an unpacked sdist. The two scripts the surface
   gates are known to load are the control."""

   members = sdist_members(artifacts.sdist)
   shipped_gates = [name for name in members if name.startswith("tests/") and name.endswith(".py")]
   loaded = set()

   for name in shipped_gates:
      loaded |= scripts_loaded_by(members[name].decode("utf-8"))

   missing = sorted(loaded - set(members))

   assert {"scripts/snapshot_surface.py", "scripts/check_surface_additive.py"} <= loaded
   assert missing == []


def known_credentials() -> dict[str, str]:
   known: dict[str, str] = {}
   env_path = REPOSITORY_ROOT / ".env"

   if env_path.exists():
      for line in env_path.read_text(encoding="utf-8").splitlines():
         key, separator, value = line.partition("=")

         if separator and key.strip() in ENV_CREDENTIAL_KEYS:
            known[f".env {key.strip()}"] = value.strip().strip('"')

   session_path = ENGINE_ROOT / "state" / "session.json"

   if session_path.exists():
      saved = json.loads(session_path.read_text(encoding="utf-8"))

      for key in SESSION_CREDENTIAL_KEYS:
         if isinstance(saved.get(key), str):
            known[f"session {key}"] = saved[key]

      for cookie, value in (saved.get("extra_cookies") or {}).items():
         known[f"session cookie {cookie}"] = value

   return {name: value for name, value in known.items() if len(value) >= SHORTEST_SCANNED_VALUE}


def readable(content: bytes) -> bytes:
   if content[:2] == b"\x1f\x8b":
      return gzip.decompress(content)

   return content


def credential_hits(members: dict[str, bytes], credentials: dict[str, str]) -> list[str]:
   hits = []

   for member, content in members.items():
      searched = readable(content)

      for name, value in credentials.items():
         if value.encode("utf-8") in searched:
            hits.append(f"{member} holds {name}")

   return hits


def planted(value: str) -> bytes:
   buffer = io.BytesIO()

   with gzip.GzipFile(fileobj=buffer, mode="wb") as compressed:
      compressed.write(f"prefix {value} suffix".encode())

   return buffer.getvalue()


def test_no_credential_this_machine_holds_is_inside_either_archive(artifacts: Artifacts) -> None:
   """Catches a session file, an environment file or a log carrying a live credential in the
   wheel or the sdist. The control plants each known value, compressed, beside the real members,
   and the same scan must report every one."""

   credentials = known_credentials()

   if not credentials:
      pytest.skip("no .env and no saved session here, so there is no known credential to seek")

   archives = {
      "wheel": wheel_members(artifacts.wheel),
      "sdist": sdist_members(artifacts.sdist),
   }

   for kind, members in archives.items():
      seeded = dict(members)

      for name, value in credentials.items():
         seeded[f"planted/{name}.gz"] = planted(value)

      found = set(credential_hits(seeded, credentials))
      expected = {f"planted/{name}.gz holds {name}" for name in credentials}
      missed = sorted(expected - found)
      member_count = len(members)

      assert missed == [], f"the {kind} control missed a planted credential"
      assert member_count > 10

   wheel_hits = credential_hits(archives["wheel"], credentials)
   sdist_hits = credential_hits(archives["sdist"], credentials)
   scanned_keys = set(credentials)

   assert {".env IG_SESSIONID", "session sessionid"} & scanned_keys
   assert wheel_hits == []
   assert sdist_hits == []
