"""Full campaign analytics report merging store, Twenty, and Clarity."""

from __future__ import annotations

from typing import Any

from lib.campaign_clarity import fetch_clarity_campaign_signals
from lib.campaign_store import aggregate_campaign_summary, recommendation_for_segment
from lib.twenty_crm import people_for_campaign


def build_campaign_analytics_report(utm_campaign: str = "") -> dict[str, Any]:
    summary = aggregate_campaign_summary(utm_campaign=utm_campaign)
    clarity = fetch_clarity_campaign_signals(utm_campaign=utm_campaign)
    people_index: dict[str, dict[str, Any]] = {}
    email_index: dict[str, dict[str, Any]] = {}
    try:
        people = people_for_campaign()
    except Exception:  # noqa: BLE001
        people = []
    for person in people:
        pid = person.get("person_id") or ""
        email = (person.get("email") or "").lower()
        if pid:
            people_index[pid] = person
        if email:
            email_index[email] = person

    enriched: list[dict[str, Any]] = []
    for lead in summary.get("leads", []):
        kid = lead.get("kunden_id") or ""
        email = (lead.get("email") or "").lower()
        person = people_index.get(kid) or email_index.get(email) or {}
        clarity_data = clarity.get("byUserId", {}).get(kid) or {}
        segment = lead.get("segment") or "not_sent"
        enriched.append(
            {
                **lead,
                "firstName": person.get("first_name", ""),
                "lastName": person.get("last_name", ""),
                "company": person.get("company", ""),
                "emailState": person.get("email_state", ""),
                "lastContactedAt": person.get("last_contacted_at", ""),
                "claritySessions": clarity_data.get("sessions", 0),
                "recommendation": recommendation_for_segment(segment),
            }
        )

    follow_up = [e for e in enriched if e.get("segment") in {"hot", "warm"}]
    top_interest = sorted(enriched, key=lambda x: x.get("score", 0), reverse=True)[:25]

    totals = summary.get("totals", {})
    kpis = {
        "sent": int(totals.get("email_sent", 0)),
        "opened": int(totals.get("resend.opened", 0)),
        "clicked": int(totals.get("resend.clicked", 0)),
        "bounced": int(totals.get("resend.bounced", 0)),
        "unsubscribed": int(totals.get("unsubscribe", 0)),
        "complained": int(totals.get("resend.complained", 0)),
    }

    return {
        "utmCampaign": utm_campaign,
        "kpis": kpis,
        "segments": summary.get("segments", {}),
        "totals": totals,
        "clarity": {"configured": clarity.get("configured", False), "totals": clarity.get("totals", {})},
        "leads": enriched,
        "followUpNow": follow_up,
        "topInterest": top_interest,
        "behaviorGuide": [
            {"segment": "hot", "text": recommendation_for_segment("hot")},
            {"segment": "warm", "text": recommendation_for_segment("warm")},
            {"segment": "mild", "text": recommendation_for_segment("mild")},
            {"segment": "cold", "text": recommendation_for_segment("cold")},
            {"segment": "bounced", "text": recommendation_for_segment("bounced")},
            {"segment": "unsubscribed", "text": recommendation_for_segment("unsubscribed")},
            {"segment": "complained", "text": recommendation_for_segment("complained")},
        ],
    }
