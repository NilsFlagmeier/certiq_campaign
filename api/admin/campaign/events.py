from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

from lib.admin_api import json_response, require_admin_auth
from lib.campaign_store import list_recent_events


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        load_dotenv()
        if not require_admin_auth(self):
            return

        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        try:
            limit = int((query.get("limit", ["200"])[0] or "200").strip())
        except ValueError:
            limit = 200
        events = list_recent_events(limit=limit)
        json_response(self, 200, {"status": "ok", "events": events, "count": len(events)})
