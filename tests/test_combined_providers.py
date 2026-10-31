"""Synthetic combined-provider checks; never evidence of authenticated access."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from test_upstox import MASTER, NOW, quote_row

from india_trader import auth, onboarding
from india_trader.brokers import Broker, BrokerError
from india_trader.core import read
from india_trader.manual import confirm_account
from india_trader.secrets import credentials
from india_trader.store import Store
from india_trader.upstox import Upstox, normalize_master
from india_trader.verification import validate_broker


class CombinedProviderTests(unittest.TestCase):
    def clients(self, workspace, failure=None, symbol="INFY"):
        onboarding.setup(
            workspace,
            "groww",
            "NSE:INFY",
            "100000",
            "500",
            "1500",
            data_provider="upstox",
            account_source="broker",
        )
        calls = []

        def account_transport(path, params=None):
            calls.append(path)
            if path == failure:
                raise BrokerError("AUTH_REQUIRED", "Synthetic expired account token")
            values = {
                "/v1/user/detail": {"nse_enabled": True},
                "/v1/holdings/user": {
                    "holdings": [
                        {"trading_symbol": symbol, "isin": MASTER[0]["isin"], "quantity": 10}
                    ]
                },
                "/v1/positions/user": {"positions": []},
                "/v1/order/list": {"order_list": []},
                "/v1/margins/detail/user": {"clear_cash": "50000"},
            }
            if path not in values:
                raise AssertionError("Groww must not provide market data in this mode: " + path)
            return values[path]

        def data_transport(path, params=None):
            if path == "/v2/market-quote/quotes":
                return {"NSE_EQ:INFY": quote_row()}
            if path.startswith("/v3/historical-candle/"):
                return {"candles": [["2026-10-30T09:30:00+05:30", 1490, 1500, 1480, 1500, 100]]}
            raise AssertionError("Unexpected data endpoint: " + path)

        feed = Upstox(data_transport, instruments=normalize_master(MASTER), clock=lambda: NOW)
        feed.master = MagicMock(return_value=normalize_master(MASTER))
        account = Broker("groww", account_transport)
        return feed, account, calls

    def test_reads_groww_account_without_requesting_groww_quotes(self):
        with tempfile.TemporaryDirectory() as directory:
            w = Path(directory)
            feed, account, calls = self.clients(w)
            result = onboarding.sync(w, NOW, client=feed, account_client=account)
            self.assertEqual(result["status"], "SYNCED", result)
            snapshot = read(w / "broker-snapshot.json")
            self.assertEqual(snapshot["broker"], "groww")
            self.assertEqual(snapshot["available_cash_inr"], "50000")
            self.assertEqual(snapshot["exposed_instruments"], ["NSE:INFY"])
            self.assertEqual(read(w / "quotes.json")["NSE:INFY"]["source"], "upstox")
            self.assertEqual(read(w / "account.json")["cash_inr"], "100000")
            self.assertEqual(read(w / "config.json")["broker"], "groww")
            self.assertEqual(
                set(calls),
                {
                    "/v1/holdings/user",
                    "/v1/positions/user",
                    "/v1/order/list",
                    "/v1/margins/detail/user",
                },
            )

    def test_isin_mapping_blocks_exposure_with_different_provider_symbol(self):
        with tempfile.TemporaryDirectory() as directory:
            w = Path(directory)
            feed, account, _ = self.clients(w, symbol="PROVIDER-ALIAS")
            onboarding.sync(w, NOW, client=feed, account_client=account)
            self.assertEqual(read(w / "broker-snapshot.json")["exposed_instruments"], ["NSE:INFY"])

    def test_account_failure_invalidates_previous_snapshot_without_manual_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            w = Path(directory)
            feed, account, _ = self.clients(w)
            onboarding.sync(w, NOW, client=feed, account_client=account)
            account.transport = lambda *args: (_ for _ in ()).throw(
                BrokerError("AUTH_REQUIRED", "Synthetic expiry")
            )
            result = onboarding.sync(w, NOW, client=feed, account_client=account)
            self.assertEqual(result["status"], "PARTIAL")
            snapshot = read(w / "broker-snapshot.json")
            self.assertEqual(snapshot["status"], "AUTH_REQUIRED")
            self.assertNotIn("available_cash_inr", snapshot)
            self.assertEqual(read(w / "quotes.json")["NSE:INFY"]["source"], "upstox")
            with self.assertRaises(ValueError):
                confirm_account(w, "100000", "", NOW, True)

    def test_partial_account_read_and_wrong_broker_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            w = Path(directory)
            feed, account, _ = self.clients(w, failure="/v1/margins/detail/user")
            result = onboarding.sync(w, NOW, client=feed, account_client=account)
            self.assertEqual(result["status"], "PARTIAL")
            self.assertEqual(read(w / "broker-snapshot.json")["status"], "AUTH_REQUIRED")
            account.account_snapshot = lambda *args: {"status": "AVAILABLE", "broker": "upstox"}
            result = onboarding.sync(w, NOW, client=feed, account_client=account)
            self.assertEqual(result["status"], "PARTIAL")
            self.assertNotEqual(read(w / "broker-snapshot.json")["status"], "AVAILABLE")

    def test_online_doctor_reports_both_credentials_and_account_login(self):
        with tempfile.TemporaryDirectory() as directory:
            w = Path(directory)
            feed, account, calls = self.clients(w)
            onboarding.sync(w, NOW, client=feed, account_client=account)
            with patch(
                "india_trader.onboarding.credentials", return_value={"access_token": "synthetic"}
            ):
                report = onboarding.doctor(w, NOW, online=True, client=feed, account_client=account)
            checks = {c["name"]: c for c in report["checks"]}
            self.assertEqual(checks["account_login"]["state"], "AVAILABLE")
            self.assertEqual(checks["account_credentials"]["state"], "AVAILABLE")
            self.assertEqual(checks["broker_account"]["state"], "AVAILABLE")
            self.assertEqual(checks["login"]["state"], "DATA_ONLY")
            self.assertIn("/v1/user/detail", calls)

    def test_validation_probes_feed_and_execution_roles_without_fake_live_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            w = Path(directory)
            feed, account, _ = self.clients(w)
            result = validate_broker(w, client=account, data_client=feed, now=NOW)
            self.assertEqual(result["status"], "PASSED_READ_ONLY_PROBES", result)
            self.assertEqual(result["data_provider"], "upstox")
            self.assertEqual(result["broker"], "groww")
            self.assertEqual(result["origin"], "TEST_DOUBLE")
            self.assertFalse(Store(w).get("broker_validation", {}))

    def test_clearing_groww_does_not_disconnect_upstox_keychain_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            w = Path(directory)
            self.clients(w)
            memory = {}
            store = MagicMock()
            store.set.side_effect = lambda b, n, v: memory.__setitem__((b, n), v)
            store.get.side_effect = lambda b, n: memory.get((b, n))
            store.delete.side_effect = lambda b, n: memory.pop((b, n), None)
            with (
                patch("india_trader.auth.Keychain", return_value=store),
                patch("india_trader.secrets.Keychain", return_value=store),
                patch.dict("os.environ", {}, clear=True),
            ):
                auth.connect(w, "upstox", prompt=lambda _: "synthetic-upstox")
                auth.connect(w, "groww", prompt=lambda _: "synthetic-groww")
                auth.connect(w, "groww", clear=True)
                settings = read(w / "settings.json")
                self.assertEqual(
                    credentials("upstox", w, settings.get("credential_store") == "keychain")[
                        "access_token"
                    ],
                    "synthetic-upstox",
                )
                self.assertFalse(credentials("groww", w, True)["access_token"])
                self.assertEqual(settings["data_provider"], "upstox")
                self.assertEqual(settings["broker"], "groww")

    def test_cli_and_interactive_setup_support_account_source(self):
        from india_trader.cli import parser

        args = parser().parse_args(
            [
                "setup",
                "--broker",
                "groww",
                "--data-provider",
                "upstox",
                "--account-source",
                "broker",
            ]
        )
        self.assertEqual(args.account_source, "broker")
        answers = iter(
            ["connected", "groww", "upstox", "broker", "NSE:INFY", "100000", "500", "1500"]
        )
        with tempfile.TemporaryDirectory() as directory:
            w = Path(directory)
            onboarding.interactive_setup(w, ask=lambda _: next(answers))
            self.assertEqual(read(w / "config.json")["account_source"], "BROKER")

    def test_missing_account_token_does_not_reuse_market_data_token(self):
        with tempfile.TemporaryDirectory() as directory:
            w = Path(directory)
            feed, _, _ = self.clients(w)
            with patch(
                "india_trader.onboarding.broker_client",
                return_value=Broker("groww", credentials={}),
            ) as factory:
                result = onboarding.sync(w, NOW, client=feed)
            factory.assert_called_once_with(w, "groww")
            self.assertEqual(result["status"], "PARTIAL")
            self.assertEqual(read(w / "broker-snapshot.json")["status"], "MISSING")

    def test_missing_account_quantity_never_means_no_exposure(self):
        def transport(path, params=None):
            return {
                "/v1/holdings/user": {"holdings": [{"trading_symbol": "INFY"}]},
                "/v1/positions/user": {"positions": []},
                "/v1/order/list": {"order_list": []},
                "/v1/margins/detail/user": {"clear_cash": "50000"},
            }[path]

        with self.assertRaises(BrokerError):
            Broker("groww", transport).account_snapshot(normalize_master(MASTER), NOW)

    def test_observation_cannot_mix_account_source_roles(self):
        from datetime import timedelta

        from india_trader.validation import record

        with tempfile.TemporaryDirectory() as directory:
            w = Path(directory)
            self.clients(w)
            config = read(w / "config.json")
            state = {
                "origin": "BROKER_RESEARCH",
                "watchlist": [],
                "broker_account": {},
                "processing_ms": 0,
            }
            store = Store(w)
            record(store, state, config, read(w / "calendar.json"), NOW, 30)
            config["account_source"] = "MANUAL_ATTESTATION"
            record(store, state, config, read(w / "calendar.json"), NOW + timedelta(seconds=30), 30)
            row = store.get("validation_sessions")[str(NOW.date())]
            self.assertTrue(row["configuration_changed"])
            self.assertEqual(row["data_provider"], "upstox")

    def test_browser_setup_selects_authenticated_account_mode(self):
        import os

        if os.environ.get("INDIA_TRADER_HTTP_TESTS") != "1":
            self.skipTest("Set INDIA_TRADER_HTTP_TESTS=1 for loopback socket test")
        import json
        import threading
        from http.client import HTTPConnection

        from india_trader.server import DeskServer

        with tempfile.TemporaryDirectory() as directory:
            w = Path(directory)
            server = DeskServer(w, 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:

                def post(route, payload):
                    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                    connection.request(
                        "POST",
                        route,
                        json.dumps(payload),
                        {
                            "Content-Type": "application/json",
                            "Origin": server.origin,
                            "X-Desk-Token": server.token,
                        },
                    )
                    response = connection.getresponse()
                    status, result = response.status, json.loads(response.read())
                    connection.close()
                    return status, result

                status, result = post(
                    "/api/setup",
                    {
                        "broker": "groww",
                        "data_provider": "upstox",
                        "account_source": "broker",
                        "watchlist": "NSE:INFY",
                        "capital": "100000",
                        "max_loss": "500",
                    },
                )
                self.assertEqual(status, 200, result)
                config = read(w / "config.json")
                self.assertEqual(config["data_provider"], "upstox")
                self.assertEqual(config["account_source"], "BROKER")
                self.assertEqual(
                    post("/api/confirm-account", {"cash": "1000", "reviewed": True})[0], 400
                )
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_malformed_account_transport_response_invalidates_snapshot(self):
        import io

        with tempfile.TemporaryDirectory() as directory:
            w = Path(directory)
            feed, account, _ = self.clients(w)
            onboarding.sync(w, NOW, client=feed, account_client=account)
            broken = Broker("groww", credentials={"access_token": "synthetic"})
            response = MagicMock()
            response.__enter__.return_value = io.BytesIO(b"[]")
            opener = MagicMock()
            opener.open.return_value = response
            with patch("india_trader.brokers.build_opener", return_value=opener):
                result = onboarding.sync(w, NOW, client=feed, account_client=broken)
            self.assertEqual(result["status"], "PARTIAL")
            self.assertEqual(read(w / "broker-snapshot.json")["status"], "ERROR")
