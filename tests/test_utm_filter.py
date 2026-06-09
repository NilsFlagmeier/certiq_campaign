"""Unit tests for UTM filter helpers and campaign analytics filtering."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from lib.campaign_clarity import _aggregate_url_rows, row_session_estimate
from lib.campaign_store import aggregate_campaign_summary
from lib.utm_filter import (
    UtmFilter,
    matches_row,
    matches_store_row,
    matches_url_query,
    parse_bool_query,
    parse_tracking_url,
    to_query_params,
    utm_filter_from_query,
)


EXAMPLE_URL = (
    "https://certiq.tech/?user_id=205&utm_campaign=business_card_intro"
    "&utm_content=A&utm_medium=email&utm_source=newsletter&utm_term=tp1"
)


class TestParseTrackingUrl(unittest.TestCase):
    def test_example_url(self) -> None:
        filt = parse_tracking_url(EXAMPLE_URL)
        self.assertEqual(filt.user_id, "205")
        self.assertEqual(filt.utm_campaign, "business_card_intro")
        self.assertEqual(filt.utm_content, "A")
        self.assertEqual(filt.utm_medium, "email")
        self.assertEqual(filt.utm_source, "newsletter")
        self.assertEqual(filt.utm_term, "tp1")

    def test_relative_url(self) -> None:
        filt = parse_tracking_url("/?utm_campaign=test&utm_source=newsletter")
        self.assertEqual(filt.utm_campaign, "test")
        self.assertEqual(filt.utm_source, "newsletter")


class TestMatchesRow(unittest.TestCase):
    def test_partial_campaign_filter(self) -> None:
        row = {
            "utm_source": "newsletter",
            "utm_medium": "email",
            "utm_campaign": "business_card_intro",
            "kunden_id": "205",
        }
        filt = UtmFilter(utm_campaign="business_card_intro")
        self.assertTrue(matches_row(row, filt))
        self.assertFalse(matches_row(row, UtmFilter(utm_campaign="other")))

    def test_store_row_matches_without_content_term(self) -> None:
        row = {
            "utm_source": "newsletter",
            "utm_medium": "email",
            "utm_campaign": "business_card_intro",
            "kunden_id": "205",
        }
        filt = UtmFilter(
            utm_source="newsletter",
            utm_medium="email",
            utm_campaign="business_card_intro",
            user_id="205",
        )
        self.assertTrue(matches_row(row, filt))

    def test_full_url_filter_requires_content_term_on_row(self) -> None:
        row = {
            "utm_source": "newsletter",
            "utm_medium": "email",
            "utm_campaign": "business_card_intro",
            "kunden_id": "205",
        }
        filt = parse_tracking_url(EXAMPLE_URL)
        self.assertFalse(matches_row(row, filt))
        self.assertTrue(matches_store_row(row, filt))

    def test_user_id_filter(self) -> None:
        row = {"kunden_id": "205", "utm_campaign": "business_card_intro"}
        self.assertTrue(matches_row(row, UtmFilter(user_id="205")))
        self.assertFalse(matches_row(row, UtmFilter(user_id="999")))

    def test_empty_filter_matches_all(self) -> None:
        row = {"utm_campaign": "x"}
        self.assertTrue(matches_row(row, UtmFilter()))


class TestQueryHelpers(unittest.TestCase):
    def test_utm_filter_from_query(self) -> None:
        filt = utm_filter_from_query(
            {
                "utm_source": ["newsletter"],
                "utm_campaign": ["business_card_intro"],
                "user_id": ["205"],
            }
        )
        self.assertEqual(filt.utm_source, "newsletter")
        self.assertEqual(filt.utm_campaign, "business_card_intro")
        self.assertEqual(filt.user_id, "205")

    def test_to_query_params(self) -> None:
        params = to_query_params(parse_tracking_url(EXAMPLE_URL))
        self.assertEqual(params["utm_term"], "tp1")
        self.assertEqual(params["utm_content"], "A")

    def test_parse_bool_query(self) -> None:
        self.assertTrue(parse_bool_query("1"))
        self.assertTrue(parse_bool_query("true"))
        self.assertFalse(parse_bool_query("0"))
        self.assertFalse(parse_bool_query(""))


class TestStoreAggregationFilter(unittest.TestCase):
    @patch("lib.campaign_store.list_events_for_sync")
    def test_filters_by_utm_triple_and_user_id(self, mock_list) -> None:
        mock_list.return_value = [
            {
                "event_type": "email_sent",
                "kunden_id": "205",
                "email": "a@example.com",
                "utm_source": "newsletter",
                "utm_medium": "email",
                "utm_campaign": "business_card_intro",
                "created_at": "2026-06-01T10:00:00+00:00",
            },
            {
                "event_type": "email_sent",
                "kunden_id": "999",
                "email": "b@example.com",
                "utm_source": "newsletter",
                "utm_medium": "email",
                "utm_campaign": "other_campaign",
                "created_at": "2026-06-01T10:00:00+00:00",
            },
        ]
        filt = UtmFilter(
            utm_source="newsletter",
            utm_medium="email",
            utm_campaign="business_card_intro",
            user_id="205",
        )
        summary = aggregate_campaign_summary(utm_filter=filt)
        self.assertEqual(summary["totals"]["email_sent"], 1)
        self.assertEqual(len(summary["leads"]), 1)
        self.assertEqual(summary["leads"][0]["kunden_id"], "205")


class TestClarityUrlFilter(unittest.TestCase):
    def test_matches_url_query(self) -> None:
        url = EXAMPLE_URL
        self.assertTrue(matches_url_query(url, parse_tracking_url(EXAMPLE_URL)))
        self.assertFalse(matches_url_query(url, UtmFilter(utm_content="B")))

    def test_aggregate_url_rows(self) -> None:
        rows = [
            {
                "URL": EXAMPLE_URL,
                "totalSessionCount": "3",
            },
            {
                "URL": "https://certiq.tech/?user_id=999&utm_campaign=other",
                "totalSessionCount": "5",
            },
        ]
        filt = UtmFilter(utm_campaign="business_card_intro", user_id="205")
        result = _aggregate_url_rows(rows, filt)
        self.assertEqual(result["sessions"], 3)
        self.assertEqual(result["byUserId"]["205"]["sessions"], 3)
        self.assertNotIn("999", result["byUserId"])

    def test_row_session_estimate(self) -> None:
        self.assertEqual(row_session_estimate({"totalSessionCount": "4"}), 4)
        self.assertEqual(row_session_estimate({"DistinctSessions": "2"}), 2)


if __name__ == "__main__":
    unittest.main()
