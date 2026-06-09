import html
import os
import urllib.parse
from datetime import datetime, timezone
from typing import Any

import resend

from lib.campaign_store import record_campaign_event
from lib.resend_campaign_sync import resend_send_key
from lib.twenty_crm import find_person_by_id_or_email, get_person, mark_person_last_contacted, people_for_campaign
from lib.unsubscribe import build_unsubscribe_url


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _base_url() -> str:
    return os.getenv("APP_BASE_URL", "https://certiq.tech").strip().rstrip("/")


def _compose_tracking_link(recipient: dict[str, Any], utm: dict[str, str]) -> str:
    params = {
        "user_id": recipient.get("person_id") or recipient.get("kunden_id", ""),
        "utm_source": utm.get("utm_source", "newsletter"),
        "utm_medium": utm.get("utm_medium", "email"),
        "utm_campaign": utm.get("utm_campaign", "certiq_campaign"),
    }
    company = (recipient.get("company") or "").strip()
    if company:
        params["company"] = company
    return f"{_base_url()}/?{urllib.parse.urlencode(params)}"


def _greeting(first_name: str, addressing: str) -> str:
    name = first_name or "there"
    if addressing.lower() == "sie":
        return f"Guten Tag{' ' + name if name != 'there' else ''},"
    return f"Hallo {name},"


def _format_signature_html(signature: str) -> str:
    return html.escape(signature).replace("\n", "<br>")


def _render_email_plain_text(
    intro: str,
    paragraphs: list[str],
    cta_label: str,
    tracking_link: str,
    signature: str,
) -> str:
    text_parts = [intro, ""]
    text_parts.extend(paragraphs)
    text_parts.append("")
    text_parts.append(f"{cta_label}: {tracking_link}")
    text_parts.append("")
    text_parts.append(signature)
    return "\n".join(text_parts)


def _render_email_body_html(
    recipient: dict[str, Any],
    tracking_link: str,
    paragraphs: list[str],
    cta_label: str,
    signature: str,
    addressing: str = "du",
    *,
    for_preview: bool = False,
    subject: str = "",
) -> str:
    """Certiq-branded email body (inline styles for mail clients)."""
    first_name = recipient.get("first_name") or recipient.get("firstName") or "there"
    intro = html.escape(_greeting(first_name, addressing))
    safe_cta = html.escape(cta_label)
    safe_link = html.escape(tracking_link, quote=True)
    logo_url = html.escape(f"{_base_url()}/brand/certiq-lockup-horizontal.png", quote=True)
    html_paragraphs = "".join(
        f"<p style=\"margin:0 0 14px;line-height:1.65;color:#0A0C0E;font-size:15px;font-family:Inter,Arial,Helvetica,sans-serif;\">{html.escape(text)}</p>"
        for text in paragraphs
    )
    preview_header = ""
    if for_preview:
        preview_header = (
            f"<p style=\"margin:0 0 16px;padding-bottom:12px;border-bottom:1px solid #e3ebe8;font-size:13px;"
            f"color:#5a6b75;font-family:Inter,Arial,Helvetica,sans-serif;\">"
            f"<strong style=\"display:block;color:#0A0C0E;font-size:15px;margin-bottom:4px;\">{html.escape(subject)}</strong>"
            f"An: {html.escape(first_name or 'Lead')}</p>"
        )
    return f"""
    <div style="margin:0;padding:0;background:#EEF3F1;font-family:Inter,Arial,Helvetica,sans-serif;">
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#EEF3F1;padding:24px 12px;">
        <tr>
          <td align="center">
            <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:620px;background:#FFFFFF;border:1px solid #D5E5DF;border-radius:14px;overflow:hidden;">
              <tr>
                <td style="background:#0A0C0E;padding:18px 24px;">
                  <img src="{logo_url}" alt="Certiq" width="148" height="32" style="display:block;border:0;max-width:148px;height:auto;" />
                </td>
              </tr>
              <tr>
                <td style="padding:24px;">
                  {preview_header}
                  <p style="margin:0 0 14px;line-height:1.6;color:#0A0C0E;font-size:15px;font-family:Inter,Arial,Helvetica,sans-serif;">{intro}</p>
                  {html_paragraphs}
                  <p style="margin:20px 0 18px;">
                    <a href="{safe_link}" style="display:inline-block;padding:12px 18px;border-radius:10px;background:#3DFFD0;color:#042019;text-decoration:none;font-weight:700;font-size:14px;font-family:Inter,Arial,Helvetica,sans-serif;">{safe_cta}</a>
                  </p>
                  <p style="margin:0;color:#5a6b75;font-size:13px;line-height:1.6;font-family:Inter,Arial,Helvetica,sans-serif;">{_format_signature_html(signature)}</p>
                </td>
              </tr>
              <tr>
                <td style="padding:14px 24px;background:#F6FAF8;border-top:1px solid #E3EBE8;font-size:11px;line-height:1.5;color:#7A8F96;font-family:Inter,Arial,Helvetica,sans-serif;">
                  Certiq · <a href="{html.escape(_base_url(), quote=True)}" style="color:#0A0C0E;text-decoration:underline;">certiq.tech</a>
                </td>
              </tr>
            </table>
          </td>
        </tr>
      </table>
    </div>
    """


def _wrap_preview_document(body_html: str) -> str:
    return (
        "<!DOCTYPE html><html><head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "<base target=\"_blank\">"
        "</head><body style=\"margin:0;padding:0;background:#EEF3F1;\">"
        f"{body_html}"
        "</body></html>"
    )


def _wrap_send_document(body_html: str) -> str:
    return (
        "<!DOCTYPE html><html><head>"
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        "</head><body style=\"margin:0;padding:0;background:#EEF3F1;\">"
        f"{body_html}"
        "</body></html>"
    )


def _render_email_content(
    recipient: dict[str, Any],
    tracking_link: str,
    subject: str,
    paragraphs: list[str],
    cta_label: str,
    signature: str,
    addressing: str = "du",
    *,
    for_preview: bool = False,
) -> tuple[str, str]:
    first_name = recipient.get("first_name") or recipient.get("firstName") or "there"
    intro = _greeting(first_name, addressing)
    body_html = _render_email_body_html(
        recipient=recipient,
        tracking_link=tracking_link,
        paragraphs=paragraphs,
        cta_label=cta_label,
        signature=signature,
        addressing=addressing,
        for_preview=for_preview,
        subject=subject,
    )
    wrapper = _wrap_preview_document if for_preview else _wrap_send_document
    text = _render_email_plain_text(intro, paragraphs, cta_label, tracking_link, signature)
    return wrapper(body_html), text


def _person_to_lead(person: dict[str, Any], utm: dict[str, str]) -> dict[str, Any]:
    email = (person.get("email") or "").strip().lower()
    tracking_link = _compose_tracking_link(person, utm)
    return {
        "id": person.get("person_id", ""),
        "pageId": person.get("person_id", ""),
        "firstName": person.get("first_name", ""),
        "lastName": person.get("last_name", ""),
        "company": person.get("company", ""),
        "email": email,
        "status": person.get("email_state", "new"),
        "emailState": person.get("email_state", "new"),
        "sequence": "",
        "sequenceStep": 0,
        "nextSendAt": "",
        "openCount": 0,
        "clickCount": 0,
        "lastContactedAt": person.get("last_contacted_at", ""),
        "lastContactCampaign": person.get("last_contact_campaign", ""),
        "sentCampaigns": person.get("sent_campaigns") or [],
        "kundenId": person.get("kunden_id", ""),
        "sendable": bool(person.get("sendable")),
        "blockedReason": person.get("blocked_reason"),
        "unsubscribed": bool(person.get("unsubscribed")),
        "trackingLink": tracking_link,
    }


def load_campaign_recipients(utm: dict[str, str] | None = None) -> dict[str, Any]:
    normalized_utm = {
        "utm_source": (utm or {}).get("utm_source", "newsletter"),
        "utm_medium": (utm or {}).get("utm_medium", "email"),
        "utm_campaign": (utm or {}).get("utm_campaign", "certiq_campaign"),
    }
    people = people_for_campaign()
    leads = [_person_to_lead(person, normalized_utm) for person in people]
    sendable_count = len([lead for lead in leads if lead.get("sendable")])
    bounced_count = len(
        [lead for lead in leads if (lead.get("blockedReason") or lead.get("emailState")) == "bounced"]
    )
    unsubscribed_count = len(
        [
            lead
            for lead in leads
            if (lead.get("blockedReason") or lead.get("emailState"))
            in {"unsubscribed", "supabase_unsubscribed"}
        ]
    )
    resend_key = resend_send_key()
    twenty_ok = bool(os.getenv("TWENTY_API_URL", "").strip() and os.getenv("TWENTY_CRM_API_KEY", "").strip())
    return {
        "meta": {
            "total": len(leads),
            "sendable": sendable_count,
            "blocked": len(leads) - sendable_count,
            "bounced": bounced_count,
            "unsubscribed": unsubscribed_count,
            "source": "twenty",
            "campaign": normalized_utm["utm_campaign"],
            "resendConfigured": bool(resend_key),
            "resendFrom": os.getenv("RESEND_FROM", "Certiq <hello@certiq.tech>").strip(),
            "twentyConfigured": twenty_ok,
            "targetUrl": _base_url(),
        },
        "leads": leads,
    }


def preview_campaign_email(
    lead_id: str,
    subject: str,
    paragraphs: list[str],
    cta_label: str,
    signature: str,
    utm: dict[str, str],
    addressing: str = "du",
) -> dict[str, Any]:
    person = get_person(lead_id) or find_person_by_id_or_email(person_id=lead_id)
    if not person:
        raise RuntimeError("Lead not found")

    lead = _person_to_lead(person, utm)
    recipient_like = {
        "first_name": lead["firstName"],
        "company": lead["company"],
        "person_id": lead["id"],
    }
    html_body, text = _render_email_content(
        recipient=recipient_like,
        tracking_link=lead["trackingLink"],
        subject=subject,
        paragraphs=paragraphs,
        cta_label=cta_label,
        signature=signature,
        addressing=addressing,
        for_preview=True,
    )
    return {
        "subject": subject,
        "html": html_body,
        "text": text,
        "trackingLink": lead["trackingLink"],
        "unsubscribeUrl": build_unsubscribe_url(lead["email"], locale="de"),
        "recipientName": f"{lead['firstName']} {lead['lastName']}".strip(),
    }


def send_campaign_batch(
    lead_ids: list[str],
    dry_run: bool,
    subject: str,
    paragraphs: list[str],
    cta_label: str,
    signature: str,
    utm: dict[str, str],
    campaign_name: str,
    addressing: str = "du",
) -> dict[str, Any]:
    payload = load_campaign_recipients(utm=utm)
    leads = payload["leads"]
    selected_ids = set(lead_ids or [])
    selected = [lead for lead in leads if lead["id"] in selected_ids] if selected_ids else []
    if not selected:
        return {"sent": 0, "dryRun": dry_run, "results": []}

    resend_key = resend_send_key()
    resend_from = os.getenv("RESEND_FROM", "Certiq <hello@certiq.tech>").strip()
    if not dry_run and not resend_key:
        raise RuntimeError("Missing RESEND_EMAIL_API_KEY or RESEND_API_KEY")
    if resend_key:
        resend.api_key = resend_key

    results: list[dict[str, Any]] = []
    for lead in selected:
        if not lead.get("sendable"):
            reason = lead.get("blockedReason") or "blocked"
            status = "skipped_unsubscribed" if reason in {"unsubscribed", "supabase_unsubscribed"} else f"skipped_{reason}"
            results.append({"id": lead["id"], "email": lead["email"], "status": status, "reason": reason})
            continue

        recipient_like = {
            "first_name": lead["firstName"],
            "company": lead["company"],
            "person_id": lead["id"],
        }
        html, text = _render_email_content(
            recipient=recipient_like,
            tracking_link=lead["trackingLink"],
            subject=subject,
            paragraphs=paragraphs,
            cta_label=cta_label,
            signature=signature,
            addressing=addressing,
            for_preview=False,
        )
        unsubscribe_url = build_unsubscribe_url(lead["email"], locale="de")

        if dry_run:
            record_campaign_event(
                event_type="email_dry_run",
                kunden_id=lead["id"],
                email=lead["email"],
                campaign=campaign_name,
                utm=utm,
                metadata={"subject": subject},
            )
            results.append({"id": lead["id"], "email": lead["email"], "status": "dry_run"})
            continue

        try:
            resend.Emails.send(
                {
                    "from": resend_from,
                    "to": [lead["email"]],
                    "subject": subject,
                    "html": html,
                    "text": text,
                    "headers": {
                        "List-Unsubscribe": f"<{unsubscribe_url}>",
                        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                    },
                    "tags": [
                        {"name": "user_id", "value": lead["id"]},
                        {"name": "kunden_id", "value": lead.get("kundenId") or lead["id"]},
                        {"name": "utm_campaign", "value": utm.get("utm_campaign", campaign_name)},
                    ],
                }
            )
            record_campaign_event(
                event_type="email_sent",
                kunden_id=lead["id"],
                email=lead["email"],
                campaign=campaign_name,
                utm=utm,
                metadata={"subject": subject},
            )
            mark_person_last_contacted(
                lead["id"],
                contacted_at=_now_iso(),
                campaign=campaign_name,
                email_state="working",
            )
            results.append({"id": lead["id"], "email": lead["email"], "status": "sent"})
        except Exception as err:  # noqa: BLE001
            results.append({"id": lead["id"], "email": lead["email"], "status": "error", "message": str(err)})

    return {
        "sent": len([item for item in results if item["status"] == "sent"]),
        "dryRun": dry_run,
        "results": results,
    }


def send_campaign_test_email(
    to_email: str,
    subject: str,
    paragraphs: list[str],
    cta_label: str,
    signature: str,
    utm: dict[str, str],
    addressing: str = "du",
) -> None:
    resend_key = resend_send_key()
    resend_from = os.getenv("RESEND_FROM", "Certiq <hello@certiq.tech>").strip()
    if not resend_key:
        raise RuntimeError("Missing RESEND_EMAIL_API_KEY or RESEND_API_KEY")
    resend.api_key = resend_key
    tracking_link = f"{_base_url()}/?{urllib.parse.urlencode(utm)}"
    html, text = _render_email_content(
        recipient={"first_name": "Test"},
        tracking_link=tracking_link,
        subject=subject,
        paragraphs=paragraphs,
        cta_label=cta_label,
        signature=signature,
        addressing=addressing,
        for_preview=False,
    )
    resend.Emails.send(
        {
            "from": resend_from,
            "to": [to_email],
            "subject": f"[TEST] {subject}",
            "html": html,
            "text": text,
        }
    )
    record_campaign_event(
        event_type="email_test",
        email=to_email,
        campaign=utm.get("utm_campaign", "certiq_campaign"),
        utm=utm,
        metadata={"subject": subject},
    )
