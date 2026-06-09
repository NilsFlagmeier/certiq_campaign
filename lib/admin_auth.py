import base64
import hashlib
import hmac
import json
import os
import time
from http.client import HTTPMessage
from urllib.parse import quote


SESSION_COOKIE_NAME = "certiq_admin_session"
SESSION_TTL_SECONDS = 60 * 60 * 12  # 12 hours
PBKDF2_ITERATIONS_DEFAULT = 260000


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("utf-8"))


def _cookie_dict(headers: HTTPMessage) -> dict[str, str]:
    raw = headers.get("Cookie", "")
    items: dict[str, str] = {}
    for segment in raw.split(";"):
        if "=" not in segment:
            continue
        key, value = segment.split("=", 1)
        items[key.strip()] = value.strip()
    return items


def _session_secret() -> str:
    return (
        os.getenv("ADMIN_PORTAL_SESSION_SECRET", "").strip()
        or os.getenv("UNSUBSCRIBE_SECRET", "").strip()
        or os.getenv("ADMIN_INGEST_TOKEN", "").strip()
    )


def admin_username() -> str:
    return os.getenv("ADMIN_USERNAME", "admin").strip() or "admin"


def _sign_payload(payload_b64: str, secret: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).digest()
    return _b64url_encode(digest)


def _safe_parse_int(value: str, fallback: int) -> int:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else fallback
    except (TypeError, ValueError):
        return fallback


def _verify_password_with_pbkdf2(submitted_password: str, hash_spec: str) -> bool:
    # Format: pbkdf2_sha256$<iterations>$<salt_b64>$<digest_b64>
    parts = hash_spec.split("$")
    if len(parts) != 4:
        return False
    _, iterations_raw, salt_b64, digest_b64 = parts
    iterations = _safe_parse_int(iterations_raw, PBKDF2_ITERATIONS_DEFAULT)
    try:
        salt = _b64url_decode(salt_b64)
        expected_digest = _b64url_decode(digest_b64)
    except Exception:
        return False
    candidate_digest = hashlib.pbkdf2_hmac(
        "sha256",
        submitted_password.encode("utf-8"),
        salt,
        iterations,
        dklen=len(expected_digest),
    )
    return hmac.compare_digest(candidate_digest, expected_digest)


def _verify_password_with_sha256(submitted_password: str, hash_spec: str) -> bool:
    # Format: sha256$<hex_digest>
    parts = hash_spec.split("$", 1)
    if len(parts) != 2:
        return False
    expected_hex = parts[1].strip().lower()
    candidate_hex = hashlib.sha256(submitted_password.encode("utf-8")).hexdigest().lower()
    return hmac.compare_digest(candidate_hex, expected_hex)


def _decode_hash_env_value(raw: str) -> str:
    if not raw:
        return ""
    try:
        return base64.b64decode(raw.encode("utf-8")).decode("utf-8").strip()
    except Exception:
        # If value is not valid base64 we keep it untouched for backward compatibility.
        return raw.strip()


def verify_admin_credentials(submitted_username: str, submitted_password: str) -> bool:
    expected_username = admin_username()
    if not hmac.compare_digest((submitted_username or "").strip(), expected_username):
        return False

    hash_b64 = os.getenv("ADMIN_PASSWORD_HASH_B64", "").strip()
    hash_raw = os.getenv("ADMIN_PASSWORD_HASH", "").strip()
    plaintext_fallback = os.getenv("ADMIN_PORTAL_PASSWORD", "").strip()
    hash_spec = _decode_hash_env_value(hash_b64) or hash_raw

    if hash_spec:
        if hash_spec.startswith("pbkdf2_sha256$"):
            return _verify_password_with_pbkdf2(submitted_password, hash_spec)
        if hash_spec.startswith("sha256$"):
            return _verify_password_with_sha256(submitted_password, hash_spec)
        # Legacy fallback: treat non-prefixed hash value as plaintext.
        return hmac.compare_digest(submitted_password, hash_spec)

    if plaintext_fallback:
        return hmac.compare_digest(submitted_password, plaintext_fallback)
    return False


def create_session_token(username: str = "admin") -> str | None:
    secret = _session_secret()
    if not secret:
        return None
    ttl_seconds = _safe_parse_int(os.getenv("ADMIN_SESSION_TTL_SECONDS", "").strip(), SESSION_TTL_SECONDS)
    now = int(time.time())
    expires_at = now + ttl_seconds
    payload = {"sub": username, "iat": now, "exp": expires_at}
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signature = _sign_payload(payload_b64, secret)
    return f"{payload_b64}.{signature}"


def is_admin_authenticated(headers: HTTPMessage) -> bool:
    token = _cookie_dict(headers).get(SESSION_COOKIE_NAME, "")
    if not token or "." not in token:
        return False
    payload_b64, provided_signature = token.split(".", 1)
    secret = _session_secret()
    if not secret:
        return False
    expected_signature = _sign_payload(payload_b64, secret)
    if not hmac.compare_digest(provided_signature, expected_signature):
        return False
    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception:
        return False
    exp = int(payload.get("exp", 0))
    return exp > int(time.time())


def is_admin_request_authenticated(headers: HTTPMessage) -> bool:
    return is_admin_authenticated(headers)


def session_cookie_header(token: str, secure: bool) -> str:
    ttl_seconds = _safe_parse_int(os.getenv("ADMIN_SESSION_TTL_SECONDS", "").strip(), SESSION_TTL_SECONDS)
    cookie = (
        f"{SESSION_COOKIE_NAME}={token}; Max-Age={ttl_seconds}; "
        "Path=/; HttpOnly; SameSite=Lax"
    )
    if secure:
        cookie += "; Secure"
    return cookie


def expired_session_cookie_header(secure: bool) -> str:
    cookie = (
        f"{SESSION_COOKIE_NAME}=; Max-Age=0; Path=/; HttpOnly; SameSite=Lax"
    )
    if secure:
        cookie += "; Secure"
    return cookie


def login_redirect_url(next_path: str = "") -> str:
    cleaned = (next_path or "").strip()
    if cleaned and cleaned.startswith("/") and not cleaned.startswith("//"):
        return f"/admin/login?next={quote(cleaned, safe='')}"
    return "/admin/login"
