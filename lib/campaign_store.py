import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from lib.utm_filter import UtmFilter, filter_to_dict, matches_store_row


EVENT_TYPES = {
    "email_sent",
    "email_test",
    "email_dry_run",
    "resend.delivered",
    "resend.opened",
    "resend.clicked",
    "resend.bounced",
    "resend.complained",
    "unsubscribe",
}


def _supabase_url() -> str:
    return (
        os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or ""
    ).strip()


def _is_supabase_ready() -> bool:
    supabase_url = _supabase_url()
    service_role = (os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
    if not supabase_url or "dein-projekt" in supabase_url:
        return False
    if not service_role or service_role.startswith("dein_"):
        return False
    return True


def _supabase_request(
    method: str,
    path: str,
    payload: Any | None = None,
    query: dict[str, str] | None = None,
    prefer: str | None = None,
) -> tuple[int, Any]:
    if not _is_supabase_ready():
        return 503, {"message": "Supabase is not configured"}

    supabase_url = _supabase_url().rstrip("/")
    service_role = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    url = f"{supabase_url}/rest/v1/{path}"
    if query:
        url += f"?{urllib.parse.urlencode(query)}"

    headers = {
        "apikey": service_role,
        "Authorization": f"Bearer {service_role}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer

    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as err:
        raw = err.read().decode("utf-8", errors="replace")
        try:
            body = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = {"message": raw}
        return err.code, body
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        return 503, {"message": f"Supabase request failed: {err!s}"}


def _parse_iso(value: str) -> datetime:
    normalized = (value or "").replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def record_campaign_event(
    event_type: str,
    kunden_id: str = "",
    email: str = "",
    campaign: str = "",
    channel: str = "email",
    utm: dict[str, str] | None = None,
    metadata: dict[str, Any] | None = None,
    created_at: str | None = None,
) -> tuple[bool, str]:
    event_name = (event_type or "").strip()
    if event_name not in EVENT_TYPES:
        return False, f"Unsupported event type: {event_name}"

    utm_payload = utm or {}
    payload = [
        {
            "event_type": event_name,
            "kunden_id": (kunden_id or "").strip() or None,
            "email": (email or "").strip().lower() or None,
            "campaign": (campaign or "").strip() or None,
            "channel": (channel or "email").strip(),
            "utm_source": (utm_payload.get("utm_source") or "").strip() or None,
            "utm_medium": (utm_payload.get("utm_medium") or "").strip() or None,
            "utm_campaign": (utm_payload.get("utm_campaign") or "").strip() or None,
            "metadata": metadata or {},
            "created_at": created_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
    ]
    status, body = _supabase_request("POST", "campaign_events", payload=payload, prefer="return=minimal")
    if status in (200, 201, 204):
        return True, "ok"
    return False, f"Failed to record campaign event ({status}): {body}"


def upsert_unsubscribe(
    email: str,
    kunden_id: str = "",
    status: str = "unsubscribed",
    source: str = "manual",
    reason: str = "",
    metadata: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        return False, "Missing email"
    payload = [
        {
            "email": normalized_email,
            "kunden_id": (kunden_id or "").strip() or None,
            "status": (status or "unsubscribed").strip(),
            "source": (source or "manual").strip(),
            "reason": (reason or "").strip() or None,
            "metadata": metadata or {},
            "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        }
    ]
    status_code, body = _supabase_request(
        "POST",
        "campaign_unsubscribes",
        payload=payload,
        query={"on_conflict": "email"},
        prefer="resolution=merge-duplicates,return=minimal",
    )
    if status_code in (200, 201, 204):
        return True, "ok"
    return False, f"Failed to upsert unsubscribe ({status_code}): {body}"


def get_unsubscribed_emails() -> set[str]:
    status, body = _supabase_request(
        "GET",
        "campaign_unsubscribes",
        query={"select": "email,status", "status": "neq.active", "limit": "10000"},
    )
    if status != 200 or not isinstance(body, list):
        return set()
    result: set[str] = set()
    for item in body:
        email = str(item.get("email") or "").strip().lower()
        if email:
            result.add(email)
    return result


def last_contact_index() -> dict[str, str]:
    status, body = _supabase_request(
        "GET",
        "campaign_events",
        query={
            "select": "kunden_id,email,created_at,event_type",
            "event_type": "eq.email_sent",
            "order": "created_at.desc",
            "limit": "5000",
        },
    )
    if status != 200 or not isinstance(body, list):
        return {}
    latest: dict[str, str] = {}
    for row in body:
        kunden_id = str(row.get("kunden_id") or "").strip()
        if not kunden_id:
            continue
        if kunden_id not in latest:
            latest[kunden_id] = str(row.get("created_at") or "")
    return latest


def list_recent_events(limit: int = 200) -> list[dict[str, Any]]:
    safe_limit = max(1, min(limit, 1000))
    status, body = _supabase_request(
        "GET",
        "campaign_events",
        query={"select": "*", "order": "created_at.desc", "limit": str(safe_limit)},
    )
    if status != 200 or not isinstance(body, list):
        return []
    return body


def list_events_for_sync(limit: int = 5000) -> list[dict[str, Any]]:
    safe_limit = max(1, min(limit, 10000))
    status, body = _supabase_request(
        "GET",
        "campaign_events",
        query={"select": "*", "order": "created_at.desc", "limit": str(safe_limit)},
    )
    if status != 200 or not isinstance(body, list):
        return []
    return body


def aggregate_campaign_summary(utm_filter: UtmFilter | None = None) -> dict[str, Any]:
    rows = list_events_for_sync(limit=6000)
    if utm_filter and utm_filter.is_active():
        rows = [row for row in rows if matches_store_row(row, utm_filter)]

    counts: dict[str, int] = defaultdict(int)
    per_lead: dict[str, dict[str, Any]] = {}
    for row in rows:
        event_type = str(row.get("event_type") or "")
        counts[event_type] += 1
        kunden_id = str(row.get("kunden_id") or "").strip()
        if not kunden_id:
            continue
        lead_entry = per_lead.setdefault(
            kunden_id,
            {
                "kunden_id": kunden_id,
                "email": str(row.get("email") or ""),
                "lastEventAt": "",
                "events": defaultdict(int),
            },
        )
        lead_entry["events"][event_type] += 1
        created_at = str(row.get("created_at") or "")
        if created_at and (
            not lead_entry["lastEventAt"] or _parse_iso(created_at) > _parse_iso(lead_entry["lastEventAt"])
        ):
            lead_entry["lastEventAt"] = created_at

    leads: list[dict[str, Any]] = []
    for lead_entry in per_lead.values():
        events = dict(lead_entry["events"])
        opens = int(events.get("resend.opened", 0))
        clicks = int(events.get("resend.clicked", 0))
        sent = int(events.get("email_sent", 0))
        bounced = int(events.get("resend.bounced", 0))
        complained = int(events.get("resend.complained", 0))
        unsubscribed = int(events.get("unsubscribe", 0))
        score = (clicks * 3) + (opens * 1) - (bounced * 4) - (complained * 5) - (unsubscribed * 5)
        segment = "not_sent"
        if complained:
            segment = "complained"
        elif unsubscribed:
            segment = "unsubscribed"
        elif bounced:
            segment = "bounced"
        elif sent <= 0:
            segment = "not_sent"
        elif score >= 6:
            segment = "hot"
        elif score >= 3:
            segment = "warm"
        elif score >= 1:
            segment = "mild"
        else:
            segment = "cold"

        leads.append(
            {
                "kunden_id": lead_entry["kunden_id"],
                "email": lead_entry["email"],
                "lastEventAt": lead_entry["lastEventAt"],
                "segment": segment,
                "score": score,
                "events": events,
            }
        )

    segment_counts: dict[str, int] = defaultdict(int)
    for lead in leads:
        segment_counts[lead["segment"]] += 1

    return {
        "filters": filter_to_dict(utm_filter),
        "totals": dict(counts),
        "segments": dict(segment_counts),
        "leads": sorted(leads, key=lambda entry: entry["score"], reverse=True),
    }


def recommendation_for_segment(segment: str) -> str:
    mapping = {
        "hot": "Mehrfach geklickt oder starke Signale — persoenlich anrufen oder individuelles Follow-up.",
        "warm": "Geoeffnet oder leichte Interaktion — kurzes, konkretes Follow-up per E-Mail.",
        "mild": "Schwaches Signal — erst spaeter erneut kontaktieren.",
        "cold": "Kein Engagement — nicht erneut mailen.",
        "not_sent": "Noch nicht kontaktiert — fuer Erstversand geeignet.",
        "bounced": "Adresse unzustellbar — nicht erneut senden.",
        "unsubscribed": "Abgemeldet — kein weiterer Versand.",
        "complained": "Spam-Beschwerde — sofort stoppen.",
    }
    return mapping.get(segment, "Status pruefen.")
