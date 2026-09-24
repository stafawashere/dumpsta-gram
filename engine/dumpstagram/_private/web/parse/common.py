"""The readers every domain's mapper is built from.

A missing required key raises :class:`~dumpstagram.errors.SchemaChanged` carrying the path
that was missing, and nothing here supplies a default the upstream did not send.
"""

from __future__ import annotations

from typing import Any

from dumpstagram.errors import SchemaChanged

MILLISECONDS_PER_SECOND = 1000


def _object_at(payload: Any, path: tuple[str, ...]) -> dict[str, Any]:
   """Walk ``path``, raising with the exact prefix that stopped resolving."""

   current = payload

   for depth, key in enumerate(path):
      reached = ".".join(path[: depth + 1])

      if not isinstance(current, dict):
         raise SchemaChanged(
            f"{reached} is not reachable, its parent is not an object", path=reached
         )

      if key not in current:
         raise SchemaChanged(f"{reached} is missing from the payload", path=reached)

      current = current[key]

   if not isinstance(current, dict):
      raise SchemaChanged(f"{'.'.join(path)} is not an object", path=".".join(path))

   return current


def _required(node: Any, key: str, path: str) -> Any:
   if not isinstance(node, dict) or key not in node:
      raise SchemaChanged(f"{path}.{key} is missing from the payload", path=f"{path}.{key}")

   return node[key]


def _required_string(node: Any, key: str, path: str) -> str:
   value = _required(node, key, path)

   if not isinstance(value, str):
      raise SchemaChanged(f"{path}.{key} is not a string", path=f"{path}.{key}")

   return value


def _required_flag(node: Any, key: str, path: str) -> bool:
   value = _required(node, key, path)

   if not isinstance(value, bool):
      raise SchemaChanged(f"{path}.{key} is not a boolean", path=f"{path}.{key}")

   return value


def _optional_flag(node: dict[str, Any], key: str, path: str) -> bool | None:
   value = _required(node, key, path)

   if value is None:
      return None

   if not isinstance(value, bool):
      raise SchemaChanged(f"{path}.{key} is not a boolean or null", path=f"{path}.{key}")

   return value


def _optional_string(node: dict[str, Any], key: str, path: str) -> str | None:
   value = _required(node, key, path)

   if value is None:
      return None

   if not isinstance(value, str):
      raise SchemaChanged(f"{path}.{key} is not a string or null", path=f"{path}.{key}")

   return value


def _required_integer(node: Any, key: str, path: str) -> int:
   value = _required(node, key, path)

   if isinstance(value, bool) or not isinstance(value, int):
      raise SchemaChanged(f"{path}.{key} is not an integer", path=f"{path}.{key}")

   return value


def _hd_profile_pic_url(node: dict[str, Any], path: str) -> str | None:
   """The high resolution avatar, which arrives wrapped in a one-key object.

   The wrapper resolving to something other than an object is not treated as absent, because
   an unexpected shape there is the upstream changing and not the account lacking a picture.
   """

   raw = _required(node, "hd_profile_pic_url_info", path)

   if raw is None:
      return None

   if not isinstance(raw, dict):
      raise SchemaChanged(
         f"{path}.hd_profile_pic_url_info is not an object or null",
         path=f"{path}.hd_profile_pic_url_info",
      )

   return _optional_string(raw, "url", f"{path}.hd_profile_pic_url_info")


def _optional_integer(node: dict[str, Any], key: str, path: str) -> int | None:
   value = _required(node, key, path)

   if value is None:
      return None

   if isinstance(value, bool) or not isinstance(value, int):
      raise SchemaChanged(f"{path}.{key} is not an integer or null", path=f"{path}.{key}")

   return value
