import json
from http.server import BaseHTTPRequestHandler

from dotenv import load_dotenv

from lib.admin_auth import is_admin_authenticated


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
        authenticated = is_admin_authenticated(self.headers)
        _json_response(self, 200, {"authenticated": authenticated})
