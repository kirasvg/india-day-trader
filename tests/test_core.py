import copy
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from india_trader.core import (
    D,
    alerts,
    entry,
    estimated_loss,
    load_bars,
    number,
    paper_close,
    paper_fill,
    path_outcome,
    plan,
    read,
    risk,
    session,
    simulate,
    size,
    stamp,
    ticket,
)

FIXTURE = Path(__file__).resolve().parents[1] / "india_trader" / "templates" / "demo"
NOW = stamp("2026-10-19T09:35:00+05:30")
INSTRUMENT = "NSE:RELIANCE"


class TradingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bars = load_bars(FIXTURE / "bars.csv")

    def setUp(self):
        self.config = read(FIXTURE / "config.json")
        self.config["instruments"] = read(FIXTURE / "instruments.json")
        self.calendar = read(FIXTURE / "calendar.json")
        self.account = read(FIXTURE / "account.json")
        self.quotes = read(FIXTURE / "quotes.json")
        self.signal = entry(self.bars, INSTRUMENT, NOW, self.calendar)
        self.plan = plan(self.signal, "0.05")
        self.order = size(self.plan, self.config, self.account)

    def check(self, now=NOW):
        return risk(self.order, self.config, self.account, self.quotes, self.calendar, now)

    def test_connected_risk_requires_displayed_liquidity_and_blocks_circuit(self):
        self.config["require_broker_snapshot"] = True
        result = self.check()
        self.assertTrue(any("visible bid/ask" in r for r in result["reasons"]))
        self.quotes[INSTRUMENT].update(
            bid="1007.95", ask="1008", ask_quantity=1000, upper_circuit="1008"
        )
        self.assertTrue(any("circuit limit" in r for r in self.check()["reasons"]))

    def test_closed_bar_only(self):
        self.assertEqual(
            entry(self.bars, INSTRUMENT, NOW - timedelta(seconds=1), self.calendar)["status"],
            "waiting",
        )
        self.assertEqual(self.signal["status"], "triggered")
        self.assertEqual(self.signal["entry_time"], NOW.isoformat())

    def test_missing_opening_bar_never_triggers(self):
        rows = [r for r in self.bars if r["timestamp"] != NOW - timedelta(minutes=10)]
        self.assertEqual(entry(rows, INSTRUMENT, NOW, self.calendar)["status"], "waiting")

    def test_gap_in_candles_is_unavailable(self):
        rows = [r for r in self.bars if r["timestamp"] != NOW - timedelta(minutes=5)]
        template = copy.deepcopy(self.bars[-1])
        template["timestamp"] = NOW
        rows.append(template)
        self.assertEqual(
            entry(rows, INSTRUMENT, NOW + timedelta(minutes=5), self.calendar)["status"],
            "unavailable",
        )

    def test_unknown_holiday_fails_closed(self):
        with self.assertRaises(ValueError):
            session(self.calendar, "NSE", "2026-10-20")

    def test_explicit_special_session_supported(self):
        self.calendar["sessions"]["BSE:2026-10-18"] = {
            "open": "18:00:00",
            "entry_after": "18:15:00",
            "entry_before": "18:30:00",
            "flat_by": "18:50:00",
            "close": "19:00:00",
        }
        self.assertEqual(session(self.calendar, "BSE", "2026-10-18")["open"].hour, 18)

    def test_timezone_conversion(self):
        self.assertEqual(stamp("2026-10-19T04:05:00Z"), NOW)
        with self.assertRaises(ValueError):
            stamp("2026-10-19T09:35:00")

    def test_invalid_financial_numbers_rejected(self):
        for value in ("NaN", "Infinity", True):
            with self.assertRaises(ValueError):
                number(value)

    def test_position_sizing_respects_cash_and_loss(self):
        self.assertLessEqual(estimated_loss(self.config, self.plan, self.order["quantity"]), D(500))
        self.assertLessEqual(D(self.plan["entry"]) * self.order["quantity"], D(25000))
        self.assertEqual(self.check()["status"], "PASS")

    def test_costs_can_make_one_share_impossible(self):
        self.config["max_loss_per_trade_inr"] = "10"
        with self.assertRaises(ValueError):
            size(self.plan, self.config, self.account)

    def test_negative_costs_are_invalid(self):
        self.config["roundtrip_cost_bps"] = "-1"
        with self.assertRaises(ValueError):
            self.check()

    def test_tick_size_is_not_assumed(self):
        p = plan(self.signal, "0.10")
        self.assertEqual(D(p["stop"]) % D("0.10"), 0)
        self.order["plan"]["tick_size"] = "0.10"
        self.assertEqual(self.check()["status"], "BLOCK")

    def test_unverified_instrument_blocks(self):
        self.config["instruments"] = {}
        self.assertEqual(self.check()["status"], "BLOCK")

    def test_stale_or_future_quotes_block(self):
        for seconds in (-61, 1):
            self.quotes[INSTRUMENT]["timestamp"] = (NOW + timedelta(seconds=seconds)).isoformat()
            self.assertEqual(self.check()["status"], "BLOCK")

    def test_stale_plan_blocks_even_with_fresh_quote(self):
        later = NOW + timedelta(minutes=11)
        self.quotes[INSTRUMENT]["timestamp"] = later.isoformat()
        self.assertIn("Entry plan is stale or future-dated", self.check(later)["reasons"])

    def test_invalidated_setup_blocks(self):
        self.quotes[INSTRUMENT]["price"] = self.plan["stop"]
        self.assertEqual(self.check()["status"], "BLOCK")

    def test_live_or_fractional_orders_rejected(self):
        self.order["paper"] = False
        self.assertEqual(self.check()["status"], "BLOCK")
        self.order["quantity"] = 1.5
        with self.assertRaises(ValueError):
            self.check()

    def test_order_change_gets_new_fingerprint_and_verdict(self):
        initial = self.check()
        self.order["quantity"] = 1000
        updated = self.check()
        self.assertNotEqual(initial["order_hash"], updated["order_hash"])
        self.assertEqual(updated["status"], "BLOCK")

    def test_daily_risk_includes_closed_profitable_entries(self):
        self.account["trades"] = [
            {"timestamp": NOW.isoformat(), "instrument": "NSE:INFY", "reserved_risk_inr": "1499"}
        ]
        self.assertIn("Daily risk budget exceeded", self.check()["reasons"])

    def test_entry_window_blocks_after_cutoff(self):
        after = stamp("2026-10-19T15:00:00+05:30")
        self.assertIn("Outside verified entry window", self.check(after)["reasons"])

    def test_paper_roundtrip_conserves_cash_minus_estimated_cost(self):
        filled = paper_fill(self.order, self.config, self.account, self.quotes, self.calendar, NOW)
        self.assertEqual(self.account["positions"], {})
        closed = paper_close(INSTRUMENT, filled, self.quotes, NOW, 60)
        self.assertFalse(closed["positions"])
        fee = D(filled["positions"][INSTRUMENT]["cost_reserve_inr"])
        self.assertEqual(D(closed["cash_inr"]), D(100000) - fee)

    def test_duplicate_paper_fill_blocked(self):
        filled = paper_fill(self.order, self.config, self.account, self.quotes, self.calendar, NOW)
        with self.assertRaises(ValueError):
            paper_fill(self.order, self.config, filled, self.quotes, self.calendar, NOW)

    def test_limit_order_does_not_fill_above_limit(self):
        self.quotes[INSTRUMENT]["price"] = "1008.05"
        with self.assertRaisesRegex(ValueError, "not marketable"):
            paper_fill(self.order, self.config, self.account, self.quotes, self.calendar, NOW)

    def test_exit_allowed_after_entry_cutoff(self):
        filled = paper_fill(self.order, self.config, self.account, self.quotes, self.calendar, NOW)
        after = stamp("2026-10-19T15:10:00+05:30")
        self.quotes[INSTRUMENT]["timestamp"] = after.isoformat()
        self.assertFalse(paper_close(INSTRUMENT, filled, self.quotes, after, 60)["positions"])

    def test_broker_tickets_are_unsubmitted_and_distinct(self):
        kite, groww = ticket(self.order, "zerodha"), ticket(self.order, "groww")
        self.assertIn("tradingsymbol", kite["manual_entry_payload"])
        self.assertIn("trading_symbol", groww["manual_entry_payload"])
        self.assertEqual(groww["manual_entry_payload"]["segment"], "CASH")
        self.assertFalse(kite["submitted"])
        self.assertNotIn("stop_loss", kite["manual_entry_payload"])

    def test_gap_through_stop_exits_at_gap_not_stop(self):
        outcome, price = path_outcome(
            [{"open": 90, "high": 96, "low": 89, "close": 95}], D(100), D(95), D(110)
        )
        self.assertEqual((outcome, price), ("stop", D(90)))

    def test_ambiguous_bar_stop_first(self):
        self.assertEqual(
            path_outcome(
                [{"open": 100, "high": 120, "low": 90, "close": 105}], D(100), D(95), D(110)
            )[0],
            "stop",
        )

    def test_flat_by_alert_without_fresh_price(self):
        self.assertIn("FLAT_BY", alerts(self.plan, {}, stamp(self.plan["flat_by"]), 60))
        self.assertIn("DATA_STALE", alerts(self.plan, {}, NOW, 60))

    def test_simulation_reproducible_and_excludes_future(self):
        first = simulate(self.plan, self.bars, self.calendar, self.config, 50, 19)
        future = copy.deepcopy(self.bars[-1])
        future["timestamp"] += timedelta(days=2)
        future["high"] = D(999999)
        second = simulate(self.plan, self.bars + [future], self.calendar, self.config, 50, 19)
        self.assertEqual(first, second)
        self.assertAlmostEqual(sum(first["probabilities"].values()), 1)
        self.assertEqual(first["prior_sessions"], 25)

    def test_insufficient_history_is_not_silently_simulated(self):
        with self.assertRaisesRegex(ValueError, "20 complete"):
            simulate(self.plan, self.bars[-100:], self.calendar, self.config, 10)

    def test_duplicate_csv_candle_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bars.csv"
            lines = (FIXTURE / "bars.csv").read_text().splitlines()
            path.write_text("\n".join(lines[:2] + [lines[1]]) + "\n")
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                load_bars(path)


if __name__ == "__main__":
    unittest.main()
