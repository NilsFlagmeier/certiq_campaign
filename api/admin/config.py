import json
import os
from http.server import BaseHTTPRequestHandler

from dotenv import load_dotenv

from lib.admin_auth import admin_username, is_admin_request_authenticated


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        load_dotenv()
        if not is_admin_request_authenticated(self.headers):
            _json_response(self, 401, {"status": "error", "message": "Unauthorized"})
            return

        _json_response(
            self,
            200,
            {
                "status": "ok",
                "adminUsername": admin_username(),
                "hasSessionSecret": bool(os.getenv("ADMIN_PORTAL_SESSION_SECRET", "").strip()),
                "hasPasswordHash": bool(
                    os.getenv("ADMIN_PASSWORD_HASH_B64", "").strip() or os.getenv("ADMIN_PASSWORD_HASH", "").strip()
                ),
                "hasLegacyPassword": bool(os.getenv("ADMIN_PORTAL_PASSWORD", "").strip()),
            },
        )
