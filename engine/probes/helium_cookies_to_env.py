"""No requests. Copies an Instagram session out of a local Helium profile into an env file.

Reads the profile's Cookies database, decrypts the three cookies the engine needs with the
"Helium Safe Storage" key from the login keychain, and writes them to the env file named on the
command line. No cookie value is printed or logged, only which keys were found.

   uv run python probes/helium_cookies_to_env.py "Profile 1" ../.env.account-c
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

HELIUM_ROOT = Path.home() / "Library" / "Application Support" / "net.imput.helium"
COOKIE_TO_ENV_KEY = {
   "sessionid": "IG_SESSIONID",
   "ds_user_id": "IG_DS_USER_ID",
   "csrftoken": "IG_CSRFTOKEN",
}


def safe_storage_key() -> bytes:
   command = ["security", "find-generic-password", "-w", "-s", "Helium Safe Storage"]
   password = subprocess.run(command, capture_output=True, text=True, check=True).stdout.strip()

   return hashlib.pbkdf2_hmac("sha1", password.encode(), b"saltysalt", 1003, 16)


def decrypt(encrypted_value: bytes, key: bytes, host_key: str) -> str:
   cipher = Cipher(algorithms.AES(key), modes.CBC(b" " * 16))
   decryptor = cipher.decryptor()
   padded = decryptor.update(encrypted_value[3:]) + decryptor.finalize()
   plain = padded[: -padded[-1]]
   host_digest = hashlib.sha256(host_key.encode()).digest()
   has_host_prefix = plain.startswith(host_digest)

   if has_host_prefix:
      plain = plain[32:]

   return plain.decode()


def main() -> int:
   parser = argparse.ArgumentParser()
   parser.add_argument("profile")
   parser.add_argument("env_file", type=Path)
   arguments = parser.parse_args()

   source = HELIUM_ROOT / arguments.profile / "Cookies"

   with tempfile.TemporaryDirectory() as scratch:
      copy = Path(scratch) / "Cookies"
      shutil.copy(source, copy)
      rows = (
         sqlite3.connect(copy)
         .execute(
            "select name, encrypted_value, host_key from cookies where host_key like '%instagram.com'"
         )
         .fetchall()
      )

   key = safe_storage_key()
   found: dict[str, str] = {}

   for name, encrypted_value, host_key in rows:
      if name in COOKIE_TO_ENV_KEY:
         found[COOKIE_TO_ENV_KEY[name]] = decrypt(encrypted_value, key, host_key)

   missing = sorted(set(COOKIE_TO_ENV_KEY.values()) - set(found))

   if missing:
      print(f"missing {missing}")
      return 1

   lines = [f"{env_key}={value}" for env_key, value in sorted(found.items())]
   arguments.env_file.write_text("\n".join(lines) + "\n")
   arguments.env_file.chmod(0o600)
   print(f"wrote {sorted(found)} to {arguments.env_file}")

   return 0


if __name__ == "__main__":
   sys.exit(main())
