import json
import os
from http.server import BaseHTTPRequestHandler

from dotenv import load_dotenv

from lib.admin_auth import (
    admin_username,
    create_session_token,
    session_cookie_header,
    verify_admin_credentials,
)


def _json_response(
    handler: BaseHTTPRequestHandler,
    status: int,
    payload: dict,
    set_cookie: str | None = None,
) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    if set_cookie:
        handler.send_header("Set-Cookie", set_cookie)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _is_secure_request(handler: BaseHTTPRequestHandler) -> bool:
    proto = (handler.headers.get("x-forwarded-proto", "") or "").lower()
    if proto:
        return proto == "https"
    return bool(os.getenv("VERCEL", "").strip())


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        load_dotenv()

        has_any_auth_config = bool(
            os.getenv("ADMIN_PASSWORD_HASH_B64", "").strip()
            or os.getenv("ADMIN_PASSWORD_HASH", "").strip()
            or os.getenv("ADMIN_PORTAL_PASSWORD", "").strip()
        )
        if not has_any_auth_config:
            _json_response(
                self,
                500,
                {"status": "error", "message": "Missing admin credential configuration"},
            )
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            _json_response(self, 400, {"status": "error", "message": "Invalid JSON body"})
            return

        submitted_username = str(payload.get("username", "")).strip()
        submitted_password = str(payload.get("password", "")).strip()
        if not verify_admin_credentials(submitted_username, submitted_password):
            _json_response(self, 401, {"status": "error", "message": "Invalid credentials"})
            return

        token = create_session_token(username=submitted_username or admin_username())
        if not token:
            _json_response(
                self,
                500,
                {"status": "error", "message": "Missing admin session secret configuration"},
            )
            return

        cookie = session_cookie_header(token, secure=_is_secure_request(self))
        _json_response(self, 200, {"status": "ok", "username": submitted_username or admin_username()}, set_cookie=cookie)
