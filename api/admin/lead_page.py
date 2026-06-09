from http.server import BaseHTTPRequestHandler
from pathlib import Path

from dotenv import load_dotenv

from lib.admin_auth import is_admin_authenticated, login_redirect_url


def _lead_file() -> Path:
    root = Path(__file__).resolve().parents[2]
    return root / "ui" / "lead.html"


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        load_dotenv()
        if not is_admin_authenticated(self.headers):
            self.send_response(302)
            self.send_header("Location", login_redirect_url("/admin/lead"))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return

        html_text = _lead_file().read_text(encoding="utf-8", errors="replace")
        body = html_text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
