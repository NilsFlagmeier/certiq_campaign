"""Clarity export signals for campaign analytics."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from lib.clarity_export import fetch_live_insights
from lib.utm_filter import UtmFilter, matches_url_query

SMC_FILTER_FIELDS = ("utm_source", "utm_medium", "utm_campaign")


def row_session_estimate(row: dict[str, Any]) -> int:
    raw = (
        row.get("DistinctSessions")
        or row.get("totalSessionCount")
        or row.get("distantUserCount")
        or row.get("sessions")
        or "0"
    )
    try:
        return int(float(str(raw).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def _extract_insight_rows(data: Any) -> list[dict[str, Any]]:
    rows = data if isinstance(data, list) else (data.get("data") if isinstance(data, dict) else [])
    if not isinstance(rows, list):
        return []
    entries: list[dict[str, Any]] = []
    for block in rows:
        if not isinstance(block, dict):
            continue
        values = block.get("information") or block.get("data") or []
        if not isinstance(values, list):
            continue
        for entry in values:
            if isinstance(entry, dict):
                entries.append(entry)
    return entries


def _matches_smc_row(entry: dict[str, Any], utm_filter: UtmFilter | None) -> bool:
    if utm_filter is None or not utm_filter.is_active():
        return True
    active = utm_filter.active_fields()
    row = {
        "utm_source": str(entry.get("Source") or entry.get("source") or "").strip(),
        "utm_medium": str(entry.get("Medium") or entry.get("medium") or "").strip(),
        "utm_campaign": str(entry.get("Campaign") or entry.get("campaign") or "").strip(),
    }
    for name in SMC_FILTER_FIELDS:
        expected = active.get(name)
        if not expected:
            continue
        if row.get(name) != expected:
            return False
    return True


def _aggregate_smc_rows(rows: list[dict[str, Any]], utm_filter: UtmFilter | None) -> dict[str, Any]:
    total_sessions = 0
    for entry in rows:
        if not _matches_smc_row(entry, utm_filter):
            continue
        total_sessions += row_session_estimate(entry)
    return {"sessions": total_sessions}


def _aggregate_url_rows(rows: list[dict[str, Any]], utm_filter: UtmFilter | None) -> dict[str, Any]:
    by_user: dict[str, dict[str, Any]] = {}
    total_sessions = 0
    for entry in rows:
        raw_url = str(entry.get("URL") or entry.get("Url") or entry.get("url") or "").strip()
        if not raw_url:
            continue
        if not matches_url_query(raw_url, utm_filter):
            continue
        sessions = row_session_estimate(entry)
        total_sessions += sessions
        parsed = _user_id_from_url(raw_url)
        if parsed:
            slot = by_user.setdefault(parsed, {"sessions": 0, "pages": 0})
            slot["sessions"] += sessions
    return {"sessions": total_sessions, "byUserId": by_user}


def _user_id_from_url(url: str) -> str:
    from lib.utm_filter import parse_tracking_url

    return parse_tracking_url(url).user_id


def fetch_clarity_campaign_signals(utm_filter: UtmFilter | None = None) -> dict[str, Any]:
    api_token = os.getenv("CLARITY_TOKEN", "").strip()
    if not api_token:
        return {
            "configured": False,
            "fetched": False,
            "apiCalls": 0,
            "byUserId": {},
            "totals": {},
        }

    errors: list[str] = []
    smc_totals = {"sessions": 0}
    url_totals = {"sessions": 0}
    by_user: dict[str, dict[str, Any]] = {}
    api_calls = 0

    try:
        smc_data = fetch_live_insights(
            api_token,
            num_of_days=3,
            dimensions=["Source", "Medium", "Campaign"],
        )
        api_calls += 1
        smc_totals = _aggregate_smc_rows(_extract_insight_rows(smc_data), utm_filter)
    except Exception as err:  # noqa: BLE001
        errors.append(f"SMC: {err}")

    try:
        url_data = fetch_live_insights(
            api_token,
            num_of_days=3,
            dimensions=["URL"],
        )
        api_calls += 1
        url_result = _aggregate_url_rows(_extract_insight_rows(url_data), utm_filter)
        url_totals = {"sessions": url_result["sessions"]}
        by_user = url_result["byUserId"]
    except Exception as err:  # noqa: BLE001
        errors.append(f"URL: {err}")

    return {
        "configured": True,
        "fetched": True,
        "apiCalls": api_calls,
        "fetchedAt": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "filtered": bool(utm_filter and utm_filter.is_active()),
        "error": "; ".join(errors) if errors else "",
        "byUserId": by_user,
        "totals": {
            "smcSessions": smc_totals["sessions"],
            "urlSessions": url_totals["sessions"],
            "sessions": url_totals["sessions"] or smc_totals["sessions"],
        },
    }
