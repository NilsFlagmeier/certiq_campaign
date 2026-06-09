import json
import os
from http.server import BaseHTTPRequestHandler

from lib.admin_auth import is_admin_request_authenticated


def is_secure_request(handler: BaseHTTPRequestHandler) -> bool:
    proto = (handler.headers.get("x-forwarded-proto", "") or "").lower()
    if proto:
        return proto == "https"
    return bool(os.getenv("VERCEL", "").strip())


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json_body(handler: BaseHTTPRequestHandler) -> dict:
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError:
        length = 0
    raw = handler.rfile.read(length) if length > 0 else b"{}"
    try:
        payload = json.loads(raw.decode("utf-8"))
        return payload if isinstance(payload, dict) else {}
    except json.JSONDecodeError:
        return {}


def require_admin_auth(handler: BaseHTTPRequestHandler) -> bool:
    if is_admin_request_authenticated(handler.headers):
        return True
    json_response(handler, 401, {"status": "error", "message": "Unauthorized"})
    return False
