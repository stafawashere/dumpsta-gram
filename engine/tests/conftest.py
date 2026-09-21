"""Environment guard.

The engine has been broken three times by the same fault, and it is silent every time: the
sync agent on `~/Documents` sets the macOS `UF_HIDDEN` flag on the `.pth` files inside an
in-tree `.venv`, CPython's `site` skips a hidden `.pth`, and the editable install drops off
`sys.path`. Collection then fails with `ModuleNotFoundError: No module named 'dumpstagram'`,
which reads like a packaging mistake rather than a filesystem one.

This guard names the real cause before the first test runs. It checks the interpreter that is
actually executing, so it fires on a fallback environment as loudly as on a flagged one.
"""

import os
import stat
import sys
import sysconfig

import pytest

SYNC_MANAGED_PREFIXES = ("/Users/mahfujm/Documents",)
EXPECTED_ENVIRONMENT = "/Users/mahfujm/venvs/dumpstagram-engine"


def hidden_pth_files(site_packages):
   if not os.path.isdir(site_packages):
      return []

   flagged = []

   for name in sorted(os.listdir(site_packages)):
      if not name.endswith(".pth"):
         continue

      path = os.path.join(site_packages, name)
      flags = getattr(os.stat(path), "st_flags", 0)

      if flags & stat.UF_HIDDEN:
         flagged.append(name)

   return flagged


def pytest_configure(config):
   prefix = os.path.realpath(sys.prefix)
   site_packages = sysconfig.get_paths()["purelib"]

   for managed in SYNC_MANAGED_PREFIXES:
      if prefix.startswith(os.path.realpath(managed)):
         raise pytest.UsageError(
            f"environment {prefix} is inside the sync-managed tree {managed}. "
            f"Export UV_PROJECT_ENVIRONMENT={EXPECTED_ENVIRONMENT} and rerun. "
            "See engine/docs/engineering/project-profile.md"
         )

   flagged = hidden_pth_files(site_packages)

   if flagged:
      names = ", ".join(flagged)

      raise pytest.UsageError(
         "these .pth files carry the macOS hidden flag, so site skipped them and the editable "
         f"install is not on sys.path: {names}. Clear with `chflags nohidden` in "
         f"{site_packages}, and move the environment out of the sync-managed tree so it does "
         "not come back."
      )
