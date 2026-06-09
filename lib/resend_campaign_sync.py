import json
import os
import urllib.error
import urllib.request
from typing import Any

from lib.campaign_store import record_campaign_event


EVENT_MAPPING = {
    "delivered": "resend.delivered",
    "opened": "resend.opened",
    "clicked": "resend.clicked",
    "bounced": "resend.bounced",
    "complained": "resend.complained",
}


def resend_send_key() -> str:
    return (os.getenv("RESEND_EMAIL_API_KEY") or os.getenv("RESEND_API_KEY") or "").strip()


def _resend_read_key() -> str:
    return (
        resend_send_key()
        or os.getenv("RESEND_API_KEY_READ")
        or os.getenv("RESEND_CONTACTS_API_KEY")
        or ""
    ).strip()


def sync_resend_to_campaign_store(limit: int = 100) -> dict[str, Any]:
    api_key = _resend_read_key()
    if not api_key:
        return {
            "synced": 0,
            "skipped": 0,
            "message": "Missing RESEND_EMAIL_API_KEY, RESEND_API_KEY_READ, or RESEND_CONTACTS_API_KEY",
        }

    safe_limit = max(1, min(limit, 500))
    url = f"https://api.resend.com/emails?limit={safe_limit}"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        return {"synced": 0, "skipped": 0, "message": f"Resend request failed ({err.code}): {body}"}
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        return {"synced": 0, "skipped": 0, "message": f"Resend request failed: {err!s}"}

    records = payload.get("data") if isinstance(payload, dict) else []
    if not isinstance(records, list):
        records = []

    synced = 0
    skipped = 0
    for record in records:
        last_event = str(record.get("last_event") or "").strip().lower()
        mapped_event = EVENT_MAPPING.get(last_event)
        if not mapped_event:
            skipped += 1
            continue

        tags = record.get("tags") if isinstance(record.get("tags"), list) else []
        tag_map = {}
        for tag in tags:
            key = str((tag or {}).get("name") or "").strip()
            value = str((tag or {}).get("value") or "").strip()
            if key:
                tag_map[key] = value

        ok, _ = record_campaign_event(
            event_type=mapped_event,
            kunden_id=tag_map.get("kunden_id", ""),
            email=str(record.get("to") or "").strip().lower(),
            campaign=tag_map.get("utm_campaign", ""),
            utm={
                "utm_source": tag_map.get("utm_source", ""),
                "utm_medium": tag_map.get("utm_medium", ""),
                "utm_campaign": tag_map.get("utm_campaign", ""),
            },
            metadata={"resendId": record.get("id"), "lastEvent": last_event},
            created_at=str(record.get("last_event_at") or ""),
        )
        if ok:
            synced += 1
        else:
            skipped += 1

    return {"synced": synced, "skipped": skipped, "fetched": len(records)}
