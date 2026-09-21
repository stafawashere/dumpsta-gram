"""Generate the public surface snapshot that ADR-0011 makes the API contract.

The output is one sorted line per public entry, and nothing else. A line carries a name, a
shape, and the annotations around it. Docstrings are deliberately absent: a wording fix is not
an API change, and prose in here would make the file churn until people stopped reading the
diff.

The declared surface is `__all__`, per `engine/docs/engineering/02-public-api-practices.md`. A
module without `__all__` falls back to its non-underscore names, which is the same rule applied
where nobody wrote the list down. A name re-exported from another module renders as one alias
line rather than a second copy of the definition, so moving a class between modules shows up as
exactly two changed lines instead of a rewrite.

Run it from `engine/`:

   uv run python scripts/snapshot_surface.py            # print
   uv run python scripts/snapshot_surface.py --write    # rewrite tests/public_surface.txt

Rewriting is a deliberate act that belongs in the same change as the surface edit it records.
It is never a way to make `tests/test_public_surface.py` go green.
"""

from __future__ import annotations

import argparse
import dataclasses
import inspect
import pkgutil
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

PACKAGE = "dumpstagram"
SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "tests" / "public_surface.txt"

LIFECYCLE_DUNDERS = (
   "__init__",
   "__enter__",
   "__exit__",
   "__aenter__",
   "__aexit__",
   "__iter__",
   "__next__",
   "__aiter__",
   "__anext__",
)
"""The only underscored members that carry contract.

Construction and the two context-manager protocols are things a caller writes code against.
Everything else behind an underscore is implementation, and `__repr__` is owned by the
redaction gate rather than by a shape comparison.
"""

_LITERAL_TYPES = (bool, int, float, str, bytes, type(None))


def public_modules() -> list[ModuleType]:
   """Every importable module in the package whose whole dotted path avoids an underscore."""

   root = __import__(PACKAGE, fromlist=["__path__"])
   found = [root]

   for entry in pkgutil.walk_packages(root.__path__, prefix=f"{PACKAGE}."):
      parts = entry.name.split(".")[1:]

      if any(part.startswith("_") for part in parts):
         continue

      found.append(__import__(entry.name, fromlist=["__name__"]))

   return sorted(found, key=lambda module: module.__name__)


def declared_names(module: ModuleType) -> list[str]:
   declared = getattr(module, "__all__", None)

   if declared is not None:
      return sorted(declared)

   return sorted(name for name in dir(module) if not name.startswith("_"))


def format_annotation(annotation: Any) -> str:
   """Render an annotation the way the source wrote it.

   Every module in the package uses `from __future__ import annotations`, so annotations
   arrive as strings and render identically across modules. The object branch exists so that
   a module which stops doing that produces a stable line instead of an address.
   """

   if isinstance(annotation, str):
      return annotation

   if annotation is None or annotation is type(None):
      return "None"

   if isinstance(annotation, type):
      if annotation.__module__ == "builtins":
         return annotation.__qualname__

      return f"{annotation.__module__}.{annotation.__qualname__}"

   return str(annotation)


def format_value(value: Any) -> str:
   """Render a constant's value when it is stable, and its type when it is not.

   A value belongs in the snapshot because a changed default is a breaking change the
   signature alone cannot show. An object whose `repr` carries an address or an iteration
   order does not, because the diff would then be noise.
   """

   if isinstance(value, type):
      return f"{value.__module__}.{value.__qualname__}"

   if isinstance(value, _LITERAL_TYPES):
      return repr(value)

   if isinstance(value, tuple):
      return f"({', '.join(format_value(item) for item in value)})"

   return f"<{type(value).__module__}.{type(value).__qualname__}>"


def format_signature(function: Any) -> str:
   signature = inspect.signature(function)
   rendered: list[str] = []
   kind_seen_keyword_only = False

   for parameter in signature.parameters.values():
      if parameter.kind is inspect.Parameter.KEYWORD_ONLY and not kind_seen_keyword_only:
         kind_seen_keyword_only = True

         rendered.append("*")

      piece = parameter.name

      if parameter.kind is inspect.Parameter.VAR_POSITIONAL:
         piece = f"*{piece}"
         kind_seen_keyword_only = True

      if parameter.kind is inspect.Parameter.VAR_KEYWORD:
         piece = f"**{piece}"

      if parameter.annotation is not inspect.Parameter.empty:
         piece = f"{piece}: {format_annotation(parameter.annotation)}"

      if parameter.default is not inspect.Parameter.empty:
         piece = f"{piece} = {format_value(parameter.default)}"

      rendered.append(piece)

   returns = ""

   if signature.return_annotation is not inspect.Signature.empty:
      returns = f" -> {format_annotation(signature.return_annotation)}"

   return f"({', '.join(rendered)}){returns}"


def class_lines(path: str, subject: type) -> Iterator[str]:
   bases = ", ".join(
      f"{base.__module__}.{base.__qualname__}" for base in subject.__bases__ if base is not object
   )

   yield f"class {path}({bases})"

   field_names: set[str] = set()

   if dataclasses.is_dataclass(subject):
      for entry in dataclasses.fields(subject):
         field_names.add(entry.name)

      for entry in dataclasses.fields(subject):
         line = f"field {path}.{entry.name}: {format_annotation(entry.type)}"

         if entry.default is not dataclasses.MISSING:
            line = f"{line} = {format_value(entry.default)}"

         if entry.default_factory is not dataclasses.MISSING:
            line = f"{line} = <factory {entry.default_factory.__qualname__}>"

         yield line

   for name, member in sorted(vars(subject).items()):
      is_a_dunder_with_contract = name in LIFECYCLE_DUNDERS
      is_private = name.startswith("_") and not is_a_dunder_with_contract

      if is_private:
         continue

      already_rendered_as_a_field = name in field_names
      generated_by_the_dataclass = dataclasses.is_dataclass(subject) and name == "__init__"

      if already_rendered_as_a_field or generated_by_the_dataclass:
         continue

      yield from member_lines(f"{path}.{name}", member)


def member_lines(path: str, member: Any) -> Iterator[str]:
   if isinstance(member, property):
      getter = member.fget
      returns = (
         inspect.Signature.empty if getter is None else inspect.signature(getter).return_annotation
      )

      if returns is inspect.Signature.empty:
         yield f"property {path}"
      else:
         yield f"property {path} -> {format_annotation(returns)}"

      return

   if isinstance(member, classmethod):
      yield f"classmethod {path}{format_signature(member.__func__)}"

      return

   if isinstance(member, staticmethod):
      yield f"staticmethod {path}{format_signature(member.__func__)}"

      return

   if inspect.isfunction(member):
      yield f"def {path}{format_signature(member)}"

      return

   if isinstance(member, type):
      yield from class_lines(path, member)

      return

   yield f"data {path}: {type(member).__qualname__} = {format_value(member)}"


def module_lines(module: ModuleType) -> Iterator[str]:
   for name in declared_names(module):
      subject = getattr(module, name)
      path = f"{module.__name__}.{name}"

      if isinstance(subject, ModuleType):
         continue

      defining_module = getattr(subject, "__module__", module.__name__)
      is_re_exported = defining_module != module.__name__ and defining_module.startswith(PACKAGE)

      if is_re_exported:
         yield f"alias {path} -> {defining_module}.{getattr(subject, '__qualname__', name)}"

         continue

      yield from member_lines(path, subject)


def _sort_key(line: str) -> tuple[str, str]:
   """Sort by the dotted path first, so entries group by name rather than by line kind."""

   kind, _, remainder = line.partition(" ")

   return (remainder, kind)


def render_surface() -> str:
   """The whole snapshot, sorted, with a trailing newline."""

   lines: list[str] = []

   for module in public_modules():
      lines.append(f"module {module.__name__}")
      lines.extend(module_lines(module))

   return "\n".join(sorted(set(lines), key=_sort_key)) + "\n"


def main(argv: list[str] | None = None) -> int:
   parser = argparse.ArgumentParser(description=__doc__)
   parser.add_argument(
      "--write",
      action="store_true",
      help="rewrite tests/public_surface.txt instead of printing the snapshot",
   )
   arguments = parser.parse_args(argv)

   surface = render_surface()

   if arguments.write:
      SNAPSHOT_PATH.write_text(surface, encoding="utf-8")

      return 0

   sys.stdout.write(surface)

   return 0


if __name__ == "__main__":
   raise SystemExit(main())
