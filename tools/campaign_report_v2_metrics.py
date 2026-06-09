"""
Campaign Report v2 — metrics, timelines, segments, scoring (no I/O).

Used by tools/campaign_report.py. Avoids importing campaign_report to prevent cycles.
"""

from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol, runtime_checkable
from urllib.parse import parse_qs, urlparse

_RESEND_ANGLE_EMAIL = re.compile(r"<([^<\s]+@[^>\s]+)>")
_RESEND_LOOSE_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")


def _normalize_resend_to_email(raw: Any) -> str:
    """First To-address from Resend row, lowercase (aligned with campaign_report)."""
    if isinstance(raw, list):
        for x in raw:
            s = x if isinstance(x, str) else (str(x) if x is not None else "")
            m = _RESEND_ANGLE_EMAIL.search(s)
            if m:
                return m.group(1).strip().lower()
            m2 = _RESEND_LOOSE_EMAIL.search(s)
            if m2:
                return m2.group(0).strip().lower()
    elif isinstance(raw, str):
        m = _RESEND_ANGLE_EMAIL.search(raw)
        if m:
            return m.group(1).strip().lower()
        m2 = _RESEND_LOOSE_EMAIL.search(raw)
        if m2:
            return m2.group(0).strip().lower()
    elif raw is not None:
        s = str(raw)
        m = _RESEND_ANGLE_EMAIL.search(s)
        if m:
            return m.group(1).strip().lower()
        m2 = _RESEND_LOOSE_EMAIL.search(s)
        if m2:
            return m2.group(0).strip().lower()
    return ""


def parse_iso_datetime(raw: str) -> datetime | None:
    """Parse Notion/Resend ISO timestamps to UTC-aware datetime."""
    s = (raw or "").strip()
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except (TypeError, ValueError):
        return None


@runtime_checkable
class ContactForV2(Protocol):
    email: str
    company: str
    pipeline_status: str
    email_state: str
    sequence: str
    open_count: int
    click_count: int
    last_sent_at: str
    last_opened_at: str
    last_clicked_at: str
    sent_campaigns: list[str]
    utm_campaign: list[str]
    tags: list[str]
    next_send_at: str
    kunden_id: str
    link: str
    parsed_link: dict[str, str]
    utm_source_field: str
    utm_medium_field: str
    utm_term_field: str


def _norm_utm_token(s: str) -> str:
    return (s or "").strip().lower().replace(" ", "_").replace("-", "_")


def _canon_campaign(camp: str, aliases: dict[str, str]) -> str:
    t = _norm_utm_token(camp)
    return aliases.get(t, t)


def effective_utm_triple(c: ContactForV2, aliases: dict[str, str]) -> tuple[str, str, str] | None:
    pq = c.parsed_link
    src = _norm_utm_token(pq.get("utm_source", "") or c.utm_source_field)
    med = _norm_utm_token(pq.get("utm_medium", "") or c.utm_medium_field)
    camp_raw = pq.get("utm_campaign", "") or (c.utm_campaign[0] if c.utm_campaign else "")
    camp = _canon_campaign(str(camp_raw), aliases)
    if not src and not med and not camp:
        return None
    return (src, med, camp)


def _blocked_email_state(state: str) -> bool:
    s = (state or "").strip().lower()
    return s in {"bounced", "unsubscribed"} or "bounce" in s


def row_session_estimate(r: dict[str, Any]) -> int:
    raw = (
        r.get("DistinctSessions")
        or r.get("totalSessionCount")
        or r.get("distantUserCount")
        or "0"
    )
    try:
        return int(float(str(raw).replace(",", "")))
    except (TypeError, ValueError):
        return 0


def clarity_row_key(r: dict[str, Any], aliases: dict[str, str]) -> tuple[str, str, str]:
    src = _norm_utm_token(str(r.get("Source") or r.get("source") or ""))
    med = _norm_utm_token(str(r.get("Medium") or r.get("medium") or ""))
    camp = _canon_campaign(str(r.get("Campaign") or r.get("campaign") or ""), aliases)
    return (src, med, camp)


@dataclass
class WindowTrend:
    label: str
    current: float
    previous: float
    delta_abs: float
    delta_pct: float | None  # None if previous == 0


@dataclass
class FunnelStage:
    name: str
    count: int
    pct_of_prior: float | None  # None for first stage


@dataclass
class SegmentRow:
    key: str
    n: int
    opens: int
    clicks: int
    clarity_sessions: int  # sum of max sessions per kid in segment (approx)
    open_rate: float
    click_rate: float
    volume_share_pct: float = 0.0  # Anteil am Segment-Gesamt-n (gleiche Dimension)


@dataclass
class DeliveryHealth:
    """Resend-Sample: Zaehlung nach letztem Event/Status (vereinfachte Kategorien)."""

    delivered: int
    bounced: int
    suppressed: int
    failed: int
    complained: int
    opened_tracked: int
    clicked_tracked: int
    other: int
    total: int


@dataclass
class DomainRiskRow:
    domain: str
    n_sends: int
    n_problem: int
    problem_rate_pct: float


@dataclass
class SendTimeStat:
    """Aggregation nach Wochentag oder Tageszeit-Bucket (UTC)."""

    label: str
    n_sends: int
    n_with_open_signal: int
    open_rate_pct: float


@dataclass
class LeadScoreRow:
    email: str
    company: str
    pipeline_status: str
    score: float
    reasons: list[str]
    lead_action: str  # call | followup | nurture | wait
    recommended_action_de: str


@dataclass
class CohortRow:
    week_label: str
    cohort_size: int
    open_rate: float
    click_rate: float


@dataclass
class LagStats:
    send_to_open_hours_median: float | None
    open_to_click_hours_median: float | None
    n_send_open_pairs: int
    n_open_click_pairs: int


@dataclass
class DataQuality:
    pct_with_link: float
    pct_user_id_matches_kunden_id: float
    pct_has_utm_triple: float
    pct_resend_matched: float | None  # None if no resend data
    attribution_strong_pct: float  # kid in clarity uid map with sessions


@dataclass
class AlertRow:
    severity: str  # high, medium, low
    message: str


@dataclass
class V2MetricsBundle:
    generated_at_utc: str
    trends_7d: list[WindowTrend] = field(default_factory=list)
    trends_30d: list[WindowTrend] = field(default_factory=list)
    funnel: list[FunnelStage] = field(default_factory=list)
    segments_sequence: list[SegmentRow] = field(default_factory=list)
    segments_utm_campaign: list[SegmentRow] = field(default_factory=list)
    lead_scores: list[LeadScoreRow] = field(default_factory=list)
    cohorts: list[CohortRow] = field(default_factory=list)
    lag: LagStats | None = None
    quality: DataQuality | None = None
    alerts: list[AlertRow] = field(default_factory=list)
    resend_sample_bounce_rate: float | None = None
    notes: list[str] = field(default_factory=list)
    delivery_health: DeliveryHealth | None = None
    domain_risks: list[DomainRiskRow] = field(default_factory=list)
    send_time_weekday: list[SendTimeStat] = field(default_factory=list)
    send_time_daypart: list[SendTimeStat] = field(default_factory=list)
    send_time_recommendation_de: str = ""
    drop_off_insights_de: list[str] = field(default_factory=list)
    sales_next_best_actions: list[str] = field(default_factory=list)
    # Snapshot-Zahlen (Sales-Callout, unabhaengig vom Markdown-Renderer)
    snapshot_total_contacts: int = 0
    snapshot_eligible_contacts: int = 0
    snapshot_resend_sample_n: int = 0
    snapshot_clarity_session_sum: int = 0
    snapshot_open_rate_sent30_pct: float | None = None
    snapshot_click_rate_sent30_pct: float | None = None


def _in_window(ts: datetime | None, start: datetime, end: datetime) -> bool:
    if ts is None:
        return False
    return start <= ts <= end


_WEEKDAY_DE = ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So")


def _daypart_label_utc(hour: int) -> str:
    if 6 <= hour < 11:
        return "Morgen (06–11 UTC)"
    if 11 <= hour < 14:
        return "Mittag (11–14 UTC)"
    if 14 <= hour < 18:
        return "Nachmittag (14–18 UTC)"
    if 18 <= hour < 22:
        return "Abend (18–22 UTC)"
    return "Nacht (sonst UTC)"


def _classify_resend_delivery_row(e: dict[str, Any]) -> str:
    ev = str(e.get("last_event") or e.get("event") or e.get("status") or "").strip().lower()
    if ev in {"bounced"}:
        return "bounced"
    if ev in {"suppressed"}:
        return "suppressed"
    if ev in {"failed"}:
        return "failed"
    if ev in {"complained", "complaint"}:
        return "complained"
    if ev in {"clicked"}:
        return "clicked_tracked"
    if ev in {"opened"}:
        return "opened_tracked"
    if ev in {"delivered", "delivery_delayed", "sent"}:
        return "delivered"
    return "other"


def delivery_health_from_resend(
    emails: list[dict[str, Any]] | None,
    resend_error: str | None,
) -> DeliveryHealth | None:
    if not emails or resend_error:
        return None
    d = 0
    b = 0
    s = 0
    f = 0
    c = 0
    o = 0
    cl = 0
    ot = 0
    for e in emails:
        if not isinstance(e, dict):
            continue
        cat = _classify_resend_delivery_row(e)
        if cat == "delivered":
            d += 1
        elif cat == "bounced":
            b += 1
        elif cat == "suppressed":
            s += 1
        elif cat == "failed":
            f += 1
        elif cat == "complained":
            c += 1
        elif cat == "opened_tracked":
            o += 1
        elif cat == "clicked_tracked":
            cl += 1
        else:
            ot += 1
    tot = d + b + s + f + c + o + cl + ot
    if tot == 0:
        return None
    return DeliveryHealth(
        delivered=d,
        bounced=b,
        suppressed=s,
        failed=f,
        complained=c,
        opened_tracked=o,
        clicked_tracked=cl,
        other=ot,
        total=tot,
    )


def _resend_row_is_problem(e: dict[str, Any]) -> bool:
    cat = _classify_resend_delivery_row(e)
    return cat in {"bounced", "suppressed", "failed", "complained"}


def domain_risks_from_resend(
    emails: list[dict[str, Any]] | None,
    resend_error: str | None,
    *,
    min_n: int = 3,
    top: int = 12,
) -> list[DomainRiskRow]:
    if not emails or resend_error:
        return []
    by_dom: dict[str, list[bool]] = defaultdict(list)
    for e in emails:
        if not isinstance(e, dict):
            continue
        addr = _normalize_resend_to_email(e.get("to"))
        if not addr or "@" not in addr:
            continue
        dom = addr.split("@", 1)[1].strip().lower()
        if not dom:
            continue
        by_dom[dom].append(_resend_row_is_problem(e))
    rows: list[DomainRiskRow] = []
    for dom, flags in by_dom.items():
        n = len(flags)
        if n < min_n:
            continue
        prob = sum(1 for x in flags if x)
        rate = 100.0 * prob / max(n, 1)
        rows.append(DomainRiskRow(domain=dom, n_sends=n, n_problem=prob, problem_rate_pct=rate))
    rows.sort(key=lambda r: (-r.problem_rate_pct, -r.n_problem, -r.n_sends))
    return rows[:top]


def _open_signal_contact(c: ContactForV2) -> bool:
    return c.open_count > 0 or parse_iso_datetime(c.last_opened_at) is not None


def send_time_stats_from_contacts(
    contacts_sent_in_window: list[ContactForV2],
) -> tuple[list[SendTimeStat], list[SendTimeStat], str]:
    """Wochentag + Tageszeit (UTC) aus Last_Sent_At."""
    wd_counts: dict[int, list[ContactForV2]] = defaultdict(list)
    part_counts: dict[str, list[ContactForV2]] = defaultdict(list)
    for c in contacts_sent_in_window:
        ts = parse_iso_datetime(c.last_sent_at)
        if ts is None:
            continue
        wd = ts.weekday()  # Mon=0
        wd_counts[wd].append(c)
        part = _daypart_label_utc(ts.hour)
        part_counts[part].append(c)

    def _stats(groups: dict[Any, list[ContactForV2]], label_fn: Any) -> list[SendTimeStat]:
        out: list[SendTimeStat] = []
        for k in sorted(groups.keys(), key=lambda x: (isinstance(x, int), x)):
            grp = groups[k]
            n = len(grp)
            opens = sum(1 for x in grp if _open_signal_contact(x))
            lab = label_fn(k)
            out.append(
                SendTimeStat(
                    label=lab,
                    n_sends=n,
                    n_with_open_signal=opens,
                    open_rate_pct=100.0 * opens / max(n, 1),
                )
            )
        out.sort(key=lambda s: -s.open_rate_pct)
        return out

    wd_stats = _stats(wd_counts, lambda wd: f"{_WEEKDAY_DE[int(wd)]} (UTC)")
    # Sort Mo–So for display table
    order = {lab: i for i, lab in enumerate(_WEEKDAY_DE)}
    wd_stats.sort(key=lambda s: order.get(s.label.split()[0], 99))

    part_order = [
        "Morgen (06–11 UTC)",
        "Mittag (11–14 UTC)",
        "Nachmittag (14–18 UTC)",
        "Abend (18–22 UTC)",
        "Nacht (sonst UTC)",
    ]
    part_stats_raw = _stats(part_counts, lambda k: str(k))
    part_stats = sorted(part_stats_raw, key=lambda s: part_order.index(s.label) if s.label in part_order else 99)

    rec = ""
    candidates = [s for s in part_stats if s.n_sends >= 5] or part_stats
    if candidates:
        best = max(candidates, key=lambda s: (s.open_rate_pct, s.n_sends))
        rec = (
            f"Heuristik: **{best.label}** zeigt unter den Buckets mit ausreichend Volumen "
            f"die beste Open-Rate (**{best.open_rate_pct:.1f}%**, n={best.n_sends}). "
            "Testweise mehr Sends in diesem Fenster planen (A/B)."
        )
    return wd_stats, part_stats, rec


def funnel_short_names() -> list[str]:
    return [
        "Eligible",
        "Send 30d",
        "Open",
        "Click",
        "Clarity",
    ]


def drop_off_insights_de(funnel: list[FunnelStage], short_names: list[str]) -> list[str]:
    if len(funnel) < 2 or len(short_names) != len(funnel):
        return []
    losses: list[tuple[float, str]] = []
    for i in range(len(funnel) - 1):
        a, b = funnel[i], funnel[i + 1]
        if a.count <= 0:
            continue
        conv = 100.0 * b.count / a.count
        drop = max(0.0, 100.0 - conv)
        s_from = short_names[i]
        s_to = short_names[i + 1]
        losses.append(
            (
                drop,
                f"**{s_from} → {s_to}**: {a.count} → {b.count} "
                f"({conv:.1f}% bleiben; Drop **{drop:.1f}%**).",
            )
        )
    losses.sort(key=lambda x: -x[0])
    return [s for _, s in losses[:3]]


def derive_lead_action(score: float, reasons: list[str], pipeline: str) -> tuple[str, str]:
    pl = (pipeline or "").strip().lower()
    rs = " ".join(reasons).lower()
    if score >= 55.0 or ("clarity url-sessions" in rs and score >= 38.0):
        return "call", "Anruf / Direktkontakt (hoher Intent)"
    if "klick" in rs or "click in den letzten" in rs or score >= 35.0:
        return "call", "Anruf — starkes Engagement"
    if "opens=" in rs or "crm opens" in rs or score >= 15.0:
        return "followup", "Mail-Follow-up (Interesse, noch kein Klick)"
    if pl in {"cold", "idle"} and score < 10.0:
        return "wait", "Warten / nächste Sequenz-Stufe"
    if score < 5.0:
        return "nurture", "Pflege-Touch (leichter Inhalt)"
    return "followup", "Mail-Follow-up"


def _apply_volume_share(rows: list[SegmentRow]) -> None:
    tot = sum(r.n for r in rows)
    if tot <= 0:
        return
    for r in rows:
        r.volume_share_pct = 100.0 * r.n / tot


def build_sales_next_best_actions(
    *,
    alerts: list[AlertRow],
    drop_offs: list[str],
    domain_risks: list[DomainRiskRow],
    segments_seq: list[SegmentRow],
    segments_utm: list[SegmentRow],
    resend_problem_pct: float | None,
    funnel: list[FunnelStage],
) -> list[str]:
    bullets: list[str] = []
    if resend_problem_pct is not None and resend_problem_pct > 3.0:
        bullets.append(
            f"**Zustellung prüfen:** Resend-Sample-Problemrate **{resend_problem_pct:.1f}%** — "
            "Listenhygiene, Domain-Reputation, Suppressions."
        )
    if drop_offs:
        bullets.append(
            "**Engagement-Lücke:** " + drop_offs[0].replace("**", "") + " Tracking/Webhooks und Betreff/CTA prüfen."
        )
    if domain_risks and domain_risks[0].problem_rate_pct >= 25.0:
        dr = domain_risks[0]
        bullets.append(
            f"**Risiko-Domain:** `{dr.domain}` — {dr.n_problem}/{dr.n_sends} problematisch "
            f"({dr.problem_rate_pct:.0f}%). Segmentierung oder separates Profil erwägen."
        )
    if segments_seq:
        best = max(segments_seq, key=lambda r: (r.open_rate, r.n))
        worst = min(segments_seq, key=lambda r: (r.open_rate, -r.n))
        if best.key != worst.key:
            bullets.append(
                f"**Sequences:** Best Open-Rate `{best.key[:40]}` ({best.open_rate:.1f}%, n={best.n}), "
                f"schwächste `{worst.key[:40]}` ({worst.open_rate:.1f}%). Winner-Template skalieren."
            )
    if segments_utm:
        best_c = max(segments_utm, key=lambda r: (r.click_rate, r.open_rate))
        bullets.append(
            f"**Kampagne (utm):** `{best_c.key[:40]}` — Klicks {best_c.click_rate:.1f}%, Opens {best_c.open_rate:.1f}% "
            f"(n={best_c.n}); Learnings in die nächste Welle übernehmen."
        )
    if funnel and len(funnel) >= 3:
        sent_n = funnel[1].count
        open_n = funnel[2].count
        if sent_n > 50 and open_n == 0:
            bullets.append(
                "**Opens = 0 bei Volumen:** Resend Open-Tracking + Webhooks aktivieren und prüfen, "
                "ob CRM `Last_Opened_At` befüllt wird."
            )
    for a in alerts:
        if a.severity == "high" and a.message not in str(bullets):
            bullets.append(f"**Alert:** {a.message}")
            break
    return bullets[:5]


def _count_contacts_sent_in_window(contacts: list[ContactForV2], start: datetime, end: datetime) -> int:
    n = 0
    for c in contacts:
        t = parse_iso_datetime(c.last_sent_at)
        if _in_window(t, start, end):
            n += 1
    return n


def _count_contacts_open_in_window(contacts: list[ContactForV2], start: datetime, end: datetime) -> int:
    n = 0
    for c in contacts:
        t = parse_iso_datetime(c.last_opened_at)
        if _in_window(t, start, end):
            n += 1
    return n


def _count_contacts_click_in_window(contacts: list[ContactForV2], start: datetime, end: datetime) -> int:
    n = 0
    for c in contacts:
        t = parse_iso_datetime(c.last_clicked_at)
        if _in_window(t, start, end):
            n += 1
    return n


def _resend_created_at(e: dict[str, Any]) -> datetime | None:
    return parse_iso_datetime(str(e.get("created_at") or ""))


def _count_resend_in_window(
    emails: list[dict[str, Any]] | None,
    start: datetime,
    end: datetime,
) -> int:
    if not emails:
        return 0
    n = 0
    for e in emails:
        if not isinstance(e, dict):
            continue
        t = _resend_created_at(e)
        if _in_window(t, start, end):
            n += 1
    return n


def _make_trend(label: str, cur: float, prev: float) -> WindowTrend:
    d = cur - prev
    if prev == 0:
        pct = None if cur == 0 else 100.0
    else:
        pct = 100.0 * d / prev
    return WindowTrend(label=label, current=cur, previous=prev, delta_abs=d, delta_pct=pct)


def compute_v2_metrics(
    contacts: list[ContactForV2],
    resend_emails: list[dict[str, Any]] | None,
    resend_error: str | None,
    clarity_rows: list[dict[str, Any]] | None,
    clarity_error: str | None,
    clarity_url_rows: list[dict[str, Any]] | None,
    clarity_url_error: str | None,
    *,
    utm_aliases: dict[str, str],
    now: datetime | None = None,
) -> V2MetricsBundle:
    now = now or datetime.now(timezone.utc)
    now = now.astimezone(timezone.utc)
    generated_at_utc_str = now.strftime("%Y-%m-%d %H:%M UTC")

    min_seg = 5
    try:
        min_seg = max(1, int(os.getenv("CAMPAIGN_REPORT_V2_MIN_SEGMENT", "5") or "5"))
    except ValueError:
        min_seg = 5

    notes: list[str] = []
    notes.append(
        "Trends basieren auf **Zeitstempeln** (`Last_Sent_At`, `Last_Opened_At`, `Last_Clicked_At`) "
        "und Resend-`created_at` — nicht auf kumulierten Zählern allein."
    )
    if clarity_rows and not clarity_error:
        notes.append(f"Clarity SMC: **{len(clarity_rows)}** Export-Zeilen (Source/Medium/Campaign).")

    # --- Windows (UTC) ---
    d7 = timedelta(days=7)
    d30 = timedelta(days=30)
    end = now

    def pair(w: timedelta) -> tuple[datetime, datetime, datetime, datetime]:
        cur_start = end - w
        prev_start = end - 2 * w
        prev_end = cur_start - timedelta(seconds=1)
        return cur_start, end, prev_start, prev_end

    c7s, c7e, p7s, p7e = pair(d7)
    c30s, c30e, p30s, p30e = pair(d30)

    trends_7d: list[WindowTrend] = [
        _make_trend(
            "Kontakte mit Send im 7d-Fenster",
            float(_count_contacts_sent_in_window(contacts, c7s, c7e)),
            float(_count_contacts_sent_in_window(contacts, p7s, p7e)),
        ),
        _make_trend(
            "Kontakte mit Open-Event im 7d-Fenster",
            float(_count_contacts_open_in_window(contacts, c7s, c7e)),
            float(_count_contacts_open_in_window(contacts, p7s, p7e)),
        ),
        _make_trend(
            "Kontakte mit Click-Event im 7d-Fenster",
            float(_count_contacts_click_in_window(contacts, c7s, c7e)),
            float(_count_contacts_click_in_window(contacts, p7s, p7e)),
        ),
        _make_trend(
            "Resend-Sends im 7d-Fenster (Sample)",
            float(_count_resend_in_window(resend_emails, c7s, c7e)),
            float(_count_resend_in_window(resend_emails, p7s, p7e)),
        ),
    ]

    trends_30d: list[WindowTrend] = [
        _make_trend(
            "Kontakte mit Send im 30d-Fenster",
            float(_count_contacts_sent_in_window(contacts, c30s, c30e)),
            float(_count_contacts_sent_in_window(contacts, p30s, p30e)),
        ),
        _make_trend(
            "Kontakte mit Open-Event im 30d-Fenster",
            float(_count_contacts_open_in_window(contacts, c30s, c30e)),
            float(_count_contacts_open_in_window(contacts, p30s, p30e)),
        ),
        _make_trend(
            "Kontakte mit Click-Event im 30d-Fenster",
            float(_count_contacts_click_in_window(contacts, c30s, c30e)),
            float(_count_contacts_click_in_window(contacts, p30s, p30e)),
        ),
        _make_trend(
            "Resend-Sends im 30d-Fenster (Sample)",
            float(_count_resend_in_window(resend_emails, c30s, c30e)),
            float(_count_resend_in_window(resend_emails, p30s, p30e)),
        ),
    ]

    # --- Clarity URL map (reuse logic inline) ---
    uid_sessions: dict[str, int] = defaultdict(int)
    url_rows = clarity_url_rows or []
    if url_rows and not clarity_url_error:
        for r in url_rows:
            if not isinstance(r, dict):
                continue
            raw_url = str(r.get("URL") or r.get("Url") or r.get("url") or "")
            s = raw_url.strip()
            if not s:
                continue
            if "://" not in s:
                s = "https://placeholder.local/" + s.lstrip("/")
            try:
                q = parse_qs(urlparse(s).query)
                uid = (q.get("user_id") or [""])[0].strip()
            except Exception:
                uid = ""
            if uid:
                uid_sessions[uid] += row_session_estimate(r)
    uid_sessions = dict(uid_sessions)

    by_kid: dict[str, list[ContactForV2]] = defaultdict(list)
    for c in contacts:
        kid = (c.kunden_id or "").strip()
        if kid:
            by_kid[kid].append(c)

    # --- Funnel (monotonic: eligible -> sent 30d -> open -> click -> clarity among clickers) ---
    eligible = [c for c in contacts if not _blocked_email_state(c.email_state)]
    n_eligible = len(eligible)
    sent_30 = [c for c in eligible if _in_window(parse_iso_datetime(c.last_sent_at), c30s, c30e)]
    n_sent = len(sent_30)
    opened_30 = [
        c for c in sent_30 if c.open_count > 0 or parse_iso_datetime(c.last_opened_at) is not None
    ]
    n_opened = len(opened_30)
    clicked_30 = [
        c for c in opened_30 if c.click_count > 0 or parse_iso_datetime(c.last_clicked_at) is not None
    ]
    n_clicked = len(clicked_30)
    clarity_after_click = sum(
        1
        for c in clicked_30
        if uid_sessions.get((c.kunden_id or "").strip(), 0) > 0
    )

    funnel_counts = [n_eligible, n_sent, n_opened, n_clicked, clarity_after_click]
    funnel_names = [
        "Mail-eligible CRM (nicht bounced/unsub)",
        "Send im letzten 30d-Fenster",
        "Open-Signal (Zähler oder Open-Zeit)",
        "Click-Signal (Zähler oder Click-Zeit)",
        "Clarity URL-Sessions > 0 unter Clickern (Kunden_ID=user_id)",
    ]
    funnel: list[FunnelStage] = []
    prior = None
    for name, cnt in zip(funnel_names, funnel_counts, strict=True):
        pct = None
        if prior is not None and prior > 0:
            pct = 100.0 * cnt / prior
        funnel.append(FunnelStage(name=name, count=cnt, pct_of_prior=pct))
        prior = cnt

    # --- Resend bounce rate in sample ---
    resend_bounce_rate: float | None = None
    if resend_emails and not resend_error:
        bad = sum(
            1
            for e in resend_emails
            if isinstance(e, dict)
            and (
                (str(e.get("last_event") or e.get("event") or "").strip().lower() in {"bounced", "suppressed", "failed"})
                or (str(e.get("status") or "").strip().lower() in {"bounced", "suppressed", "failed"})
            )
        )
        resend_bounce_rate = 100.0 * bad / max(len(resend_emails), 1)

    # --- Segments ---
    def segment_key_sequence(c: ContactForV2) -> str:
        s = (c.sequence or "").strip()
        return s or "(leer)"

    def segment_key_campaign(c: ContactForV2) -> str:
        t = effective_utm_triple(c, utm_aliases)
        if t:
            return t[2] or "(utm_campaign leer)"
        if c.utm_campaign:
            return c.utm_campaign[0]
        return "(kein utm_campaign)"

    def build_segment_rows(
        key_fn: Any,
    ) -> list[SegmentRow]:
        groups: dict[str, list[ContactForV2]] = defaultdict(list)
        for c in eligible:
            groups[key_fn(c)].append(c)
        rows: list[SegmentRow] = []
        for key, grp in groups.items():
            if len(grp) < min_seg:
                continue
            opens = sum(1 for x in grp if x.open_count > 0)
            clicks = sum(1 for x in grp if x.click_count > 0)
            sess = 0
            for x in grp:
                kid = (x.kunden_id or "").strip()
                if kid:
                    sess += uid_sessions.get(kid, 0)
            rows.append(
                SegmentRow(
                    key=key[:80],
                    n=len(grp),
                    opens=opens,
                    clicks=clicks,
                    clarity_sessions=sess,
                    open_rate=100.0 * opens / max(len(grp), 1),
                    click_rate=100.0 * clicks / max(len(grp), 1),
                    volume_share_pct=0.0,
                )
            )
        rows.sort(key=lambda r: (-r.click_rate, -r.n))
        rows = rows[:25]
        _apply_volume_share(rows)
        return rows

    segments_sequence = build_segment_rows(segment_key_sequence)
    segments_utm = build_segment_rows(segment_key_campaign)

    # --- Lead scoring ---
    def score_contact(c: ContactForV2) -> tuple[float, list[str]]:
        reasons: list[str] = []
        score = 0.0
        kid = (c.kunden_id or "").strip()
        cs = uid_sessions.get(kid, 0) if kid else 0
        if cs > 0:
            add = min(40.0, 10.0 + cs * 2.0)
            score += add
            reasons.append(f"Clarity URL-Sessions≈{cs} (+{add:.0f})")
        ck = min(30.0, 6.0 * min(c.click_count, 5))
        score += ck
        if c.click_count:
            reasons.append(f"CRM Klicks={c.click_count} (+{ck:.0f})")
        op = min(20.0, 2.0 * min(c.open_count, 10))
        score += op
        if c.open_count:
            reasons.append(f"CRM Opens={c.open_count} (+{op:.0f})")
        if _blocked_email_state(c.email_state):
            score -= 120.0
            reasons.append("Email_State riskant (−120)")
        lc = parse_iso_datetime(c.last_clicked_at)
        if lc and (now - lc).total_seconds() <= 14 * 86400 and c.click_count > 0:
            score += 12.0
            reasons.append("Click in den letzten 14d (+12)")
        return score, reasons

    scored: list[LeadScoreRow] = []
    for c in eligible:
        s, r = score_contact(c)
        act, act_de = derive_lead_action(s, r, c.pipeline_status)
        scored.append(
            LeadScoreRow(
                email=c.email,
                company=c.company or "—",
                pipeline_status=(c.pipeline_status or "").strip(),
                score=s,
                reasons=r,
                lead_action=act,
                recommended_action_de=act_de,
            )
        )
    scored.sort(key=lambda x: (-x.score, x.email))
    lead_scores = scored[:25]

    # --- Cohort by ISO week of last_sent (last 8 weeks among eligible with send) ---
    cohort_map: dict[tuple[int, int], list[ContactForV2]] = defaultdict(list)
    week_cut = now - timedelta(weeks=8)
    for c in eligible:
        ts = parse_iso_datetime(c.last_sent_at)
        if ts is None or ts < week_cut:
            continue
        ical = ts.isocalendar()
        cohort_map[(ical.year, ical.week)].append(c)

    cohorts: list[CohortRow] = []
    for (y, w) in sorted(cohort_map.keys(), reverse=True)[:10]:
        grp = cohort_map[(y, w)]
        opens = sum(1 for x in grp if x.open_count > 0)
        clicks = sum(1 for x in grp if x.click_count > 0)
        cohorts.append(
            CohortRow(
                week_label=f"{y}-W{w:02d}",
                cohort_size=len(grp),
                open_rate=100.0 * opens / max(len(grp), 1),
                click_rate=100.0 * clicks / max(len(grp), 1),
            )
        )

    # --- Lag (send -> open, open -> click) ---
    send_open_hours: list[float] = []
    open_click_hours: list[float] = []
    for c in eligible:
        ts = parse_iso_datetime(c.last_sent_at)
        to = parse_iso_datetime(c.last_opened_at)
        tc = parse_iso_datetime(c.last_clicked_at)
        if ts and to and to >= ts:
            send_open_hours.append((to - ts).total_seconds() / 3600.0)
        if to and tc and tc >= to:
            open_click_hours.append((tc - to).total_seconds() / 3600.0)

    def _median(xs: list[float]) -> float | None:
        if not xs:
            return None
        ys = sorted(xs)
        m = len(ys) // 2
        if len(ys) % 2:
            return ys[m]
        return 0.5 * (ys[m - 1] + ys[m])

    lag = LagStats(
        send_to_open_hours_median=_median(send_open_hours),
        open_to_click_hours_median=_median(open_click_hours),
        n_send_open_pairs=len(send_open_hours),
        n_open_click_pairs=len(open_click_hours),
    )

    # --- Data quality ---
    n = max(len(contacts), 1)
    with_link = sum(1 for c in contacts if (c.link or "").strip())
    uid_match = 0
    uid_both = 0
    for c in contacts:
        lu = (c.parsed_link.get("user_id") or "").strip()
        kid = (c.kunden_id or "").strip()
        if lu and kid:
            uid_both += 1
            if lu == kid:
                uid_match += 1
    utm_ok = sum(1 for c in contacts if effective_utm_triple(c, utm_aliases) is not None)
    matched_resend = 0
    if resend_emails and not resend_error:
        by_e2: dict[str, list] = defaultdict(list)
        for e in resend_emails:
            if not isinstance(e, dict):
                continue
            addr = _normalize_resend_to_email(e.get("to"))
            if addr:
                by_e2[addr].append(e)
        matched_resend = sum(1 for c in contacts if c.email in by_e2)

    strong = sum(
        1
        for c in contacts
        if (c.kunden_id or "").strip() in uid_sessions and uid_sessions.get((c.kunden_id or "").strip(), 0) > 0
    )
    quality = DataQuality(
        pct_with_link=100.0 * with_link / n,
        pct_user_id_matches_kunden_id=(100.0 * uid_match / uid_both) if uid_both else 100.0,
        pct_has_utm_triple=100.0 * utm_ok / n,
        pct_resend_matched=(100.0 * matched_resend / n) if resend_emails and not resend_error else None,
        attribution_strong_pct=100.0 * strong / n,
    )

    # --- Alerts ---
    alerts: list[AlertRow] = []
    if resend_bounce_rate is not None and resend_bounce_rate > 5.0:
        alerts.append(AlertRow("high", f"Resend-Sample Bounce/Problem-Rate hoch: {resend_bounce_rate:.1f}%"))
    orphan = sum(1 for u in uid_sessions if u not in by_kid)
    if orphan > 20:
        alerts.append(AlertRow("medium", f"Viele orphan `user_id` in Clarity-URLs: {orphan}"))
    if clarity_error:
        alerts.append(AlertRow("low", f"Clarity SMC nicht verfügbar: {clarity_error}"))
    if resend_error:
        alerts.append(AlertRow("low", f"Resend nicht angebunden: {resend_error}"))

    delivery_health = delivery_health_from_resend(resend_emails, resend_error)
    domain_risks = domain_risks_from_resend(resend_emails, resend_error)
    send_wd, send_part, send_rec = send_time_stats_from_contacts(sent_30)
    funnel_short = funnel_short_names()
    drop_offs_de = drop_off_insights_de(funnel, funnel_short)
    next_actions = build_sales_next_best_actions(
        alerts=alerts,
        drop_offs=drop_offs_de,
        domain_risks=domain_risks,
        segments_seq=segments_sequence,
        segments_utm=segments_utm,
        resend_problem_pct=resend_bounce_rate,
        funnel=funnel,
    )

    clarity_sum = int(sum(uid_sessions.values())) if uid_sessions else 0
    snap_open_pct = None
    snap_click_pct = None
    if n_sent > 0:
        snap_open_pct = 100.0 * n_opened / n_sent
        snap_click_pct = 100.0 * n_clicked / n_sent

    return V2MetricsBundle(
        generated_at_utc=generated_at_utc_str,
        trends_7d=trends_7d,
        trends_30d=trends_30d,
        funnel=funnel,
        segments_sequence=segments_sequence,
        segments_utm_campaign=segments_utm,
        lead_scores=lead_scores,
        cohorts=cohorts,
        lag=lag,
        quality=quality,
        alerts=alerts,
        resend_sample_bounce_rate=resend_bounce_rate,
        notes=notes,
        delivery_health=delivery_health,
        domain_risks=domain_risks,
        send_time_weekday=send_wd,
        send_time_daypart=send_part,
        send_time_recommendation_de=send_rec,
        drop_off_insights_de=drop_offs_de,
        sales_next_best_actions=next_actions,
        snapshot_total_contacts=len(contacts),
        snapshot_eligible_contacts=n_eligible,
        snapshot_resend_sample_n=len(resend_emails) if resend_emails and not resend_error else 0,
        snapshot_clarity_session_sum=clarity_sum,
        snapshot_open_rate_sent30_pct=snap_open_pct,
        snapshot_click_rate_sent30_pct=snap_click_pct,
    )
