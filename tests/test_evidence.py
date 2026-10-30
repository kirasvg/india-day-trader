import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from india_trader import context, observation, reconciliation, validation, verification
from india_trader.brokers import Broker, BrokerError
from india_trader.core import number, read, stamp, write
from india_trader.market import bundled_calendar
from india_trader.onboarding import setup
from india_trader.store import Store

ROOT = Path(__file__).resolve().parents[1]
NOW = stamp("2026-10-30T10:00:00+05:30")


class ReconciliationTests(unittest.TestCase):
    def note(self, broker="zerodha"):
        return read(ROOT / "examples/contract-notes" / ("synthetic-" + broker + ".json"))

    def run_note(self, note, **kwargs):
        return reconciliation.reconcile_note(note, now=NOW, **kwargs)

    def test_each_broker_groups_partial_fills_by_order(self):
        for broker in ("zerodha", "groww"):
            result = self.run_note(self.note(broker), source_bytes=b"SYNTHETIC FIXTURE")
            self.assertEqual(result["status"], "MATCHED")
            self.assertEqual(result["order_count"], 2)
            self.assertEqual(result["execution_count"], 3)
            self.assertEqual(result["evidence_origin"], "SYNTHETIC")
            self.assertEqual(len(result["source_sha256"]), 64)

    def test_balancing_component_errors_cannot_hide_in_matched_total(self):
        note = self.note()
        note["charges_inr"]["brokerage"] = str(number(note["charges_inr"]["brokerage"]) + 1)
        note["charges_inr"]["stt"] = str(number(note["charges_inr"]["stt"]) - 1)
        result = self.run_note(note)
        self.assertEqual(result["total_difference_inr"], "0.00")
        self.assertEqual(result["status"], "MISMATCH")

    def test_duplicate_trade_id_rejected(self):
        note = self.note()
        note["executions"].append(note["executions"][0])
        with self.assertRaisesRegex(ValueError, "distinct"):
            self.run_note(note)

    def test_order_id_cannot_mix_symbols(self):
        note = self.note()
        note["executions"][1]["instrument"] = "NSE:RELIANCE"
        with self.assertRaisesRegex(ValueError, "order ID"):
            self.run_note(note)

    def test_mixed_scope_missing_components_and_totals_fail(self):
        for change in (
            {"scope": "MIXED_FNO"},
            {"scope_reviewed": False},
            {"unmodeled_charges_inr": "10"},
            {"total_charges_inr": "0"},
        ):
            with self.assertRaises(ValueError):
                self.run_note(dict(self.note(), **change))
        note = self.note()
        del note["charges_inr"]["ipft"]
        with self.assertRaisesRegex(ValueError, "seven charge"):
            self.run_note(note)

    def test_unbalanced_instruments_cannot_offset_each_other(self):
        note = self.note()
        note["executions"][-1]["instrument"] = "NSE:RELIANCE"
        with self.assertRaisesRegex(ValueError, "Every instrument must balance"):
            self.run_note(note)

    def test_missing_order_ids_and_fractional_shares_fail(self):
        for field, value in (("order_id", ""), ("quantity", 1.5)):
            note = self.note()
            note["executions"][0][field] = value
            with self.assertRaises(ValueError):
                self.run_note(note)

    def test_future_or_wrong_day_executions_rejected(self):
        for timestamp in ("2026-10-30T10:01:00+05:30", "2026-10-29T09:30:00+05:30"):
            note = self.note()
            note["executions"][0]["timestamp"] = timestamp
            with self.assertRaises(ValueError):
                self.run_note(note)

    def test_current_fee_schedule_is_not_applied_to_old_note(self):
        note = self.note()
        note["date"] = "2026-10-29"
        for fill in note["executions"]:
            fill["timestamp"] = fill["timestamp"].replace("2026-10-30", "2026-10-29")
        with self.assertRaisesRegex(ValueError, "fee profile"):
            self.run_note(note)

    def test_wide_tolerance_cannot_silently_approve_charges(self):
        with self.assertRaisesRegex(ValueError, "tolerance"):
            self.run_note(self.note(), tolerance="100")

    def test_no_source_or_user_review_never_authenticates_note(self):
        note = self.note()
        note.update(origin="BROKER_CONTRACT_NOTE", source_reviewed=True)
        self.assertEqual(self.run_note(note)["evidence_origin"], "UNVERIFIED_INPUT")
        note["source_reviewed"] = False
        self.assertEqual(
            self.run_note(note, source_bytes=b"bytes")["evidence_origin"], "UNVERIFIED_INPUT"
        )

    def test_import_is_deduplicated_and_does_not_change_paper_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = Path(tmp)
            setup(w, demo=True)
            before = (w / "account.json").read_bytes()
            source = w / "source.txt"
            source.write_text("SYNTHETIC FIXTURE")
            for _ in range(2):
                result = reconciliation.import_note(w, self.note(), source)
            self.assertEqual(result["evidence_origin"], "SYNTHETIC_WORKSPACE")
            self.assertEqual(len(Store(w).get("contract_reconciliations")), 1)
            self.assertEqual((w / "account.json").read_bytes(), before)
            ready = verification.readiness(w)
            self.assertEqual(ready["contract_note_reconciliation"]["zerodha"]["matched_dates"], [])
            self.assertEqual(ready["sessions"]["qualified_sessions"], 0)


class BrokerProbeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.w = Path(self.tmp.name)
        setup(self.w, broker="groww", instruments="NSE:INFY", capital="100000", max_loss="500")
        self.client = MagicMock()
        self.client.profile.return_value = {"status": "AVAILABLE"}
        self.client.master.return_value = {
            "NSE:INFY": {"groww_symbol": "NSE-INFY", "instrument_token": "123"}
        }
        self.client.quotes.return_value = {
            "NSE:INFY": {"timestamp": NOW.isoformat(), "price": "100"}
        }
        self.client.account_snapshot.return_value = {"status": "AVAILABLE"}
        self.client.candles.return_value = [{"close": "100"}]

    def tearDown(self):
        self.tmp.cleanup()

    def test_test_doubles_never_become_authenticated_release_evidence(self):
        result = verification.validate_broker(self.w, client=self.client, now=NOW)
        self.assertEqual(result["status"], "PASSED_READ_ONLY_PROBES")
        self.assertEqual(result["origin"], "TEST_DOUBLE")
        self.assertIsNone(Store(self.w).get("broker_validation"))

    def test_entitlement_error_preserves_capability_reason(self):
        self.client.candles.side_effect = BrokerError("NOT_ENTITLED", "Not subscribed")
        result = verification.validate_broker(self.w, client=self.client, now=NOW)
        self.assertEqual(result["status"], "NEEDS_ATTENTION")
        self.assertEqual(
            next(r["status"] for r in result["checks"] if r["capability"] == "history"),
            "NOT_ENTITLED",
        )

    def test_missing_profile_does_not_download_master(self):
        self.client.profile.side_effect = BrokerError("MISSING", "Credentials absent")
        result = verification.validate_broker(self.w, client=self.client, now=NOW)
        self.client.master.assert_not_called()
        self.assertEqual(result["status"], "NEEDS_ATTENTION")

    def test_stale_quote_and_empty_history_prevent_pass(self):
        self.client.quotes.return_value["NSE:INFY"]["timestamp"] = (
            NOW - timedelta(minutes=5)
        ).isoformat()
        self.client.candles.return_value = []
        result = verification.validate_broker(self.w, client=self.client, now=NOW)
        self.assertEqual(result["status"], "NEEDS_ATTENTION")
        self.assertIn("STALE", [r["status"] for r in result["checks"]])
        self.assertIn("MISSING", [r["status"] for r in result["checks"]])

    def test_incomplete_account_shape_cannot_pass(self):
        self.client.account_snapshot.return_value = {}
        self.assertEqual(
            verification.validate_broker(self.w, client=self.client, now=NOW)["status"],
            "NEEDS_ATTENTION",
        )


class ContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.w = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def event(self):
        return {
            "title": "INFY results",
            "source": "fixture",
            "url": "https://example.com/result",
            "published_at": NOW.isoformat(),
        }

    def test_reachable_empty_feed_stays_unverified(self):
        result = context.collect(self.w, public_only=True, fetch=lambda _: [], now=NOW)
        self.assertEqual(result["status"], "PARTIAL")
        self.assertTrue(all(r["status"] == "EMPTY_UNVERIFIED" for r in result["sources"]))
        self.assertEqual(result["origin"], "TEST_DOUBLE")

    def test_source_errors_are_distinct_from_empty(self):
        def fetch(_):
            raise ValueError("Unavailable")

        result = context.collect(self.w, public_only=True, fetch=fetch, now=NOW)
        self.assertTrue(all(r["status"] == "ERROR" for r in result["sources"]))

    def test_cached_sources_are_not_polled_again_before_five_minutes(self):
        fetch = MagicMock(return_value=[self.event()])
        context.collect(self.w, public_only=True, fetch=fetch, now=NOW)
        context.collect(self.w, public_only=True, fetch=fetch, now=NOW + timedelta(seconds=30))
        self.assertEqual(fetch.call_count, len(context.SOURCES))
        context.collect(self.w, public_only=True, fetch=fetch, now=NOW + timedelta(minutes=5))
        self.assertEqual(fetch.call_count, 2 * len(context.SOURCES))

    def test_undated_or_future_publication_is_not_known_evidence(self):
        for event in (
            dict(self.event(), published_at=None),
            dict(self.event(), published_at=(NOW + timedelta(days=1)).isoformat()),
        ):
            result = context.collect(
                self.w, public_only=True, fetch=lambda _: [event], now=NOW, force=True
            )
            self.assertTrue(all(r["status"] == "UNVERIFIED" for r in result["sources"]))
            self.assertEqual(Store(self.w).filings(), [])

    def test_partly_undated_source_cannot_claim_available_coverage(self):
        rows = [self.event(), dict(self.event(), published_at=None)]
        result = context.collect(self.w, public_only=True, fetch=lambda _: rows, now=NOW)
        self.assertTrue(all(r["status"] == "PARTIAL_UNVERIFIED" for r in result["sources"]))

    def test_old_dated_items_are_stale(self):
        item = dict(self.event(), published_at=(NOW - timedelta(days=3)).isoformat())
        result = context.collect(self.w, public_only=True, fetch=lambda _: [item], now=NOW)
        self.assertTrue(all(r["status"] == "STALE" for r in result["sources"]))

    def test_watchlist_filter_does_not_hide_source_coverage(self):
        write(self.w / "config.json", {"data_mode": "CONNECTED", "watchlist": ["NSE:RELIANCE"]})
        result = context.collect(self.w, public_only=True, fetch=lambda _: [self.event()], now=NOW)
        self.assertTrue(
            all(r["input_items"] == 1 and r["matched_items"] == 0 for r in result["sources"])
        )
        self.assertTrue(all(r["status"] == "AVAILABLE" for r in result["sources"]))

    def test_stale_snapshot_is_marked_stale_independent_of_source_success(self):
        context.collect(self.w, public_only=True, fetch=lambda _: [self.event()], now=NOW)
        self.assertEqual(
            context.snapshot(Store(self.w), NOW + timedelta(minutes=11))["status"], "STALE"
        )

    def test_demo_never_contacts_sources(self):
        setup(self.w, demo=True)
        fetch = MagicMock()
        with self.assertRaisesRegex(ValueError, "never contact"):
            context.collect(self.w, public_only=True, fetch=fetch)
        fetch.assert_not_called()

    def test_provider_proxy_uses_exchange_time_and_previous_close(self):
        raw = {"last_price": 101, "last_trade_time": "2026-10-30 10:00:00", "ohlc": {"close": 100}}
        client = Broker("zerodha", lambda path, params: {params["i"]: raw})
        rows = context.broker_proxies(client, NOW)
        self.assertTrue(all(r["status"] == "AVAILABLE" and r["change_pct"] == "1.00" for r in rows))
        self.assertTrue(all(r["kind"] == "ETF_PROXY_NOT_INDEX" for r in rows))
        self.assertTrue(
            all(
                r["status"] == "STALE"
                for r in context.broker_proxies(client, NOW + timedelta(minutes=5))
            )
        )

    def test_proxy_ages_are_recomputed_at_read_time(self):
        store = Store(self.w)
        store.put(
            "context_snapshot",
            {
                "at": NOW.isoformat(),
                "status": "OBSERVED_SOURCE_COVERAGE",
                "proxies": [{"timestamp": NOW.isoformat(), "status": "AVAILABLE"}],
            },
        )
        result = context.snapshot(store, NOW + timedelta(seconds=61))
        self.assertEqual(result["status"], "PARTIAL")
        self.assertEqual(result["proxies"][0]["status"], "STALE")

    def test_missing_proxy_timestamp_never_uses_receipt_clock(self):
        client = Broker("zerodha", lambda path, params: {params["i"]: {"last_price": 100}})
        self.assertTrue(all(r["status"] == "ERROR" for r in context.broker_proxies(client, NOW)))

    def test_groww_proxy_can_use_provider_percent_without_guessing_ohlc(self):
        raw = {
            "last_price": 101,
            "last_trade_time": int(NOW.timestamp() * 1000),
            "ohlc": "unsupported string",
            "day_change_perc": "1",
        }
        rows = context.broker_proxies(Broker("groww", lambda *args: raw), NOW)
        self.assertEqual(rows[0]["change_pct"], "1.00")
        self.assertIsNone(rows[0]["previous_close_inr"])


class CampaignTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.w = Path(self.tmp.name)
        setup(self.w, broker="zerodha", instruments="NSE:INFY", capital="100000", max_loss="500")
        self.config = read(self.w / "config.json")
        self.calendar = bundled_calendar()
        self.config["instruments"] = {
            "NSE:INFY": {
                "versions": [
                    {
                        "valid_from": "2026-08-03",
                        "valid_to": None,
                        "observed_on": "2026-10-30",
                        "source": "SYNTHETIC metadata",
                        "asset": "EQUITY",
                        "lot_size": 1,
                        "tick_size": "0.05",
                        "session_class": "CAS",
                    }
                ]
            }
        }
        write(self.w / "instruments.json", self.config["instruments"])

    def tearDown(self):
        self.tmp.cleanup()

    def desk(self, now):
        return {
            "origin": "BROKER_RESEARCH",
            "processing_ms": 10,
            "broker_account": {"status": "AVAILABLE", "checked_at": now.isoformat()},
            "watchlist": [
                {
                    "instrument": "NSE:INFY",
                    "quote": {"timestamp": now.isoformat()},
                    "context": {"closed_bars": 72},
                }
            ],
        }

    def test_no_unknown_calendar_or_outside_hours_collection(self):
        self.assertEqual(observation.window(self.w, NOW)["status"], "COLLECT")
        self.assertEqual(observation.window(self.w, NOW.replace(hour=18))["status"], "WAITING")
        self.assertEqual(
            observation.window(self.w, stamp("2026-11-08T18:00:00+05:30"))["status"], "UNVERIFIED"
        )
        self.assertEqual(
            observation.window(self.w, stamp("2026-10-31T10:00:00+05:30"))["status"], "CLOSED"
        )

    def test_one_collector_lock_and_clean_release(self):
        with observation.campaign_lock(self.w):
            with self.assertRaisesRegex(ValueError, "observer lock"):
                with observation.campaign_lock(self.w):
                    pass
        self.assertFalse((self.w / ".observer.lock").exists())

    def test_demo_campaign_refused(self):
        write(self.w / "config.json", dict(self.config, data_mode="DEMO"))
        with self.assertRaisesRegex(ValueError, "connected workspace"):
            observation.run(self.w, once=True)

    def test_missing_credentials_refused_without_starting_campaign(self):
        with patch("india_trader.observation.broker_client") as factory:
            factory.return_value.headers.side_effect = BrokerError("MISSING", "Absent")
            with self.assertRaises(BrokerError):
                observation.run(self.w, once=True)
        self.assertFalse((self.w / ".observer.lock").exists())

    def test_failed_market_polls_and_stale_account_are_measured(self):
        store = Store(self.w)
        validation.record(
            store,
            self.desk(NOW),
            self.config,
            self.calendar,
            NOW,
            30,
            healthy=False,
            issue="offline",
            cycle_ms=20,
        )
        value = store.get("validation_sessions")["2026-10-30"]
        self.assertEqual(value["market_samples"], 1)
        self.assertEqual(value["healthy_market_samples"], 0)
        self.assertEqual(value["issues"][0]["detail"], "offline")
        bad = self.desk(NOW + timedelta(seconds=30))
        bad["broker_account"]["checked_at"] = (NOW - timedelta(minutes=5)).isoformat()
        validation.record(store, bad, self.config, self.calendar, NOW + timedelta(seconds=30), 30)
        self.assertEqual(
            store.get("validation_sessions")["2026-10-30"]["healthy_market_samples"], 0
        )

    def test_missing_quote_is_an_unhealthy_poll_not_an_exception(self):
        store = Store(self.w)
        observed = self.desk(NOW)
        observed["watchlist"][0]["quote"] = None
        validation.record(store, observed, self.config, self.calendar, NOW, 30)
        self.assertEqual(
            store.get("validation_sessions")["2026-10-30"]["healthy_market_samples"], 0
        )

    def test_poll_interval_change_invalidates_day(self):
        store = Store(self.w)
        validation.record(store, self.desk(NOW), self.config, self.calendar, NOW, 30)
        validation.record(
            store,
            self.desk(NOW + timedelta(seconds=30)),
            self.config,
            self.calendar,
            NOW + timedelta(seconds=30),
            300,
        )
        self.assertTrue(store.get("validation_sessions")["2026-10-30"]["configuration_changed"])

    def test_cli_campaign_does_not_hold_the_general_workspace_lock(self):
        from india_trader.cli import main

        def fake_run(*args):
            self.assertFalse((self.w / ".lock").exists())
            return {"status": "SYNTHETIC_TEST"}

        with patch("india_trader.observation.run", side_effect=fake_run), patch("builtins.print"):
            self.assertEqual(main(["--workspace", str(self.w), "observe", "run", "--once"]), 0)

    def test_evidence_clock_cannot_be_backdated_from_cli(self):
        from india_trader.cli import main

        with patch("india_trader.observation.run") as run, patch("builtins.print"):
            self.assertEqual(
                main(
                    [
                        "--workspace",
                        str(self.w),
                        "--now",
                        NOW.isoformat(),
                        "observe",
                        "run",
                        "--once",
                    ]
                ),
                1,
            )
        run.assert_not_called()

    def test_watchlist_changes_invalidate_session(self):
        store = Store(self.w)
        validation.record(store, self.desk(NOW), self.config, self.calendar, NOW, 30)
        changed = dict(self.config, watchlist=["NSE:RELIANCE"])
        validation.record(
            store,
            self.desk(NOW + timedelta(seconds=30)),
            changed,
            self.calendar,
            NOW + timedelta(seconds=30),
            30,
        )
        self.assertTrue(store.get("validation_sessions")["2026-10-30"]["configuration_changed"])
        self.assertEqual(validation.scorecard(store)["qualified_sessions"], 0)

    def test_complete_healthy_session_can_qualify_through_recorder(self):
        store = Store(self.w)
        opening = NOW.replace(hour=9, minute=15)
        for index in range(721):
            clock = opening + timedelta(seconds=index * 30)
            observed = self.desk(clock)
            observed["watchlist"][0]["context"]["closed_bars"] = index // 10
            validation.record(store, observed, self.config, self.calendar, clock, 30, cycle_ms=10)
        score = validation.scorecard(store)
        self.assertEqual(score["qualified_sessions"], 1)
        self.assertEqual(score["sessions"][0]["healthy_market_fraction"], 1)
        self.assertEqual(score["sessions"][0]["cycle_p95_ms"], 10)

    def test_legacy_records_without_health_cannot_qualify(self):
        store = Store(self.w)
        store.put(
            "validation_sessions",
            {
                "2026-10-30": {
                    "date": "2026-10-30",
                    "origin": "CONNECTED_OBSERVATION",
                    "coverage": {
                        "NSE:INFY": {
                            "expected": 72,
                            "observed": 72,
                            "open": "2026-10-30T09:15:00+05:30",
                            "close": "2026-10-30T15:15:00+05:30",
                        }
                    },
                    "first_sample": "2026-10-30T09:15:00+05:30",
                    "last_sample": "2026-10-30T15:15:00+05:30",
                    "maximum_gap_seconds": 30,
                    "interval_seconds": 30,
                }
            },
        )
        self.assertEqual(validation.scorecard(store)["qualified_sessions"], 0)


if __name__ == "__main__":
    unittest.main()
