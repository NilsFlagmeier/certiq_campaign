"""Unit tests for campaign report v2 metrics (no network)."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

from tools.campaign_report_v2_metrics import (
    FunnelStage,
    V2MetricsBundle,
    compute_v2_metrics,
    derive_lead_action,
    parse_iso_datetime,
    _normalize_resend_to_email,
)
from tools.campaign_report_v2_visuals import render_v2_markdown


def _contact(**kwargs: object) -> SimpleNamespace:
    base = dict(
        email="lead@example.com",
        company="Example GmbH",
        pipeline_status="cold",
        email_state="working",
        sequence="live_demo",
        open_count=0,
        click_count=0,
        last_sent_at="",
        last_opened_at="",
        last_clicked_at="",
        sent_campaigns=[],
        utm_campaign=["live_demo"],
        tags=[],
        next_send_at="",
        kunden_id="19",
        link="https://certiq.tech/?user_id=19&utm_source=outreach&utm_medium=email&utm_campaign=live_demo",
        parsed_link={
            "user_id": "19",
            "utm_source": "outreach",
            "utm_medium": "email",
            "utm_campaign": "live_demo",
        },
        utm_source_field="outreach",
        utm_medium_field="email",
        utm_term_field="",
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


class TestParseIso(unittest.TestCase):
    def test_z_suffix(self) -> None:
        dt = parse_iso_datetime("2026-01-10T12:00:00Z")
        assert dt is not None
        self.assertEqual(dt.tzinfo, timezone.utc)

    def test_offset(self) -> None:
        dt = parse_iso_datetime("2026-01-10T12:00:00.000+00:00")
        assert dt is not None
        self.assertEqual(dt.hour, 12)


class TestResendEmailNorm(unittest.TestCase):
    def test_angle(self) -> None:
        self.assertEqual(
            _normalize_resend_to_email("Name <lead@example.com>"),
            "lead@example.com",
        )

    def test_plain(self) -> None:
        self.assertEqual(_normalize_resend_to_email("lead@example.com"), "lead@example.com")


class TestV2FunnelMonotonic(unittest.TestCase):
    def test_funnel_non_increasing(self) -> None:
        fixed = datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)
        sent_ts = (fixed - timedelta(days=5)).isoformat()
        contacts = [
            _contact(email="a@x.com", kunden_id="1", last_sent_at=sent_ts, open_count=1, click_count=0),
            _contact(email="b@x.com", kunden_id="2", last_sent_at=sent_ts, open_count=0, click_count=0),
            _contact(
                email="c@x.com",
                kunden_id="3",
                last_sent_at=sent_ts,
                open_count=1,
                click_count=1,
                last_opened_at=sent_ts,
                last_clicked_at=sent_ts,
            ),
        ]
        url_rows = [{"URL": "https://certiq.tech/?user_id=3", "DistinctSessions": "5"}]
        bundle = compute_v2_metrics(
            contacts,
            [{"to": "a@x.com", "created_at": sent_ts, "last_event": "delivered"}],
            None,
            None,
            None,
            url_rows,
            None,
            utm_aliases={},
            now=fixed,
        )
        counts = [st.count for st in bundle.funnel]
        for a, b in zip(counts, counts[1:], strict=False):
            self.assertGreaterEqual(a, b, msg=f"funnel not monotonic: {counts}")


class TestRenderMarkdown(unittest.TestCase):
    def test_contains_sections(self) -> None:
        b = V2MetricsBundle(generated_at_utc="x")
        md = render_v2_markdown(b)
        self.assertIn("Sales-Dashboard v2", md)
        self.assertIn("Trendfenster", md)
        self.assertNotIn("xychart-beta", md)

    def test_mermaid_uses_flowchart_for_funnel(self) -> None:
        b = V2MetricsBundle(
            generated_at_utc="x",
            funnel=[
                FunnelStage("Stage A", 100, None),
                FunnelStage("Stage B", 40, 40.0),
            ],
        )
        md = render_v2_markdown(b)
        self.assertIn("flowchart TD", md)
        self.assertIn('-->|"', md)
        self.assertIn("40.0 %", md)
        self.assertNotIn("xychart-beta", md)

    def test_drop_off_renders_when_present(self) -> None:
        b = V2MetricsBundle(
            generated_at_utc="2026-05-13 12:00 UTC",
            funnel=[
                FunnelStage("a", 10, None),
                FunnelStage("b", 5, 50.0),
            ],
            drop_off_insights_de=["**Eligible → Send**: 10 → 5 (50.0% bleiben; Drop **50.0%**)."],
        )
        md = render_v2_markdown(b)
        self.assertIn("Drop-off", md)
        self.assertIn("Eligible", md)


class TestGeneratedAtRegression(unittest.TestCase):
    def test_no_isocalendar_leak_in_output(self) -> None:
        """Regression: cohort loop must not shadow generated-at string."""
        fixed = datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)
        w1 = "2026-05-01T12:00:00Z"
        w2 = "2026-01-01T12:00:00Z"
        contacts = [
            _contact(email="a@x.com", last_sent_at=w1),
            _contact(email="b@x.com", last_sent_at=w2),
        ]
        bundle = compute_v2_metrics(
            contacts,
            None,
            None,
            None,
            None,
            None,
            None,
            utm_aliases={},
            now=fixed,
        )
        self.assertRegex(bundle.generated_at_utc, r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC$")
        md = render_v2_markdown(bundle)
        self.assertNotIn("IsoCalendarDate", md)


class TestLeadActionMapping(unittest.TestCase):
    def test_cold_low_score_wait(self) -> None:
        act, _de = derive_lead_action(3.0, [], "cold")
        self.assertEqual(act, "wait")

    def test_clarity_driver_call(self) -> None:
        act, _de = derive_lead_action(40.0, ["Clarity URL-Sessions≈8 (+26)"], "warm")
        self.assertEqual(act, "call")


if __name__ == "__main__":
    unittest.main()
