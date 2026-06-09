from http.server import BaseHTTPRequestHandler

from dotenv import load_dotenv

from lib.admin_api import json_response, read_json_body, require_admin_auth
from lib.resend_campaign_sync import sync_resend_to_campaign_store


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        load_dotenv()
        if not require_admin_auth(self):
            return
        payload = read_json_body(self)
        try:
            limit = int(str(payload.get("limit", "100")).strip())
        except ValueError:
            limit = 100
        result = sync_resend_to_campaign_store(limit=limit)
        json_response(self, 200, {"status": "ok", **result})
