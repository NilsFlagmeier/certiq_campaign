from http.server import BaseHTTPRequestHandler

from dotenv import load_dotenv

from lib.admin_api import json_response, require_admin_auth
from lib.dashboard_status import integration_status


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
                "integrations": integration_status(),
            },
        )
