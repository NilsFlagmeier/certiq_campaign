"""Google Search Console metrics for admin dashboard."""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import date, timedelta
from typing import Any


def _bearer_token() -> str:
    direct = os.getenv("GSC_ACCESS_TOKEN", "").strip()
    if direct:
        return direct
    info_raw = os.getenv("GSC_SERVICE_ACCOUNT_JSON", "").strip()
    path = os.getenv("GSC_SERVICE_ACCOUNT_PATH", "").strip()
    info: dict[str, Any] | None = None
    if info_raw:
        try:
            info = json.loads(info_raw)
        except json.JSONDecodeError:
            return ""
    elif path and os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            info = json.load(fh)
    if not info:
        return ""
    try:
        from google.oauth2 import service_account  # type: ignore
        import google.auth.transport.requests  # type: ignore

        creds = service_account.Credentials.from_service_account_info(
            info, scopes=["https://www.googleapis.com/auth/webmasters.readonly"]
        )
        creds.refresh(google.auth.transport.requests.Request())
        return str(creds.token or "")
    except ImportError:
        return ""
    except Exception:
        return ""


def _search_analytics(token: str, site_url: str, start: str, end: str, dimensions: list[str]) -> list[dict[str, Any]]:
    payload = {
        "startDate": start,
        "endDate": end,
        "dimensions": dimensions,
        "rowLimit": 10,
    }
    encoded_site = urllib.parse.quote(site_url, safe="")
    req = urllib.request.Request(
        f"https://www.googleapis.com/webmasters/v3/sites/{encoded_site}/searchAnalytics/query",
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=25) as response:
        body = json.loads(response.read().decode("utf-8"))
    rows: list[dict[str, Any]] = []
    for row in body.get("rows", []):
        keys = row.get("keys") or []
        rows.append(
            {
                "key": keys[0] if keys else "",
                "clicks": row.get("clicks", 0),
                "impressions": row.get("impressions", 0),
                "ctr": round(float(row.get("ctr") or 0) * 100, 2),
                "position": round(float(row.get("position") or 0), 1),
            }
        )
    return rows


def fetch_gsc_summary() -> dict[str, Any]:
    site_url = os.getenv("GSC_SITE_URL", "").strip()
    token = _bearer_token()
    if not site_url or not token:
        return {
            "configured": False,
            "message": "Set GSC_SITE_URL and GSC_ACCESS_TOKEN (or install google-auth + GSC_SERVICE_ACCOUNT_JSON)",
        }

    try:
        end = date.today() - timedelta(days=2)
        start = end - timedelta(days=7)
        start_s, end_s = start.isoformat(), end.isoformat()
        totals = _search_analytics(token, site_url, start_s, end_s, [])
        top_queries = _search_analytics(token, site_url, start_s, end_s, ["query"])
        top_pages = _search_analytics(token, site_url, start_s, end_s, ["page"])
        total_row = totals[0] if totals else {}
        return {
            "configured": True,
            "siteUrl": site_url,
            "period": {"start": start_s, "end": end_s},
            "clicks": int(total_row.get("clicks") or 0),
            "impressions": int(total_row.get("impressions") or 0),
            "ctr": total_row.get("ctr", 0),
            "position": total_row.get("position", 0),
            "topQueries": top_queries,
            "topPages": top_pages,
        }
    except Exception as err:  # noqa: BLE001
        return {"configured": False, "message": str(err)}
