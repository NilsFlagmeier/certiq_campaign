from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

from lib.admin_auth import is_admin_request_authenticated, login_redirect_url


ALLOWED_PAGES = {
    "dashboard": "dashboard.html",
    "campaign": "campaign.html",
    "campaign_analytics": "campaign-analytics.html",
    "lead": "lead.html",
}


def _admin_file(page_key: str) -> Path:
    root = Path(__file__).resolve().parents[2]
    filename = ALLOWED_PAGES.get(page_key, "dashboard.html")
    return root / "ui" / filename


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        load_dotenv()
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        page_key = str((query.get("name", ["dashboard"])[0] or "dashboard")).strip()
        requested_path = str((query.get("next", ["/admin"])[0] or "/admin")).strip()

        if page_key not in ALLOWED_PAGES:
            self.send_response(404)
            self.end_headers()
            return

        if not is_admin_request_authenticated(self.headers):
            self.send_response(302)
            self.send_header("Location", login_redirect_url(requested_path))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return

        html_text = _admin_file(page_key).read_text(encoding="utf-8", errors="replace")
        body = html_text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
