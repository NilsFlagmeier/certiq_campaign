from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

from lib.admin_api import json_response, require_admin_auth
from lib.campaign_analytics_report import build_campaign_analytics_report
from lib.utm_filter import filter_to_dict, parse_bool_query, utm_filter_from_query


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        load_dotenv()
        if not require_admin_auth(self):
            return
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        utm_filter = utm_filter_from_query(query)
        include_clarity = parse_bool_query(str((query.get("fetch_clarity", [""])[0] or "")))
        try:
            report = build_campaign_analytics_report(
                utm_filter=utm_filter,
                include_clarity=include_clarity,
            )
            json_response(
                self,
                200,
                {
                    "status": "ok",
                    "filters": filter_to_dict(utm_filter),
                    "fetchClarity": include_clarity,
                    "report": report,
                },
            )
        except Exception as err:  # noqa: BLE001
            json_response(self, 500, {"status": "error", "message": str(err)})
