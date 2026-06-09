import json
import os
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

from lib.admin_api import json_response, require_admin_auth

PAGESPEED_TIMEOUT = 60


def _fetch_pagespeed(strategy: str, target_url: str, api_key: str) -> dict:
    query = urllib.parse.urlencode(
        {
            "url": target_url,
            "key": api_key,
            "strategy": strategy,
            "category": "performance",
        }
    )
    req = urllib.request.Request(
        f"https://www.googleapis.com/pagespeedonline/v5/runPagespeed?{query}",
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=PAGESPEED_TIMEOUT) as response:
        payload = json.loads(response.read().decode("utf-8", errors="replace"))
    lighthouse = payload.get("lighthouseResult") or {}
    categories = lighthouse.get("categories") or {}
    perf = categories.get("performance") or {}
    score = perf.get("score")
    score_percent = int(round(float(score or 0) * 100))
    return {
        "strategy": strategy,
        "score": score_percent,
        "fcp": ((lighthouse.get("audits") or {}).get("first-contentful-paint") or {}).get("displayValue"),
        "lcp": ((lighthouse.get("audits") or {}).get("largest-contentful-paint") or {}).get("displayValue"),
        "tbt": ((lighthouse.get("audits") or {}).get("total-blocking-time") or {}).get("displayValue"),
        "cls": ((lighthouse.get("audits") or {}).get("cumulative-layout-shift") or {}).get("displayValue"),
    }


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        load_dotenv()
        if not require_admin_auth(self):
            return

        api_key = os.getenv("GOOGLE_PAGESPEED_API_KEY", "").strip()
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        query_url = str((query.get("url", [""])[0] or "")).strip()
        target_url = query_url or os.getenv(
            "ADMIN_METRICS_SITE_URL", os.getenv("APP_BASE_URL", "https://certiq.tech")
        ).strip()
        if not api_key:
            json_response(self, 200, {"status": "ok", "configured": False, "message": "Missing GOOGLE_PAGESPEED_API_KEY"})
            return

        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                mobile_future = pool.submit(_fetch_pagespeed, "mobile", target_url, api_key)
                desktop_future = pool.submit(_fetch_pagespeed, "desktop", target_url, api_key)
                mobile = mobile_future.result()
                desktop = desktop_future.result()
            json_response(
                self,
                200,
                {
                    "status": "ok",
                    "configured": True,
                    "targetUrl": target_url,
                    "mobile": mobile,
                    "desktop": desktop,
                },
            )
        except urllib.error.HTTPError as err:
            body = err.read().decode("utf-8", errors="replace")
            json_response(self, 502, {"status": "error", "message": f"PageSpeed API failed ({err.code}): {body}"})
        except TimeoutError:
            json_response(
                self,
                504,
                {
                    "status": "error",
                    "message": "PageSpeed API Timeout — Google braucht gerade länger. Bitte erneut versuchen.",
                },
            )
        except Exception as err:  # noqa: BLE001
            message = str(err)
            if "timed out" in message.lower():
                message = "PageSpeed API Timeout — bitte „Aktualisieren“ in 30 Sekunden erneut klicken."
            json_response(self, 500, {"status": "error", "message": message})
