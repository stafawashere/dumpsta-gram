"""Read the Bloks script a web Bloks answer carries its data and its bindings in.

A Bloks answer is a UI tree, and the values a screen shows live in its ``initial_lispy``
strings and in the ``on_bind`` scripts of its components, written as nested calls such as
``(bk.action.array.Make, "a", (bk.action.bool.Const, true))``. This module turns one such
string into :class:`BloksCall` objects, strings and :class:`BloksAtom` objects, and nothing
else: it evaluates nothing, so reading a script can never run what the script would do on the
page.

A string that does not read as that grammar raises
:class:`~dumpstagram.errors.SchemaChanged` with the path of the string, never a partial tree.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from dumpstagram.errors import SchemaChanged

__all__ = ["BloksAtom", "BloksCall", "BloksValue", "read_bloks_script"]


@dataclass(frozen=True)
class BloksAtom:
   """A bare word of the script: a number, ``true``, ``false`` or ``null``."""

   text: str


@dataclass(frozen=True)
class BloksCall:
   """One parenthesised call: the action's name and its arguments in order."""

   name: str
   arguments: tuple[BloksValue, ...]


BloksValue = BloksCall | BloksAtom | str

_TOKEN = re.compile(
   r"\s*(?:(?P<open>\()|(?P<close>\))|(?P<comma>,)"
   r'|(?P<string>"(?:[^"\\]|\\.)*")|(?P<word>[^\s,()"]+))'
)


def _unexpected(path: str, position: int) -> SchemaChanged:
   return SchemaChanged(
      f"{path} is not a Bloks script the engine can read, at character {position}", path=path
   )


def _string_literal(literal: str, path: str, position: int) -> str:
   try:
      value = json.loads(literal)
   except json.JSONDecodeError as error:
      raise _unexpected(path, position) from error

   return str(value)


def read_bloks_script(script: str, path: str) -> BloksValue:
   """The one value ``script`` is, a call, a string or an atom."""

   stack: list[list[BloksValue]] = [[]]
   position = 0
   script_length = len(script.rstrip())

   while position < script_length:
      token = _TOKEN.match(script, position)

      if token is None:
         raise _unexpected(path, position)

      position = token.end()

      if token.group("open") is not None:
         stack.append([])
      elif token.group("close") is not None:
         closes_nothing = len(stack) < 2
         call_parts = [] if closes_nothing else stack.pop()
         name = call_parts[0] if call_parts else None

         if not isinstance(name, BloksAtom):
            raise _unexpected(path, token.start())

         stack[-1].append(BloksCall(name=name.text, arguments=tuple(call_parts[1:])))
      elif token.group("string") is not None:
         stack[-1].append(_string_literal(token.group("string"), path, token.start()))
      elif token.group("word") is not None:
         stack[-1].append(BloksAtom(token.group("word")))

   is_one_complete_value = len(stack) == 1 and len(stack[0]) == 1

   if not is_one_complete_value:
      raise _unexpected(path, position)

   return stack[0][0]
