"""Clarity export signals for campaign analytics."""

from __future__ import annotations

import os
from typing import Any

from lib.clarity_export import fetch_live_insights


def fetch_clarity_campaign_signals(utm_campaign: str = "") -> dict[str, Any]:
    api_token = os.getenv("CLARITY_TOKEN", "").strip()
    if not api_token:
        return {"configured": False, "byUserId": {}, "totals": {}}

    try:
        data = fetch_live_insights(
            api_token,
            num_of_days=3,
            dimensions=["Source", "Medium", "Campaign"],
        )
    except Exception as err:  # noqa: BLE001
        return {"configured": False, "error": str(err), "byUserId": {}, "totals": {}}

    by_user: dict[str, dict[str, Any]] = {}
    total_sessions = 0
    rows = data if isinstance(data, list) else (data.get("data") if isinstance(data, dict) else [])
    if not isinstance(rows, list):
        rows = []

    for block in rows:
        name = str(block.get("metricName") or "").lower()
        values = block.get("information") or block.get("data") or []
        if not isinstance(values, list):
            continue
        for entry in values:
            campaign = str(entry.get("Campaign") or entry.get("campaign") or "").strip()
            if utm_campaign and campaign and campaign != utm_campaign:
                continue
            sessions = int(entry.get("totalSessionCount") or entry.get("sessions") or 0)
            total_sessions += sessions
            user_id = str(entry.get("user_id") or entry.get("UserId") or "").strip()
            if user_id:
                slot = by_user.setdefault(user_id, {"sessions": 0, "pages": 0})
                slot["sessions"] += sessions

    return {
        "configured": True,
        "byUserId": by_user,
        "totals": {"sessions": total_sessions, "utmCampaign": utm_campaign},
    }
