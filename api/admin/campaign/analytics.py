from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

from lib.admin_api import json_response, require_admin_auth
from lib.campaign_analytics_report import build_campaign_analytics_report


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        load_dotenv()
        if not require_admin_auth(self):
            return
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        utm_campaign = str((query.get("utm_campaign", [""])[0] or "").strip())
        try:
            report = build_campaign_analytics_report(utm_campaign=utm_campaign)
            json_response(
                self,
                200,
                {
                    "status": "ok",
                    "utmCampaign": utm_campaign,
                    "report": report,
                },
            )
        except Exception as err:  # noqa: BLE001
            json_response(self, 500, {"status": "error", "message": str(err)})
