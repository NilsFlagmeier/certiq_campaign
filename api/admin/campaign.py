from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

from lib.admin_api import json_response, read_json_body, require_admin_auth
from lib.campaign_admin import load_campaign_recipients, send_campaign_batch


def _utm_from_payload(payload: dict) -> dict[str, str]:
    raw = payload.get("utm") if isinstance(payload.get("utm"), dict) else {}
    return {
        "utm_source": str(raw.get("utm_source", "newsletter")).strip() or "newsletter",
        "utm_medium": str(raw.get("utm_medium", "email")).strip() or "email",
        "utm_campaign": str(raw.get("utm_campaign", "certiq_campaign")).strip() or "certiq_campaign",
    }


def _utm_from_query(query: dict) -> dict[str, str]:
    return {
        "utm_source": str((query.get("utm_source", ["newsletter"])[0] or "newsletter")).strip() or "newsletter",
        "utm_medium": str((query.get("utm_medium", ["email"])[0] or "email")).strip() or "email",
        "utm_campaign": str((query.get("utm_campaign", ["certiq_campaign"])[0] or "certiq_campaign")).strip()
        or "certiq_campaign",
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        load_dotenv()
        if not require_admin_auth(self):
            return
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        utm = _utm_from_query(query)
        try:
            data = load_campaign_recipients(utm=utm)
            json_response(self, 200, {"status": "ok", **data})
        except Exception as err:  # noqa: BLE001
            json_response(self, 500, {"status": "error", "message": str(err)})

    def do_POST(self) -> None:  # noqa: N802
        load_dotenv()
        if not require_admin_auth(self):
            return
        payload = read_json_body(self)
        utm = _utm_from_payload(payload)
        dry_run = bool(payload.get("dryRun", False))
        content = payload.get("content") if isinstance(payload.get("content"), dict) else {}
        subject = str(content.get("subject", "Certiq Intro")).strip() or "Certiq Intro"
        paragraphs = content.get("paragraphs") if isinstance(content.get("paragraphs"), list) else []
        paragraphs = [str(item).strip() for item in paragraphs if str(item).strip()]
        if not paragraphs:
            paragraphs = [
                "ich wollte dich kurz auf Certiq aufmerksam machen.",
                "Wir helfen Industriebetrieben dabei, komplexe Anforderungen schneller und klarer zu validieren.",
            ]
        cta_label = str(content.get("ctaLabel", "Mehr erfahren")).strip() or "Mehr erfahren"
        signature = str(content.get("signature", "Viele Gruesse\nCertiq Team")).strip() or "Viele Gruesse\nCertiq Team"
        addressing = str(content.get("addressing", "du")).strip().lower() or "du"
        lead_ids = payload.get("leadIds") if isinstance(payload.get("leadIds"), list) else []
        lead_ids = [str(item).strip() for item in lead_ids if str(item).strip()]
        campaign_name = utm["utm_campaign"]

        try:
            result = send_campaign_batch(
                lead_ids=lead_ids,
                dry_run=dry_run,
                subject=subject,
                paragraphs=paragraphs,
                cta_label=cta_label,
                signature=signature,
                utm=utm,
                campaign_name=campaign_name,
                addressing=addressing,
            )
            json_response(self, 200, {"status": "ok", **result})
        except Exception as err:  # noqa: BLE001
            json_response(self, 500, {"status": "error", "message": str(err)})
