"""Behavioral checks for the personal desk; all account/feed fixtures are synthetic."""

import copy
import io
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.parse import parse_qs

from india_trader import auth, desk, fees, filings, onboarding, replay, validation
from india_trader.brokers import BrokerError
from india_trader.core import load_bars, number, read, stamp, write
from india_trader.secrets import credentials
from india_trader.server import Handler
from india_trader.store import Store

NOW = stamp("2026-10-19T09:35:00+05:30")
TODAY = stamp("2026-10-30T09:35:00+05:30")


class FeeTests(unittest.TestCase):
    def profile(self, broker="zerodha"):
        return fees.profile_for(broker, "NSE", TODAY.date())

    def estimate(self, broker="zerodha", qty=100, price="1000", exit="1001"):
        return fees.estimate(
            self.profile(broker),
            [{"quantity": qty, "price": price}],
            [{"quantity": qty, "price": exit}],
        )

    def test_each_executed_order_has_brokerage_cap(self):
        self.assertEqual(self.estimate(qty=1000)["components_inr"]["brokerage"], "40.00")

    def test_groww_small_order_has_minimum_each_side(self):
        self.assertEqual(
            self.estimate("groww", 1, "100", "101")["components_inr"]["brokerage"], "10.00"
        )

    def test_sell_stt_and_buy_stamp_use_distinct_turnover(self):
        result = self.estimate()
        self.assertEqual(result["components_inr"]["stt"], "25.03")
        self.assertEqual(result["components_inr"]["stamp"], "3.00")
        self.assertEqual(number(result["net_pnl_inr"]), number("100") - number(result["total_inr"]))

    def test_partial_fills_cannot_duplicate_order_brokerage(self):
        with self.assertRaisesRegex(ValueError, "partial fills"):
            fees.estimate(
                self.profile(),
                [{"quantity": 1, "price": "100", "order_id": "a"}] * 2,
                [{"quantity": 2, "price": "100"}],
            )

    def test_roundtrip_quantities_must_match(self):
        with self.assertRaises(ValueError):
            fees.estimate(
                self.profile(), [{"quantity": 1, "price": "100"}], [{"quantity": 2, "price": "100"}]
            )

    def test_fractional_quantity_rejected(self):
        with self.assertRaises(ValueError):
            self.estimate(qty=1.5)

    def test_historic_rates_never_backfilled_from_current(self):
        for day in ("2026-10-29", "2027-01-01"):
            with self.assertRaises(ValueError):
                fees.profile_for("zerodha", "NSE", day)

    def test_bse_requires_separate_schedule(self):
        with self.assertRaises(ValueError):
            fees.profile_for("groww", "BSE", TODAY.date())

    def test_breakeven_is_smallest_profitable_tick(self):
        p = self.profile()
        price = number(fees.breakeven(p, "1000", 10, "0.10"))
        self.assertEqual(price % number("0.10"), 0)
        for value, profitable in ((price, True), (price - number(".10"), False)):
            result = fees.estimate(
                p, [{"quantity": 10, "price": "1000"}], [{"quantity": 10, "price": str(value)}]
            )
            self.assertEqual(number(result["net_pnl_inr"]) >= 0, profitable)

    def test_reconciliation_exposes_mismatch(self):
        result = self.estimate()
        self.assertEqual(fees.reconcile(result, result["total_inr"])["status"], "MATCHED")
        self.assertEqual(fees.reconcile(result, "0")["status"], "MISMATCH")


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.w = Path(self.temp.name)
        onboarding.setup(self.w, demo=True)

    def tearDown(self):
        self.temp.cleanup()

    def test_setup_never_resets_existing_account(self):
        before = (self.w / "account.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "already initialized"):
            onboarding.setup(self.w, demo=True)
        self.assertEqual((self.w / "account.json").read_bytes(), before)

    def test_connected_watchlist_requires_explicit_exchange(self):
        for value in ("INFY", "NSE:INFY,NSE:INFY", ""):
            with self.assertRaises(ValueError):
                onboarding.watchlist(value)

    def test_demo_never_syncs_or_counts_observations(self):
        client = MagicMock()
        with self.assertRaisesRegex(ValueError, "never connects"):
            onboarding.sync(self.w, NOW, client=client)
        client.assert_not_called()
        result = desk.refresh(self.w, NOW)
        store = Store(self.w)
        validation.record(
            store, result, desk.configuration(self.w), read(self.w / "calendar.json"), NOW, 30
        )
        self.assertEqual(validation.scorecard(store)["qualified_sessions"], 0)
        self.assertEqual(validation.scorecard(store)["status"], "NOT_STARTED")

    def test_doctor_labels_demo_and_never_claims_live_ready(self):
        result = onboarding.doctor(self.w, NOW)
        self.assertEqual(result["status"], "DEMO")
        self.assertFalse(result["ready_for_live_trading"])
        self.assertIn("SYNTHETIC", [c["state"] for c in result["checks"]])

    def candidate(self):
        return desk.refresh(self.w, NOW)["candidates"][0]

    def test_identical_refresh_keeps_one_immutable_plan(self):
        first = self.candidate()
        second = self.candidate()
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(Store(self.w).plans()), 1)

    def test_changed_plan_creates_new_version_and_preserves_first(self):
        first = self.candidate()
        plan = copy.deepcopy(first["plan"])
        plan["target"] = "1025"
        store = Store(self.w)
        other = store.record_plan(plan, {}, NOW.isoformat(), "SYNTHETIC")
        self.assertEqual(store.plan(other)["version"], 2)
        self.assertEqual(store.plan(first["id"])["plan"]["target"], first["plan"]["target"])

    def test_paper_track_is_idempotent_and_close_is_atomic(self):
        candidate = self.candidate()
        desk.act(self.w, "track", NOW, candidate["id"])
        store = Store(self.w)
        before = store.account()
        with self.assertRaises(ValueError):
            desk.act(self.w, "track", NOW, candidate["id"])
        self.assertEqual(store.account(), before)
        self.assertEqual(store.plan(candidate["id"])["state"], "PAPER_TRACKED")
        desk.act(self.w, "close", NOW, instrument="NSE:RELIANCE")
        self.assertEqual(store.plan(candidate["id"])["state"], "CLOSED")
        self.assertEqual(store.account()["positions"], {})
        self.assertEqual(len(store.review()["closed_trades"]), 1)

    def test_optimistic_account_update_rejects_lost_update(self):
        store = Store(self.w)
        before = store.account()
        after = dict(before, cash_inr="90000")
        store.commit_account(before, after, "TEST", NOW.isoformat())
        with self.assertRaisesRegex(ValueError, "concurrently"):
            store.commit_account(before, dict(before, cash_inr="80000"), "TEST", NOW.isoformat())
        self.assertEqual(store.account()["cash_inr"], "90000")

    def test_database_recovers_stale_json_mirror(self):
        store = Store(self.w)
        before = store.account()
        store.commit_account(before, dict(before, cash_inr="90000"), "TEST", NOW.isoformat())
        write(self.w / "account.json", before)
        self.assertEqual(store.account()["cash_inr"], "90000")

    def test_pause_blocks_new_paper_tracking(self):
        candidate = self.candidate()
        desk.act(self.w, "pause", NOW)
        with self.assertRaisesRegex(ValueError, "paused"):
            desk.act(self.w, "track", NOW, candidate["id"])
        self.assertEqual(Store(self.w).account()["positions"], {})

    def test_skip_is_preserved_after_refresh(self):
        candidate = self.candidate()
        desk.act(self.w, "skip", NOW, candidate["id"], "No liquidity")
        self.assertEqual(self.candidate()["state"], "SKIPPED")

    def test_note_is_retained_and_oversized_input_rejected(self):
        desk.act(self.w, "note", NOW, reason="Watch the spread")
        self.assertEqual(Store(self.w).review()["events"][0]["payload"]["text"], "Watch the spread")
        with self.assertRaises(ValueError):
            desk.act(self.w, "note", NOW, reason="x" * 4001)

    def test_events_deduplicate_explicit_identity(self):
        store = Store(self.w)
        for _ in range(2):
            store.event("ALERT", {"x": 1}, NOW.isoformat(), identity="same")
        self.assertEqual(len(store.review()["events"]), 1)

    def test_replay_has_chronological_holdout_and_no_current_day(self):
        result = replay.run(
            load_bars(self.w / "bars.csv"),
            "NSE:RELIANCE",
            read(self.w / "calendar.json"),
            desk.configuration(self.w),
            NOW,
        )
        self.assertEqual(result["sessions_seen"], 25)
        self.assertTrue(all(r["date"] < str(NOW.date()) for r in result["trades"]))
        self.assertIsNotNone(result["holdout_starts"])
        self.assertEqual(
            result["training"]["filled_trades"] + result["holdout"]["filled_trades"],
            result["summary"]["filled_trades"],
        )
        self.assertEqual(
            result["run_id"],
            replay.run(
                load_bars(self.w / "bars.csv"),
                "NSE:RELIANCE",
                read(self.w / "calendar.json"),
                desk.configuration(self.w),
                NOW,
            )["run_id"],
        )

    def test_replay_excludes_missing_historical_fee_profiles(self):
        config = desk.configuration(self.w)
        config["fee_mode"] = "published_snapshot"
        result = replay.run(
            load_bars(self.w / "bars.csv"),
            "NSE:RELIANCE",
            read(self.w / "calendar.json"),
            config,
            NOW,
        )
        self.assertEqual(result["summary"]["filled_trades"], 0)
        self.assertTrue(any("fee profile" in r["reason"] for r in result["excluded_sessions"]))

    def test_expired_plan_cannot_be_paper_filled(self):
        candidate = self.candidate()
        desk.refresh(self.w, NOW.replace(hour=16))
        self.assertEqual(Store(self.w).plan(candidate["id"])["state"], "EXPIRED")
        with self.assertRaises(ValueError):
            desk.act(self.w, "track", NOW.replace(hour=16), candidate["id"])


class ConnectedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.w = Path(self.temp.name)
        onboarding.setup(
            self.w, broker="groww", instruments="NSE:INFY", capital="100000", max_loss="500"
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_missing_metadata_and_snapshot_are_actionable(self):
        report = onboarding.doctor(self.w, TODAY)
        states = {r["name"]: r["state"] for r in report["checks"]}
        self.assertEqual(states["broker_account"], "MISSING")
        self.assertEqual(states["instrument:NSE:INFY"], "MISSING")
        self.assertFalse(report["ready_for_live_trading"])

    def test_account_snapshot_age_and_broker_checked(self):
        write(
            self.w / "broker-snapshot.json",
            {"status": "AVAILABLE", "broker": "groww", "checked_at": TODAY.isoformat()},
        )

        def state(now):
            return next(
                r["state"]
                for r in onboarding.doctor(self.w, now)["checks"]
                if r["name"] == "broker_account"
            )

        self.assertEqual(state(TODAY), "AVAILABLE")
        self.assertEqual(state(TODAY + timedelta(seconds=121)), "STALE")

    def test_old_metadata_does_not_prevent_refresh(self):
        write(
            self.w / "instruments.json",
            {
                "NSE:INFY": {
                    "versions": [
                        {
                            "valid_from": "2026-10-01",
                            "valid_to": "2026-10-02",
                            "observed_on": "2026-10-01",
                        }
                    ]
                }
            },
        )
        client = MagicMock()
        client.master.side_effect = BrokerError("AUTH_REQUIRED", "Expired")
        with self.assertRaises(BrokerError):
            onboarding.sync(self.w, TODAY, client=client)
        client.master.assert_called_once()

    def test_primary_broker_preserved_when_second_connected(self):
        with patch("india_trader.auth.Keychain") as keychain:
            result = auth.connect(self.w, "zerodha", prompt=lambda _: "FAKE_TEST_VALUE")
        self.assertEqual(result["status"], "STORED")
        self.assertEqual(read(self.w / "settings.json")["broker"], "groww")
        self.assertNotIn("FAKE_TEST_VALUE", (self.w / "settings.json").read_text())
        self.assertEqual(keychain.return_value.set.call_count, 2)

    def test_environment_credentials_take_precedence(self):
        with (
            patch.dict("os.environ", {"GROWW_ACCESS_TOKEN": "FAKE_TEST_TOKEN"}, clear=True),
            patch("india_trader.secrets.Keychain") as keychain,
        ):
            self.assertEqual(credentials("groww", self.w, True)["access_token"], "FAKE_TEST_TOKEN")
            keychain.return_value.get.assert_not_called()

    def test_kite_exchange_posts_only_fixed_session_endpoint_and_checksum(self):
        response = MagicMock()
        response.__enter__.return_value = io.StringIO(
            '{"status":"success","data":{"access_token":"FAKE_RESULT"}}'
        )
        with patch("india_trader.auth.build_opener") as opener:
            opener.return_value.open.return_value = response
            result = auth.exchange_kite(
                "fakekey", "fakesecret", "https://example.com/?request_token=fakerequest"
            )
        request = opener.return_value.open.call_args[0][0]
        self.assertEqual(request.full_url, "https://api.kite.trade/session/token")
        self.assertEqual(request.get_method(), "POST")
        body = parse_qs(request.data.decode())
        self.assertNotIn("fakesecret", request.data.decode())
        self.assertEqual(len(body["checksum"][0]), 64)
        self.assertEqual(result, "FAKE_RESULT")


class SourceTests(unittest.TestCase):
    def event(self):
        return {
            "title": "Synthetic results",
            "source": "Synthetic fixture",
            "url": "https://example.com/results",
            "published_at": NOW.isoformat(),
            "instrument": "NSE:INFY",
        }

    def test_source_identity_is_stable_but_revision_changes(self):
        item = self.event()
        first = filings.normalize_events([item], NOW)[0]
        self.assertEqual(first["id"], filings.normalize_events([item], NOW)[0]["id"])
        self.assertNotEqual(
            first["id"], filings.normalize_events([dict(item, revision=1)], NOW)[0]["id"]
        )
        self.assertEqual(first["evidence_status"], "SOURCE_SUPPLIED_NOT_INDEPENDENTLY_VERIFIED")

    def test_future_evidence_and_unsafe_links_rejected(self):
        for change in (
            {"published_at": (NOW + timedelta(days=1)).isoformat()},
            {"url": "javascript:alert(1)"},
            {"url": "http://example.com"},
        ):
            with self.assertRaises(ValueError):
                filings.normalize_events([dict(self.event(), **change)], NOW)

    def xml(self, start="2026-07-01", end="2026-09-30"):
        return (
            """<xbrl xmlns:i="urn:fixture"><context id="q"><period><startDate>%s</startDate><endDate>%s</endDate></period></context><unit id="inr"><measure>iso4217:INR</measure></unit><unit id="eps"><divide><unitNumerator><measure>iso4217:INR</measure></unitNumerator><unitDenominator><measure>xbrli:shares</measure></unitDenominator></divide></unit><i:RevenueFromOperations contextRef="q" unitRef="inr">1000000</i:RevenueFromOperations><i:ProfitLossForPeriod contextRef="q" unitRef="inr">100000</i:ProfitLossForPeriod><i:BasicEarningsLossPerShare contextRef="q" unitRef="eps">10</i:BasicEarningsLossPerShare></xbrl>"""
            % (start, end)
        ).encode()

    def extract(self, xml):
        return filings.extract_xbrl(
            xml, "NSE:INFY", "https://example.com/results", NOW.isoformat(), "consolidated"
        )

    def test_xbrl_preserves_units_fiscal_period_hash_and_field_evidence(self):
        row = self.extract(self.xml())[0]
        self.assertEqual(row["fiscal_quarter"], 2)
        self.assertEqual(row["fiscal_year_end"], 2027)
        self.assertEqual(row["unit"], "INR")
        self.assertEqual(row["revenue"], "1000000")
        self.assertEqual(len(row["content_sha256"]), 64)
        self.assertEqual(row["field_evidence"]["eps"]["context_ref"], "q")

    def test_cumulative_period_not_mislabeled_as_quarter(self):
        with self.assertRaises(ValueError):
            self.extract(self.xml(start="2026-04-01"))

    def test_external_entities_are_denied(self):
        with self.assertRaisesRegex(ValueError, "XML declarations"):
            self.extract(b'<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>')

    def test_missing_unit_fails_without_guessing(self):
        with self.assertRaises(ValueError):
            self.extract(self.xml().replace(b"iso4217:INR", b"unknown"))

    def test_conflicting_quarter_facts_require_review(self):
        xml = self.xml().replace(
            b"</xbrl>",
            b'<RevenueFromOperations contextRef="q" unitRef="inr">2</RevenueFromOperations></xbrl>',
        )
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            self.extract(xml)


class LocalSecurityTests(unittest.TestCase):
    def handler(self, **headers):
        h = object.__new__(Handler)
        h.server = MagicMock(server_port=8765, origin="http://127.0.0.1:8765", token="test-csrf")
        h.headers = {"Host": "127.0.0.1:8765", **headers}
        return h

    def test_loopback_host_only(self):
        self.assertTrue(self.handler().trusted())
        self.assertFalse(self.handler(Host="attacker.example:8765").trusted())
        self.assertFalse(self.handler(Host="localhost:8765").trusted())

    def test_cross_origin_and_same_site_sibling_denied(self):
        self.assertFalse(self.handler(Origin="https://example.com").trusted())
        self.assertFalse(self.handler(**{"Sec-Fetch-Site": "same-site"}).trusted())
        self.assertFalse(self.handler(**{"Sec-Fetch-Site": "cross-site"}).trusted())

    def test_mutations_require_secret_desk_token(self):
        self.assertFalse(self.handler().trusted(True))
        self.assertFalse(self.handler(**{"X-Desk-Token": "wrong"}).trusted(True))
        self.assertTrue(
            self.handler(
                **{"X-Desk-Token": "test-csrf", "Origin": "http://127.0.0.1:8765"}
            ).trusted(True)
        )


class ObservationTests(unittest.TestCase):
    def test_full_session_needs_continuous_heartbeat_and_known_coverage(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            sample = {
                "schema_version": 2,
                "market_samples": 720,
                "healthy_market_samples": 720,
                "date": "2026-10-19",
                "origin": "CONNECTED_OBSERVATION",
                "broker": "zerodha",
                "first_sample": "2026-10-19T09:15:00+05:30",
                "last_sample": "2026-10-19T15:15:00+05:30",
                "maximum_gap_seconds": 30,
                "interval_seconds": 30,
                "processing_ms": [10, 20, 30],
                "coverage": {
                    "NSE:INFY": {
                        "expected": 72,
                        "observed": 72,
                        "open": "2026-10-19T09:15:00+05:30",
                        "close": "2026-10-19T15:15:00+05:30",
                    }
                },
            }
            store.put("validation_sessions", {"2026-10-19": sample})
            self.assertEqual(validation.scorecard(store)["qualified_sessions"], 1)
            for change in (
                {"maximum_gap_seconds": 90},
                {"origin": "SYNTHETIC"},
                {"first_sample": "2026-10-19T10:00:00+05:30"},
                {
                    "coverage": {
                        "NSE:INFY": {
                            "expected": 72,
                            "observed": 60,
                            "open": "2026-10-19T09:15:00+05:30",
                            "close": "2026-10-19T15:15:00+05:30",
                        }
                    }
                },
            ):
                store.put("validation_sessions", {"2026-10-19": dict(sample, **change)})
                self.assertEqual(validation.scorecard(store)["qualified_sessions"], 0)


if __name__ == "__main__":
    unittest.main()
