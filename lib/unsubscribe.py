import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
from typing import Any


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * ((4 - len(value) % 4) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("utf-8"))


def unsubscribe_secret() -> str:
    return os.environ.get("UNSUBSCRIBE_SECRET", "").strip() or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()


def build_unsubscribe_url(email: str, locale: str = "de") -> str:
    base = os.environ.get("APP_BASE_URL", "https://certiq.tech").strip().rstrip("/")
    payload = {
        "email": email.strip().lower(),
        "locale": "en" if locale == "en" else "de",
        "exp": int(time.time()) + 60 * 60 * 24 * 30,
    }
    payload_b64 = _b64url(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    secret = unsubscribe_secret().encode("utf-8")
    signature = hmac.new(secret, payload_b64.encode("utf-8"), hashlib.sha256).digest()
    token = f"{payload_b64}.{_b64url(signature)}"
    return f"{base}/api/unsubscribe?token={urllib.parse.quote(token)}"


def verify_unsubscribe_token(token: str) -> dict[str, Any] | None:
    if "." not in token:
        return None
    payload_b64, sig_b64 = token.split(".", 1)
    try:
        payload_raw = _b64url_decode(payload_b64)
        signature_raw = _b64url_decode(sig_b64)
    except Exception:
        return None
    expected = hmac.new(unsubscribe_secret().encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).digest()
    if not hmac.compare_digest(signature_raw, expected):
        return None
    try:
        payload = json.loads(payload_raw.decode("utf-8"))
    except Exception:
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    email = str(payload.get("email", "")).strip().lower()
    if "@" not in email:
        return None
    payload["email"] = email
    payload["locale"] = "en" if payload.get("locale") == "en" else "de"
    return payload

