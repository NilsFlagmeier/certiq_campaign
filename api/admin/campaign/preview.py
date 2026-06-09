from http.server import BaseHTTPRequestHandler

from dotenv import load_dotenv

from lib.admin_api import json_response, read_json_body, require_admin_auth
from lib.campaign_admin import preview_campaign_email


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        load_dotenv()
        if not require_admin_auth(self):
            return
        payload = read_json_body(self)
        lead_id = str(payload.get("leadId", "")).strip()
        if not lead_id:
            json_response(self, 400, {"status": "error", "message": "Missing leadId"})
            return
        content = payload.get("content") if isinstance(payload.get("content"), dict) else {}
        utm = payload.get("utm") if isinstance(payload.get("utm"), dict) else {}
        subject = str(content.get("subject", "Certiq Intro")).strip() or "Certiq Intro"
        paragraphs = content.get("paragraphs") if isinstance(content.get("paragraphs"), list) else []
        paragraphs = [str(item).strip() for item in paragraphs if str(item).strip()]
        cta_label = str(content.get("ctaLabel", "Mehr erfahren")).strip() or "Mehr erfahren"
        signature = str(content.get("signature", "Viele Gruesse\nCertiq Team")).strip() or "Viele Gruesse\nCertiq Team"
        addressing = str(content.get("addressing", "du")).strip().lower() or "du"
        utm_payload = {
            "utm_source": str(utm.get("utm_source", "newsletter")).strip() or "newsletter",
            "utm_medium": str(utm.get("utm_medium", "email")).strip() or "email",
            "utm_campaign": str(utm.get("utm_campaign", "certiq_campaign")).strip() or "certiq_campaign",
        }
        try:
            preview = preview_campaign_email(
                lead_id=lead_id,
                subject=subject,
                paragraphs=paragraphs,
                cta_label=cta_label,
                signature=signature,
                utm=utm_payload,
                addressing=addressing,
            )
            json_response(self, 200, {"status": "ok", **preview})
        except Exception as err:  # noqa: BLE001
            json_response(self, 500, {"status": "error", "message": str(err)})
