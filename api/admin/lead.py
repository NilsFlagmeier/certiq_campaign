import json
import os
import re
from http.server import BaseHTTPRequestHandler
from urllib.parse import quote

from dotenv import load_dotenv

from lib.admin_auth import is_admin_request_authenticated
from lib.twenty_crm import create_lead_from_intake, get_twenty_config


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _normalize_phone(raw_phone: str) -> str:
    phone = (raw_phone or "").strip()
    cleaned = []
    for idx, char in enumerate(phone):
        if char.isdigit():
            cleaned.append(char)
        elif char == "+" and idx == 0:
            cleaned.append(char)
    normalized = "".join(cleaned)
    if normalized.startswith("00"):
        normalized = "+" + normalized[2:]
    elif normalized.startswith("0"):
        normalized = "+49" + normalized[1:]
    return normalized


def _tracking_link(person_id: str, sequence: str, variante: str = "A") -> str:
    return (
        "https://certiq.tech/"
        f"?user_id={quote(person_id, safe='')}"
        "&utm_source=newsletter"
        "&utm_medium=email"
        f"&utm_campaign={quote(sequence, safe='')}"
        f"&utm_content={quote(variante, safe='')}"
    )


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        load_dotenv()
        if os.getenv("VERCEL", "").strip() and os.getenv("ALLOW_REMOTE_INGEST", "").strip().lower() != "true":
            _json_response(
                self,
                403,
                {
                    "status": "error",
                    "message": "Lead ingestion is disabled in deployed environments.",
                },
            )
            return
        has_session = is_admin_request_authenticated(self.headers)
        if not has_session:
            expected = os.getenv("ADMIN_INGEST_TOKEN", "").strip()
            auth = self.headers.get("Authorization", "")
            if not expected or auth != f"Bearer {expected}":
                _json_response(self, 401, {"status": "error", "message": "Unauthorized"})
                return

        try:
            get_twenty_config()
        except RuntimeError:
            _json_response(self, 500, {"status": "error", "message": "Missing Twenty CRM config"})
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
        except Exception:
            _json_response(self, 400, {"status": "error", "message": "Invalid JSON"})
            return

        email = str(body.get("email", "")).strip().lower()
        if not EMAIL_RE.match(email):
            _json_response(self, 400, {"status": "error", "message": "Invalid email"})
            return

        sequence = "business_card_intro"
        consent_source = str(body.get("consentSource", "")).strip() or "Visitenkarte"
        try:
            result = create_lead_from_intake(
                email=email,
                first_name=str(body.get("firstName", "")).strip(),
                last_name=str(body.get("lastName", "")).strip(),
                company=str(body.get("company", "")).strip(),
                consent_source=consent_source,
                sequence=sequence,
            )
        except Exception as err:  # noqa: BLE001
            _json_response(self, 500, {"status": "error", "message": str(err)})
            return

        person = result["person"]
        person_id = person.get("person_id") or ""
        link = _tracking_link(person_id, sequence)
        message = "Kontakt wurde in Twenty gespeichert." if result.get("created") else "Kontakt existiert bereits in Twenty."
        _json_response(
            self,
            200,
            {
                "status": "ok",
                "kundenId": person_id,
                "personId": person_id,
                "created": bool(result.get("created")),
                "message": message,
                "link": link,
                "phone": _normalize_phone(str(body.get("phone", ""))),
            },
        )
