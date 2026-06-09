from http.server import BaseHTTPRequestHandler

from dotenv import load_dotenv

from lib.admin_api import json_response, require_admin_auth
from lib.campaign_sync import sync_last_contact_to_twenty


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        load_dotenv()
        if not require_admin_auth(self):
            return
        try:
            twenty_result = sync_last_contact_to_twenty()
        except Exception as err:  # noqa: BLE001
            json_response(self, 500, {"status": "error", "message": f"Twenty sync failed: {err}"})
            return

        json_response(
            self,
            200,
            {
                "status": "ok",
                "twenty": twenty_result,
            },
        )
