import copy
import unittest
from pathlib import Path

from india_trader.core import entry, load_bars, plan, read, simulate, stamp
from india_trader.market import (
    bar_grid,
    bundled_calendar,
    eligibility,
    instrument_on,
    merge_instruments,
    phase_at,
    resolve_session,
)

FIXTURE = Path(__file__).resolve().parents[1] / "india_trader/templates/demo"


def metadata(kind="CAS", tick="0.10", start="2026-08-03"):
    return {
        "NSE:RELIANCE": {
            "versions": [
                {
                    "valid_from": start,
                    "valid_to": None,
                    "observed_on": start,
                    "source": "SYNTHETIC test metadata",
                    "asset": "EQUITY",
                    "lot_size": 1,
                    "session_class": kind,
                    "tick_size": tick,
                    "intraday_allowed": True,
                    "eligibility_source": "https://example.com/test-eligibility",
                    "eligibility_broker": "zerodha",
                }
            ]
        }
    }


class MarketTests(unittest.TestCase):
    def setUp(self):
        self.calendar = bundled_calendar()
        self.meta = metadata()

    def resolve(self, day="2026-10-19", broker="zerodha"):
        return resolve_session(self.calendar, "NSE", day, "NSE:RELIANCE", self.meta, broker)

    def test_cas_has_72_continuous_bars_and_early_broker_exit(self):
        s = self.resolve()
        self.assertEqual(len(bar_grid(s)), 72)
        self.assertEqual(s["flat_by"].strftime("%H:%M"), "15:02")
        self.assertEqual(phase_at(s, stamp("2026-10-19T15:22:00+05:30")), "auction")

    def test_non_cas_has_75_intervals_on_same_day(self):
        self.meta = metadata("NON_CAS")
        self.assertEqual(len(bar_grid(self.resolve())), 75)

    def test_future_rule_does_not_activate_early(self):
        self.assertEqual(self.resolve("2026-12-04")["policy_id"], "nse-cas-2026-08")
        future = self.resolve("2026-12-07")
        self.assertEqual(future["policy_id"], "nse-cas-2026-12")
        self.assertEqual(len(bar_grid(future)), 75)
        self.assertEqual(future["cutoff_status"], "UNVERIFIED")

    def test_holiday_and_election_addendum_fail_closed(self):
        for day in ("2026-10-20", "2026-01-15"):
            with self.assertRaisesRegex(ValueError, "CLOSED"):
                self.resolve(day)

    def test_muhurat_times_are_not_invented(self):
        with self.assertRaisesRegex(ValueError, "UNVERIFIED"):
            self.resolve("2026-11-08")

    def test_bse_and_unknown_year_not_inferred_from_nse(self):
        with self.assertRaises(ValueError):
            resolve_session(self.calendar, "BSE", "2026-10-19", "BSE:RELIANCE", self.meta)
        with self.assertRaises(ValueError):
            self.resolve("2027-01-04")

    def test_groww_cas_deadline_stays_unverified(self):
        self.assertEqual(self.resolve(broker="groww")["cutoff_status"], "UNVERIFIED")

    def test_special_session_uses_its_own_grid(self):
        day = self.calendar["days"]["NSE:2026-11-08"]
        day.update(
            status="OPEN",
            source="SYNTHETIC special-session notice",
            phases=[{"kind": "continuous", "start": "18:00:00", "end": "19:00:00"}],
        )
        self.assertEqual(len(bar_grid(self.resolve("2026-11-08", broker="groww"))), 12)

    def test_bad_phase_overlap_rejected(self):
        self.calendar["days"]["NSE:2026-10-19"]["phases"] = [
            {"kind": "continuous", "start": "09:15:00", "end": "15:15:00"},
            {"kind": "auction", "start": "15:10:00", "end": "15:35:00"},
        ]
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            self.resolve()

    def test_ambiguous_rules_fail_closed(self):
        self.calendar["policies"].append(copy.deepcopy(self.calendar["policies"][0]))
        with self.assertRaisesRegex(ValueError, "exactly one"):
            self.resolve()

    def test_snapshot_never_backfills_prior_metadata(self):
        merged = merge_instruments(
            {},
            {"NSE:RELIANCE": {"tick_size": "0.10", "asset": "EQUITY", "lot_size": 1}},
            "2026-10-30",
            "test master",
        )
        with self.assertRaises(ValueError):
            instrument_on(merged, "NSE:RELIANCE", "2026-10-29", strict=True)

    def test_tick_versions_remain_historical(self):
        incoming = dict(self.meta["NSE:RELIANCE"]["versions"][0], tick_size="0.50")
        merged = merge_instruments(
            self.meta, {"NSE:RELIANCE": incoming}, "2026-10-30", "test new tick"
        )
        self.assertEqual(instrument_on(merged, "NSE:RELIANCE", "2026-10-19")["tick_size"], "0.10")
        self.assertEqual(instrument_on(merged, "NSE:RELIANCE", "2026-10-30")["tick_size"], "0.50")

    def test_explicit_eligibility_revocation_is_not_overwritten(self):
        old = metadata(start="2026-10-30")
        changed = dict(old["NSE:RELIANCE"]["versions"][0], intraday_allowed=False)
        merged = merge_instruments(old, {"NSE:RELIANCE": changed}, "2026-10-30", "test review")
        self.assertEqual(
            eligibility(instrument_on(merged, "NSE:RELIANCE", "2026-10-30"), "zerodha")["status"],
            "BLOCKED",
        )

    def test_eligibility_is_broker_specific(self):
        record = self.meta["NSE:RELIANCE"]["versions"][0]
        self.assertEqual(eligibility(record, "groww")["status"], "UNVERIFIED")
        record["series"] = "BE"
        self.assertEqual(eligibility(record, "zerodha")["status"], "BLOCKED")

    def test_cas_replay_accepts_complete_72_bar_days(self):
        rows = load_bars(FIXTURE / "bars.csv")
        # Use invented dates/status overrides so these fixtures never imply observed exchange data.
        for row in rows:
            day = row["timestamp"].date()
            self.calendar["days"]["NSE:" + str(day)] = {
                "status": "OPEN",
                "source": "SYNTHETIC fixture calendar",
            }
        now = stamp("2026-10-19T09:35:00+05:30")
        signal = entry(rows, "NSE:RELIANCE", now, self.calendar, self.meta, "zerodha")
        p = plan(signal, "0.10")
        config = read(FIXTURE / "config.json")
        config.update(instruments=self.meta, broker="zerodha")
        result = simulate(p, rows, self.calendar, config, 10)
        self.assertEqual(result["prior_sessions"], 25)
        self.assertEqual(result["session_policy_id"], "nse-cas-2026-08")

    def test_auction_candles_cannot_create_an_ordinary_entry(self):
        rows = load_bars(FIXTURE / "bars.csv")
        now = stamp("2026-10-19T15:30:00+05:30")
        today = [r for r in rows if r["timestamp"].date() == now.date()]
        today = today[:3]  # no continuous-session breakout
        auction = copy.deepcopy(rows[-1])
        auction["timestamp"] = stamp("2026-10-19T15:20:00+05:30")
        result = entry(today + [auction], "NSE:RELIANCE", now, self.calendar, self.meta, "zerodha")
        self.assertEqual(result["status"], "expired")
