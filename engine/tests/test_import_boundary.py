"""Gates on the import boundary, the first row of the Phase 2 gates still ahead in gates.md.

The rules come from ``docs/engineering/01-architecture-practices.md`` and
``docs/architecture.md``. ``_core`` drives ``_private``, never the other way round. Nothing
inside the package imports its own public surface back through ``dumpstagram/__init__.py``.
Nothing outside ``_core`` imports ``_private``, with one named exception: ``aio.py`` is where
the client assembles an injected transport and the upstream hosts with the ``_core`` that uses
them, which is the assembly 01 asks for. And the public surface, every name a public module
declares and every annotation on it, never hands a caller an object defined behind an
underscore, which 02 states as "the advanced path does not require knowing that ``_core`` or
``_private`` exist".

The import rules are read from the source with ``ast``, so a function-level import counts as
much as a module-level one, and each carries a positive control: an edge that exists today and
that the same scan has to find, so a scan that reads nothing cannot pass.
"""

from __future__ import annotations

import ast
import builtins
import inspect
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

ENGINE_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_ROOT = ENGINE_ROOT / "dumpstagram"

sys.path.insert(0, str(ENGINE_ROOT / "scripts"))

import snapshot_surface  # noqa: E402

ASSEMBLY_MODULES = frozenset({"dumpstagram.aio"})


def module_name_of(path: Path) -> str:
   relative = path.relative_to(ENGINE_ROOT).with_suffix("")
   parts = list(relative.parts)

   if parts[-1] == "__init__":
      parts.pop()

   return ".".join(parts)


def imported_modules(path: Path) -> Iterator[str]:
   """Every module a file imports, relative imports resolved, names imported from a package
   counted as the submodule they may be."""

   tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
   own_name = module_name_of(path)
   is_package = path.name == "__init__.py"
   package_parts = own_name.split(".") if is_package else own_name.split(".")[:-1]

   for node in ast.walk(tree):
      if isinstance(node, ast.Import):
         for alias in node.names:
            yield alias.name

      if isinstance(node, ast.ImportFrom):
         if node.level:
            base_parts = package_parts[: len(package_parts) - node.level + 1]
            base = ".".join(base_parts + ([node.module] if node.module else []))
         else:
            base = node.module or ""

         yield base

         for alias in node.names:
            yield f"{base}.{alias.name}"


def import_edges() -> list[tuple[str, str]]:
   edges = []

   for path in sorted(PACKAGE_ROOT.rglob("*.py")):
      importer = module_name_of(path)

      for imported in imported_modules(path):
         edges.append((importer, imported))

   return edges


def is_within(module: str, package: str) -> bool:
   return module == package or module.startswith(f"{package}.")


@pytest.fixture(scope="module")
def edges() -> list[tuple[str, str]]:
   return import_edges()


def test_private_never_imports_core(edges: list[tuple[str, str]]) -> None:
   """Catches ``_private`` reaching up into ``_core``, which ties the surface adapter to one
   caller and makes a second adapter, the mobile one ADR-0007 defers, a rewrite."""

   core_importing_private = [
      (importer, imported)
      for importer, imported in edges
      if is_within(importer, "dumpstagram._core") and is_within(imported, "dumpstagram._private")
   ]
   private_importing_core = [
      (importer, imported)
      for importer, imported in edges
      if is_within(importer, "dumpstagram._private") and is_within(imported, "dumpstagram._core")
   ]

   assert (
      "dumpstagram._core.requesting",
      "dumpstagram._private.transport",
   ) in core_importing_private
   assert private_importing_core == []


def test_nothing_inside_the_package_imports_its_public_root(edges: list[tuple[str, str]]) -> None:
   """Catches an internal module importing a name through ``dumpstagram/__init__.py``, which is
   a cycle the moment the surface grows. A gate file that does import through the root is the
   control, so the scan is shown to see that form."""

   control = set(imported_modules(ENGINE_ROOT / "tests" / "test_errors.py"))
   through_the_root = [
      (importer, imported) for importer, imported in edges if imported == "dumpstagram"
   ]

   assert "dumpstagram" in control
   assert through_the_root == []


def test_only_the_assembly_imports_private_from_outside_core(
   edges: list[tuple[str, str]],
) -> None:
   """Catches a public module, a model or the command line importing ``_private`` directly,
   which puts a header or a query shape one step from the public surface."""

   outside_core = [
      (importer, imported)
      for importer, imported in edges
      if is_within(imported, "dumpstagram._private")
      and not is_within(importer, "dumpstagram._core")
      and not is_within(importer, "dumpstagram._private")
   ]
   importers = {importer for importer, _ in outside_core}

   assert "dumpstagram.aio" in importers
   assert importers - ASSEMBLY_MODULES == set()


def is_internal(module: str | None) -> bool:
   if not module:
      return False

   parts = module.split(".")
   is_ours = parts[0] == "dumpstagram"

   return is_ours and any(part.startswith("_") for part in parts[1:])


def names_in(annotation: Any) -> Iterator[str]:
   """Every dotted name an annotation mentions, read from its source text.

   The package writes ``from __future__ import annotations``, so annotations are strings, and
   reading them as text avoids evaluating a type parameter such as ``ItemT`` out of scope.
   """

   text = annotation if isinstance(annotation, str) else getattr(annotation, "__name__", "")

   if not text:
      return

   for node in ast.walk(ast.parse(text, mode="eval")):
      if isinstance(node, ast.Name):
         yield node.id

      if isinstance(node, ast.Attribute):
         yield ast.unparse(node)


def resolve(dotted: str, namespace: dict[str, Any]) -> Any:
   head, *rest = dotted.split(".")
   resolved = namespace.get(head, getattr(builtins, head, None))

   for part in rest:
      resolved = getattr(resolved, part, None)

   return resolved


def raw_annotations(target: Any) -> dict[str, Any]:
   unwrapped = target

   if isinstance(unwrapped, staticmethod | classmethod):
      unwrapped = unwrapped.__func__

   if isinstance(unwrapped, property):
      unwrapped = unwrapped.fget

   if not callable(unwrapped):
      return {}

   return dict(inspect.get_annotations(unwrapped))


def public_members(owner: type) -> Iterator[tuple[str, Any]]:
   for name, member in vars(owner).items():
      is_public = not name.startswith("_") or name in snapshot_surface.LIFECYCLE_DUNDERS

      if is_public:
         yield name, member


def exposures() -> Iterator[tuple[str, Any]]:
   """Every object the public surface hands a caller: each declared name, and each name its
   public signatures and fields annotate with, resolved where it was written."""

   for module in snapshot_surface.public_modules():
      for name in snapshot_surface.declared_names(module):
         value = getattr(module, name)
         qualified = f"{module.__name__}.{name}"

         yield qualified, value

         defining_module = getattr(value, "__module__", None) or module.__name__
         namespace = vars(sys.modules.get(defining_module, module))
         annotated: list[tuple[str, Any]] = []

         if isinstance(value, type):
            for base in reversed(value.__mro__):
               if not base.__module__.startswith("dumpstagram"):
                  continue

               for field_name, text in inspect.get_annotations(base).items():
                  if not field_name.startswith("_"):
                     annotated.append((f"{qualified}.{field_name}", text))

            for member_name, member in public_members(value):
               annotated.extend(
                  (f"{qualified}.{member_name}", text) for text in raw_annotations(member).values()
               )
         else:
            annotated.extend((qualified, text) for text in raw_annotations(value).values())

         for where, text in annotated:
            for mentioned in names_in(text):
               resolved = resolve(mentioned, namespace)

               if resolved is not None:
                  yield where, resolved


def test_the_public_surface_exposes_nothing_defined_behind_an_underscore() -> None:
   """Catches ``__all__`` re-exporting an internal class, and a public signature or field whose
   annotation names one, either of which makes a caller import ``_core`` to type their code."""

   leaks = []
   seen_names = set()

   for where, exposed in exposures():
      defined_in = getattr(exposed, "__module__", None)
      seen_names.add(getattr(exposed, "__name__", ""))

      if isinstance(defined_in, str) and is_internal(defined_in):
         leaks.append((where, getattr(exposed, "__qualname__", repr(exposed))))

   assert {"Session", "Event", "Behavior", "EventListener", "Page", "Callable"} <= seen_names
   assert leaks == []


def test_is_internal_reads_the_whole_dotted_path() -> None:
   assert is_internal("dumpstagram._core.realtime.buffer")
   assert is_internal("dumpstagram._private.transport")
   assert not is_internal("dumpstagram.models.events")
   assert not is_internal("builtins")
