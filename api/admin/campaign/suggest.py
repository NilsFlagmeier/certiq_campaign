from http.server import BaseHTTPRequestHandler

from dotenv import load_dotenv

from lib.admin_api import json_response, read_json_body, require_admin_auth
from lib.campaign_ai_suggest import default_model, is_available, suggest_email


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        load_dotenv()
        if not require_admin_auth(self):
            return
        json_response(
            self,
            200,
            {
                "status": "ok",
                "available": is_available(),
                "model": default_model() if is_available() else None,
            },
        )

    def do_POST(self) -> None:  # noqa: N802
        load_dotenv()
        if not require_admin_auth(self):
            return
        payload = read_json_body(self)
        topic = str(payload.get("topic", "Certiq follow-up")).strip() or "Certiq follow-up"
        company = str(payload.get("company", "")).strip()
        addressing = str(payload.get("addressing", "sie")).strip().lower() or "sie"
        suggestion = suggest_email(topic=topic, company=company, addressing=addressing)
        json_response(self, 200, {"status": "ok", "suggestion": suggestion})
