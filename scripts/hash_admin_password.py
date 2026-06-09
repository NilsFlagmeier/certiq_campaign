"""Generate ADMIN_PASSWORD_HASH + ADMIN_PASSWORD_HASH_B64 for a new admin password."""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import secrets
import sys

PBKDF2_ITERATIONS = 260000


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def make_password_hash(password: str, iterations: int = PBKDF2_ITERATIONS) -> tuple[str, str]:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
        dklen=32,
    )
    hash_spec = "pbkdf2_sha256${iterations}${salt}${digest}".format(
        iterations=iterations,
        salt=_b64url_encode(salt),
        digest=_b64url_encode(digest),
    )
    hash_b64 = base64.b64encode(hash_spec.encode("utf-8")).decode("utf-8")
    return hash_spec, hash_b64


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--password", help="Password to hash (omit to prompt securely)")
    args = parser.parse_args()
    password = args.password or getpass.getpass("Admin password: ")
    if not password:
        print("Empty password.", file=sys.stderr)
        return 1
    hash_spec, hash_b64 = make_password_hash(password)
    print("Add to .env:")
    print(f"ADMIN_PASSWORD_HASH={hash_spec}")
    print(f"ADMIN_PASSWORD_HASH_B64={hash_b64}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
