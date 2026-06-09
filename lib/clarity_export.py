"""Microsoft Clarity Data Export API — GET project-live-insights."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

CLARITY_EXPORT_URL = "https://www.clarity.ms/export-data/api/v1/project-live-insights"
DEFAULT_TIMEOUT = 30


def fetch_live_insights(
    api_token: str,
    *,
    num_of_days: int = 3,
    dimensions: list[str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Any:
    """Call Clarity Data Export API (GET, Bearer token scoped to project)."""
    safe_days = max(1, min(int(num_of_days), 3))
    params: dict[str, str] = {"numOfDays": str(safe_days)}
    for index, dimension in enumerate((dimensions or [])[:3], start=1):
        params[f"dimension{index}"] = dimension

    query = urllib.parse.urlencode(params)
    req = urllib.request.Request(
        f"{CLARITY_EXPORT_URL}?{query}",
        headers={
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Clarity API failed ({err.code}): {body}") from err
    except TimeoutError as err:
        raise RuntimeError("Clarity API timeout — bitte später erneut versuchen.") from err
