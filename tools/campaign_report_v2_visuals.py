"""Campaign Report v2 — Markdown / Mermaid visual helpers (Sales / Notion).

Notion unterstuetzt nur einen Teil von Mermaid (u.a. flowchart, pie).
Kein xychart-beta — nur kompatible Diagramme.
"""

from __future__ import annotations

import re

from tools.campaign_report_v2_metrics import (
    DeliveryHealth,
    FunnelStage,
    SegmentRow,
    V2MetricsBundle,
    WindowTrend,
)


def _mermaid_sanitize_label(s: str, max_len: int = 42) -> str:
    """Node-Text fuer flowchart/pie: keine Zeilenumbrueche, keine problematischen Zeichen."""
    t = (s or "").replace("\n", " ").replace("\r", " ")
    t = t.replace('"', "'").replace("[", "(").replace("]", ")")
    t = re.sub(r"\s+", " ", t).strip()
    return t[:max_len] if len(t) > max_len else t


def _trend_arrow(t: WindowTrend) -> str:
    if t.delta_pct is None:
        return "—"
    if t.delta_pct > 0.05:
        return "▲"
    if t.delta_pct < -0.05:
        return "▼"
    return "●"


def _fmt_trend_row(t: WindowTrend) -> str:
    cur = int(t.current) if t.current == int(t.current) else round(t.current, 1)
    prev = int(t.previous) if t.previous == int(t.previous) else round(t.previous, 1)
    if t.delta_pct is None:
        pct = "n/a"
    else:
        pct = f"{t.delta_pct:+.1f}%"
    arr = _trend_arrow(t)
    lab = _mermaid_sanitize_label(t.label, 56)
    return f"| {lab} | {cur} | {prev} | {pct} | {arr} |\n"


def mermaid_funnel_flowchart(stages: list[FunnelStage], short_labels: list[str]) -> str:
    """Funnel als flowchart TD mit %-Labels auf den Kanten (Notion-kompatibel)."""
    if len(stages) != len(short_labels) or not stages:
        return ""
    lines = ["```mermaid", "flowchart TD"]
    for i, (st, short) in enumerate(zip(stages, short_labels, strict=True)):
        nid = f"F{i}"
        safe_short = _mermaid_sanitize_label(short, 20)
        lines.append(f'  {nid}["{safe_short}<br/>{st.count}"]')
    for i in range(len(stages) - 1):
        nxt = stages[i + 1]
        pct = nxt.pct_of_prior
        if pct is None:
            lbl = "—"
        else:
            lbl = f"{pct:.1f} %"
        lbl = _mermaid_sanitize_label(lbl, 16)
        lines.append(f'  F{i} -->|"{lbl}"| F{i + 1}')
    lines.append("```\n")
    return "\n".join(lines) + "\n"


def mermaid_delivery_pie(dh: DeliveryHealth | None) -> str:
    if dh is None or dh.total <= 0:
        return ""
    slices: list[tuple[str, int]] = [
        ("Delivered", dh.delivered),
        ("Bounced", dh.bounced),
        ("Suppressed", dh.suppressed),
        ("Failed", dh.failed),
        ("Complained", dh.complained),
        ("Opened (Resend)", dh.opened_tracked),
        ("Clicked (Resend)", dh.clicked_tracked),
        ("Sonstige", dh.other),
    ]
    slices = [(a, b) for a, b in slices if b > 0]
    if len(slices) <= 1:
        return ""
    lines = ["```mermaid", "pie showData", '    title Resend-Sample: letzte Events (vereinfacht)']
    for name, val in slices[:10]:
        lines.append(f'    "{_mermaid_sanitize_label(name, 28)}" : {val}')
    lines.append("```\n")
    return "\n".join(lines) + "\n"


def mermaid_volume_pie(rows: list[SegmentRow], title: str, max_slices: int = 6) -> str:
    if not rows:
        return ""
    sorted_r = sorted(rows, key=lambda r: -r.n)
    top = sorted_r[: max_slices - 1]
    rest_n = sum(r.n for r in sorted_r[max_slices - 1 :])
    parts: list[tuple[str, int]] = [(_mermaid_sanitize_label(r.key, 24), r.n) for r in top]
    if rest_n > 0:
        parts.append(("Sonstige", rest_n))
    lines = ["```mermaid", "pie showData", f'    title {_mermaid_sanitize_label(title, 40)}']
    for name, val in parts:
        lines.append(f'    "{name}" : {val}')
    lines.append("```\n")
    return "\n".join(lines) + "\n"


def mermaid_sendtime_pies(
    weekday: list,
    daypart: list,
) -> str:
    """Zwei kompakte pie-Charts fuer Wochentag und Tageszeit (nur wenn Daten)."""
    out: list[str] = []
    if weekday:
        lines = ["```mermaid", "pie showData", "    title Sends nach Wochentag (UTC)"]
        for s in weekday:
            if s.n_sends <= 0:
                continue
            lines.append(f'    "{_mermaid_sanitize_label(s.label, 22)}" : {s.n_sends}')
        lines.append("```\n")
        out.append("\n".join(lines) + "\n")
    if daypart:
        lines = ["```mermaid", "pie showData", "    title Sends nach Tageszeit-Bucket (UTC)"]
        for s in daypart:
            if s.n_sends <= 0:
                continue
            lines.append(f'    "{_mermaid_sanitize_label(s.label, 28)}" : {s.n_sends}')
        lines.append("```\n")
        out.append("\n".join(lines) + "\n")
    return "".join(out)


def _snapshot_callout(bundle: V2MetricsBundle) -> str:
    t_send = bundle.trends_7d[0] if bundle.trends_7d else None
    arr_send = _trend_arrow(t_send) if t_send else "●"
    prob = bundle.resend_sample_bounce_rate
    prob_s = f"{prob:.1f} %" if prob is not None else "n/a"
    op = bundle.snapshot_open_rate_sent30_pct
    cl = bundle.snapshot_clarity_session_sum
    op_s = f"{op:.1f} %" if op is not None else "n/a"
    ck = bundle.snapshot_click_rate_sent30_pct
    ck_s = f"{ck:.1f} %" if ck is not None else "n/a"
    block = (
        "### Snapshot (diese Periode)\n\n"
        "> **"
        f"{bundle.snapshot_total_contacts} Kontakte** · **{bundle.snapshot_eligible_contacts} mail-eligible** · "
        f"**{bundle.snapshot_resend_sample_n} Resend-Sends (Sample)** · "
        f"**Problem-Rate (Sample): {prob_s}** · **Open-Rate (Send 30d): {op_s}** {arr_send} · "
        f"**Click-Rate (Send 30d): {ck_s}** · **Clarity URL-Sessions Σ: {cl}**"
        "\n\n"
        "*Vergleich Send-Volumen 7d: ▲ höher vs. Vorperiode, ▼ niedriger, ● stabil.*\n\n"
    )
    return block


def render_v2_markdown(bundle: V2MetricsBundle) -> str:
    """Sales-Story v2 fuer Notion (Markdown + nur flowchart/pie)."""
    out: list[str] = []
    out.append("## 2b) Sales-Dashboard v2 — Snapshot, Funnel, Patterns, Top-Leads\n\n")
    out.append(
        "> **Hinweis (Notion):** Nur **flowchart**- und **pie**-Diagramme. "
        "Fuer **Open/Click**-Zahlen muessen Resend-Webhooks und Domain-Tracking aktiv sein — sonst 0% trotz Send.\n\n"
    )
    out.append(f"*Generiert (UTC): {bundle.generated_at_utc}*\n\n")

    for n in bundle.notes:
        out.append(f"> {n}\n\n")

    if bundle.alerts:
        out.append("### Alerts\n\n")
        for a in bundle.alerts:
            out.append(f"- **{a.severity}**: {a.message}\n")
        out.append("\n")

    out.append("---\n\n")
    out.append(_snapshot_callout(bundle))

    out.append("---\n\n")
    out.append("### Zustellung (Resend-Sample)\n\n")
    if bundle.delivery_health:
        dh = bundle.delivery_health
        out.append("| Kategorie | Anzahl |\n| --- | ---: |\n")
        out.append(f"| Delivered | {dh.delivered} |\n")
        out.append(f"| Bounced | {dh.bounced} |\n")
        out.append(f"| Suppressed | {dh.suppressed} |\n")
        out.append(f"| Failed | {dh.failed} |\n")
        out.append(f"| Complained | {dh.complained} |\n")
        out.append(f"| Opened (Resend-Event) | {dh.opened_tracked} |\n")
        out.append(f"| Clicked (Resend-Event) | {dh.clicked_tracked} |\n")
        out.append(f"| Sonstige | {dh.other} |\n")
        out.append(f"| **Gesamt** | **{dh.total}** |\n\n")
    pie_d = mermaid_delivery_pie(bundle.delivery_health)
    if pie_d:
        out.append(pie_d)

    out.append("---\n\n")
    out.append("### Funnel (CRM + Clarity)\n\n")
    funnel_short = ["Eligible", "Send 30d", "Open", "Click", "Clarity"]
    if bundle.funnel:
        out.append("| Stufe | Anzahl | % von vorher |\n| --- | ---: | ---: |\n")
        for st in bundle.funnel:
            pct = "—" if st.pct_of_prior is None else f"{st.pct_of_prior:.1f} %"
            lab = _mermaid_sanitize_label(st.name, 70)
            out.append(f"| {lab} | {st.count} | {pct} |\n")
        out.append("\n")
        short = funnel_short[: len(bundle.funnel)]
        while len(short) < len(bundle.funnel):
            short.append(f"S{len(short)}")
        out.append(mermaid_funnel_flowchart(bundle.funnel, short))

    out.append("---\n\n")
    out.append("### Wo verlieren wir Leads? (Drop-off)\n\n")
    if bundle.drop_off_insights_de:
        for s in bundle.drop_off_insights_de:
            out.append(f"- {s}\n")
        out.append(
            "\n*Ursache pruefen: Tracking aus, Webhook fehlt, Domain-Reputation, Betreff/CTA, oder falsche Zielgruppe.*\n\n"
        )
    else:
        out.append("*Keine Drop-off-Kanten berechenbar.*\n\n")

    out.append("---\n\n")
    out.append("### Performance: Sequence + utm_campaign\n\n")
    if bundle.segments_sequence:
        out.append("#### Nach Sequence\n\n")
        out.append("| Sequence | n | Vol.% | Opens % | Clicks % | Clarity Σ |\n")
        out.append("| --- | ---: | ---: | ---: | ---: | ---: |\n")
        for r in bundle.segments_sequence[:15]:
            seq = _mermaid_sanitize_label(r.key, 26)
            out.append(
                f"| {seq} | {r.n} | {r.volume_share_pct:.1f} | {r.open_rate:.1f} | {r.click_rate:.1f} | {r.clarity_sessions} |\n"
            )
        out.append("\n")
        out.append(mermaid_volume_pie(bundle.segments_sequence, "Volumen Sequence", 6))
    else:
        out.append("*Keine Sequence-Segmente über Mindestgröße.*\n\n")

    if bundle.segments_utm_campaign:
        out.append("\n#### Nach utm_campaign\n\n")
        out.append("| utm_campaign | n | Vol.% | Opens % | Clicks % | Clarity Σ |\n")
        out.append("| --- | ---: | ---: | ---: | ---: | ---: |\n")
        for r in bundle.segments_utm_campaign[:15]:
            uc = _mermaid_sanitize_label(r.key, 26)
            out.append(
                f"| {uc} | {r.n} | {r.volume_share_pct:.1f} | {r.open_rate:.1f} | {r.click_rate:.1f} | {r.clarity_sessions} |\n"
            )
        out.append("\n")
        out.append(mermaid_volume_pie(bundle.segments_utm_campaign, "Volumen utm_campaign", 6))
    else:
        out.append("\n*Keine utm_campaign-Segmente über Mindestgröße.*\n\n")

    out.append("---\n\n")
    out.append("### Sendezeit-Muster (UTC)\n\n")
    out.append(mermaid_sendtime_pies(bundle.send_time_weekday, bundle.send_time_daypart))
    if bundle.send_time_weekday:
        out.append("| Wochentag | Sends | Open-Rate % |\n| --- | ---: | ---: |\n")
        for s in bundle.send_time_weekday:
            out.append(f"| {s.label} | {s.n_sends} | {s.open_rate_pct:.1f} |\n")
        out.append("\n")
    if bundle.send_time_daypart:
        out.append("| Tageszeit | Sends | Open-Rate % |\n| --- | ---: | ---: |\n")
        for s in bundle.send_time_daypart:
            out.append(f"| {s.label} | {s.n_sends} | {s.open_rate_pct:.1f} |\n")
        out.append("\n")
    if bundle.send_time_recommendation_de:
        out.append(f"> {bundle.send_time_recommendation_de}\n\n")

    out.append("---\n\n")
    out.append("### Domain-Risiken (Resend-Sample)\n\n")
    if bundle.domain_risks:
        out.append("| Domain | Sends | Probleme | Rate % |\n| --- | ---: | ---: | ---: |\n")
        for dr in bundle.domain_risks[:15]:
            out.append(f"| `{dr.domain}` | {dr.n_sends} | {dr.n_problem} | {dr.problem_rate_pct:.1f} |\n")
        out.append("\n")
    else:
        out.append("*Keine Domains mit ausreichend Volumen (min. 3 Sends) im Sample.*\n\n")

    out.append("---\n\n")
    out.append("### Top-Leads (Score + empfohlene Aktion)\n\n")
    if not bundle.lead_scores:
        out.append("*Keine Scores.*\n\n")
    else:
        out.append("| Score | Firma | E-Mail | Aktion | Treiber (Auszug) |\n")
        out.append("| ---: | --- | --- | --- | --- |\n")
        for row in bundle.lead_scores[:15]:
            co = _mermaid_sanitize_label(row.company, 28)
            act = _mermaid_sanitize_label(row.recommended_action_de, 36)
            drv = _mermaid_sanitize_label("; ".join(row.reasons[:2]), 48)
            out.append(f"| {row.score:.0f} | {co} | `{row.email}` | {act} | {drv} |\n")
        out.append("\n")

    out.append("---\n\n")
    out.append("### Next-Best-Actions (Sales)\n\n")
    if bundle.sales_next_best_actions:
        for b in bundle.sales_next_best_actions:
            out.append(f"- {b}\n")
        out.append("\n")
    else:
        out.append("- *(Keine automatischen Empfehlungen — Datenlage zu dünn.)*\n\n")

    out.append("---\n\n")
    out.append("### Detail: Datenqualität & Attribution\n\n")
    if bundle.quality:
        q = bundle.quality
        out.append("| Metrik | Wert |\n| --- | ---: |\n")
        out.append(f"| Anteil mit Stamm-Link | {q.pct_with_link:.1f} % |\n")
        out.append(f"| user_id = Kunden_ID (wo beide gesetzt) | {q.pct_user_id_matches_kunden_id:.1f} % |\n")
        out.append(f"| UTM-Tripel ableitbar | {q.pct_has_utm_triple:.1f} % |\n")
        if q.pct_resend_matched is not None:
            out.append(f"| CRM-E-Mail im Resend-Sample | {q.pct_resend_matched:.1f} % |\n")
        out.append(f"| Clarity URL-Match (Kunden_ID) | {q.attribution_strong_pct:.1f} % |\n")
        out.append("\n")

    out.append("---\n\n")
    out.append("### Detail: Trendfenster (7d / 30d)\n\n")
    out.append(
        "Vergleich **aktuelles Fenster** und **gleich langes vorheriges Fenster** (UTC). "
        "Spalte **Trend**: ▲ höher, ▼ niedriger, ● stabil / n/a.\n\n"
    )
    out.append("#### 7 Tage\n\n")
    out.append("| Kennzahl | Aktuell | Vorperiode | Delta % | Trend |\n| --- | ---: | ---: | ---: | :---: |\n")
    for t in bundle.trends_7d:
        out.append(_fmt_trend_row(t))
    out.append("\n#### 30 Tage\n\n")
    out.append("| Kennzahl | Aktuell | Vorperiode | Delta % | Trend |\n| --- | ---: | ---: | ---: | :---: |\n")
    for t in bundle.trends_30d:
        out.append(_fmt_trend_row(t))
    out.append("\n")

    out.append("---\n\n")
    out.append("### Detail: Kohorten (Sende-Woche)\n\n")
    if not bundle.cohorts:
        out.append("*Keine Kohorten im 8-Wochen-Fenster.*\n\n")
    else:
        out.append("| Woche | n | Open % | Click % |\n| --- | ---: | ---: | ---: |\n")
        for c in bundle.cohorts:
            out.append(f"| {c.week_label} | {c.cohort_size} | {c.open_rate:.1f} | {c.click_rate:.1f} |\n")
        out.append("\n")

    out.append("---\n\n")
    out.append("### Detail: Latenz (Median)\n\n")
    if bundle.lag:
        lg = bundle.lag
        so_s = f"{lg.send_to_open_hours_median:.1f} h" if lg.send_to_open_hours_median is not None else "—"
        oc_s = f"{lg.open_to_click_hours_median:.1f} h" if lg.open_to_click_hours_median is not None else "—"
        out.append(
            f"- **Send → Open:** {so_s} (n = {lg.n_send_open_pairs})\n"
            f"- **Open → Click:** {oc_s} (n = {lg.n_open_click_pairs})\n\n"
        )
    else:
        out.append("*Keine Latenzdaten.*\n\n")

    return "".join(out)
