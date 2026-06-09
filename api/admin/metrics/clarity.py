import os
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler

from dotenv import load_dotenv

from lib.admin_api import json_response, require_admin_auth
from lib.clarity_export import fetch_live_insights


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        load_dotenv()
        if not require_admin_auth(self):
            return

        api_token = os.getenv("CLARITY_TOKEN", "").strip()
        project_id = os.getenv("CLARITY_PROJECT_ID", "").strip()
        if not api_token:
            json_response(
                self,
                200,
                {
                    "status": "ok",
                    "configured": False,
                    "message": "CLARITY_TOKEN fehlt — in Clarity unter Settings → Data Export erzeugen",
                },
            )
            return

        try:
            response = fetch_live_insights(
                api_token,
                num_of_days=3,
                dimensions=["URL"],
            )
            json_response(
                self,
                200,
                {
                    "status": "ok",
                    "configured": True,
                    "projectId": project_id or None,
                    "fetchedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                    "data": response,
                },
            )
        except Exception as err:  # noqa: BLE001
            json_response(self, 502, {"status": "error", "message": str(err)})
