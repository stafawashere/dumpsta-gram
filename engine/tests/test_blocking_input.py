"""Nothing in the library blocks on input, 17.8 item 6 in ``docs/build-plan.md``.

The Swift app imports the package inside a process it owns, with no terminal attached, and
calls it from one serial queue. A read from standard input there never returns, and the queue
that made the call stalls every later call behind it. So no module in ``dumpstagram/``,
including the command line, may call ``input``, touch ``sys.stdin`` or ``sys.__stdin__``,
import ``getpass`` or ``fileinput``, or read file descriptor 0.

The scan reads the source with ``ast``. Its positive control plants each forbidden form into the
text of a real library file and requires the same scan to report it, so a scan that parses
nothing, or looks for the wrong node, cannot pass.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

ENGINE_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = ENGINE_ROOT / "dumpstagram"

BLOCKING_MODULES = frozenset({"getpass", "fileinput"})
STDIN_ATTRIBUTES = frozenset({"stdin", "__stdin__"})
STDIN_DESCRIPTOR = 0

PLANTED_FORMS = {
   "input": "\n\ndef _planted() -> str:\n   return input()\n",
   "sys.stdin": "\n\nimport sys\n\n_planted = sys.stdin.readline()\n",
   "sys.__stdin__": "\n\nimport sys\n\n_planted = sys.__stdin__\n",
   "from sys import stdin": "\n\nfrom sys import stdin as _planted\n",
   "getpass": "\n\nimport getpass\n",
   "from getpass import": "\n\nfrom getpass import getpass as _planted\n",
   "fileinput": "\n\nimport fileinput\n",
   "os.read(0)": "\n\nimport os\n\n_planted = os.read(0, 1)\n",
   "open(0)": "\n\n_planted = open(0)\n",
}


def blocking_reads(source: str, filename: str) -> Iterator[str]:
   tree = ast.parse(source, filename=filename)

   for node in ast.walk(tree):
      if isinstance(node, ast.Import):
         for alias in node.names:
            if alias.name.split(".")[0] in BLOCKING_MODULES:
               yield f"{filename}:{node.lineno} imports {alias.name}"

      if isinstance(node, ast.ImportFrom):
         module = node.module or ""
         imported = {alias.name for alias in node.names}
         takes_stdin = module == "sys" and bool(imported & STDIN_ATTRIBUTES)

         if module.split(".")[0] in BLOCKING_MODULES or takes_stdin:
            yield f"{filename}:{node.lineno} imports from {module}"

      if isinstance(node, ast.Attribute) and node.attr in STDIN_ATTRIBUTES:
         yield f"{filename}:{node.lineno} reads {node.attr}"

      if isinstance(node, ast.Call):
         yield from blocking_call(node, filename)


def blocking_call(node: ast.Call, filename: str) -> Iterator[str]:
   callee = ast.unparse(node.func)
   first_argument = node.args[0] if node.args else None
   reads_descriptor_zero = (
      isinstance(first_argument, ast.Constant) and first_argument.value == STDIN_DESCRIPTOR
   )

   if callee == "input":
      yield f"{filename}:{node.lineno} calls input"

   descriptor_readers = {"open", "os.read", "os.fdopen", "io.open"}

   if callee in descriptor_readers and reads_descriptor_zero:
      yield f"{filename}:{node.lineno} calls {callee} on descriptor 0"


def library_files() -> list[Path]:
   return sorted(PACKAGE_ROOT.rglob("*.py"))


@pytest.mark.parametrize("form", sorted(PLANTED_FORMS))
def test_the_scan_reports_each_form_planted_in_a_real_library_file(form: str) -> None:
   host = PACKAGE_ROOT / "_cli" / "cookie_sources.py"
   original = host.read_text(encoding="utf-8")

   assert list(blocking_reads(original, host.name)) == []
   assert list(blocking_reads(original + PLANTED_FORMS[form], host.name))


def test_nothing_in_the_library_blocks_on_input() -> None:
   """Catches a prompt, a password read or a stdin read anywhere in the package, the command
   line included, which would hang the app's serial queue on a process with no terminal."""

   files = library_files()
   scanned = {path.relative_to(ENGINE_ROOT).as_posix() for path in files}
   findings = [
      finding
      for path in files
      for finding in blocking_reads(
         path.read_text(encoding="utf-8"), str(path.relative_to(ENGINE_ROOT))
      )
   ]

   assert {"dumpstagram/_cli/main.py", "dumpstagram/_cli/cookie_sources.py"} <= scanned
   assert len(scanned) >= 50
   assert findings == []
