"""Fast integration status for the admin dashboard (no external API calls)."""

from __future__ import annotations

import os

from lib.campaign_ai_suggest import is_available as mistral_available
from lib.campaign_store import _is_supabase_ready
from lib.gsc_metrics import _bearer_token
from lib.resend_campaign_sync import resend_send_key


def integration_status() -> dict[str, dict[str, object]]:
    pagespeed_key = os.getenv("GOOGLE_PAGESPEED_API_KEY", "").strip()
    clarity_token = os.getenv("CLARITY_TOKEN", "").strip()
    clarity_project = os.getenv("CLARITY_PROJECT_ID", "").strip()  # optional — token is project-scoped
    gsc_site = os.getenv("GSC_SITE_URL", "").strip()
    gsc_token = bool(_bearer_token())
    twenty_url = os.getenv("TWENTY_API_URL", "").strip()
    twenty_key = os.getenv("TWENTY_CRM_API_KEY", "").strip() or os.getenv("TWENTY_API_KEY", "").strip()
    metrics_url = (
        os.getenv("ADMIN_METRICS_SITE_URL", "").strip()
        or os.getenv("APP_BASE_URL", "https://certiq.tech").strip()
    )

    return {
        "pagespeed": {
            "configured": bool(pagespeed_key),
            "label": "PageSpeed",
            "targetUrl": metrics_url,
        },
        "clarity": {
            "configured": bool(clarity_token),
            "label": "Clarity",
            "projectId": clarity_project or None,
        },
        "gsc": {
            "configured": bool(gsc_site and gsc_token),
            "label": "Search Console",
            "siteUrl": gsc_site or None,
        },
        "resend": {
            "configured": bool(resend_send_key()),
            "label": "Resend",
        },
        "supabase": {
            "configured": _is_supabase_ready(),
            "label": "Supabase",
        },
        "twenty": {
            "configured": bool(twenty_url and twenty_key),
            "label": "Twenty CRM",
        },
        "mistral": {
            "configured": mistral_available(),
            "label": "Mistral KI",
        },
    }
