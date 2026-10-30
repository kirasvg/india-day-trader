import unittest
from pathlib import Path

from india_trader.core import read, stamp
from india_trader.research import earnings, monitor, parse_feed

FIXTURE = Path(__file__).resolve().parents[1] / "india_trader" / "templates" / "demo"
NOW = stamp("2026-10-19T09:35:00+05:30")


class ResearchTests(unittest.TestCase):
    def test_rss_dates_and_html(self):
        rows = parse_feed((FIXTURE / "sample.xml").read_bytes(), "fixture")
        self.assertEqual(len(rows), 1)
        self.assertEqual(stamp(rows[0]["published_at"]).hour, 9)

    def test_official_nse_local_date_has_explicit_normalization_provenance(self):
        content = b"<rss><channel><item><title>Fixture</title><pubDate>30-Oct-2026 09:30:00</pubDate></item></channel></rss>"
        row = parse_feed(
            content, "https://nsearchives.nseindia.com/content/RSS/Financial_Results.xml"
        )[0]
        self.assertEqual(row["published_at"], "2026-10-30T09:30:00+05:30")
        self.assertEqual(row["publication_time_basis"], "NSE_LOCAL_IST_NORMALIZATION")
        for source in (
            "https://example.com/content/RSS/example.xml",
            "https://nsearchives.nseindia.com.attacker.example/content/RSS/example.xml",
        ):
            self.assertIsNone(parse_feed(content, source)[0]["published_at"])

    def test_atom_feed(self):
        rows = parse_feed(
            b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Results</title><updated>2026-10-19T03:00:00Z</updated><link href="https://example.com/a"/></entry></feed>',
            "fixture",
        )
        self.assertEqual(rows[0]["url"], "https://example.com/a")

    def test_xml_entities_rejected(self):
        with self.assertRaises(ValueError):
            parse_feed(b'<!DOCTYPE rss [<!ENTITY a "bad">]><rss/>', "fixture")

    def test_html_error_page_not_reported_as_empty_feed(self):
        with self.assertRaisesRegex(ValueError, "not an RSS"):
            parse_feed(b"<html><body>Access denied</body></html>", "fixture")

    def test_actual_empty_rss_is_valid_but_marked_no_coverage(self):
        rows = parse_feed(b"<rss><channel><title>Empty feed</title></channel></rss>", "fixture")
        result = monitor(rows, NOW, 24)
        self.assertEqual(result["input_items"], 0)
        self.assertIn("incomplete", result["warning"])

    def test_timezone_offsets_sorted_by_actual_time(self):
        rows = [
            {"title": "Earlier", "published_at": "2026-10-19T09:00:00+05:30"},
            {"title": "Later", "published_at": "2026-10-19T04:00:00Z"},
        ]
        self.assertEqual(monitor(rows, NOW, 24)["items"][0]["title"], "Later")

    def test_undated_and_future_news_not_current(self):
        rows = [
            {"title": "News", "published_at": None},
            {"title": "Future", "published_at": "2026-10-20T09:00:00+05:30"},
        ]
        result = monitor(rows, NOW, 24)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["skipped_undated"], 1)

    def test_disclosure_filter_and_deduplication(self):
        rows = read(FIXTURE / "news-input.json")
        result = monitor(rows, NOW, 24, {"NSE:RELIANCE": ["Reliance Industries"]}, True)
        self.assertEqual(len(result["items"]), 1)
        self.assertIn("insider-disclosure", result["items"][0]["tags"])
        again = monitor(rows, NOW, 24, disclosures=True, seen=[r["id"] for r in result["items"]])
        self.assertFalse(again["items"])

    def test_alias_matching_does_not_match_substrings(self):
        rows = [{"title": "INFYSOMETHING result", "published_at": NOW.isoformat()}]
        self.assertFalse(monitor(rows, NOW, 24, {"NSE:INFY": ["INFY"]})["items"])

    def test_earnings_qoq_and_yoy(self):
        result = earnings(read(FIXTURE / "financials.json"))
        self.assertEqual(result["comparisons"]["yoy"]["revenue"]["change_pct"], "20.0")
        self.assertIsNotNone(result["comparisons"]["qoq"])

    def test_mixed_basis_rejected(self):
        rows = read(FIXTURE / "financials.json")
        rows[0]["basis"] = "standalone"
        with self.assertRaises(ValueError):
            earnings(rows)

    def test_negative_earnings_base_not_misleading_growth(self):
        rows = read(FIXTURE / "financials.json")
        rows[0]["net_profit"] = "-100"
        result = earnings(rows)["comparisons"]["yoy"]["net_profit"]
        self.assertIsNone(result["change_pct"])
        self.assertEqual(result["absolute_change"], "225")
