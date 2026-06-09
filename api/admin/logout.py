import json
import os
from http.server import BaseHTTPRequestHandler

from dotenv import load_dotenv

from lib.admin_auth import expired_session_cookie_header


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
        cookie = expired_session_cookie_header(secure=_is_secure_request(self))
        _json_response(self, 200, {"status": "ok"}, set_cookie=cookie)
