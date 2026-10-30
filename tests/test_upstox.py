"""Synthetic contract tests; never authenticated/live integration evidence."""

import copy
import tempfile
import unittest
from datetime import timedelta
from email.message import Message
from pathlib import Path
from unittest.mock import MagicMock, patch

from india_trader import auth, onboarding
from india_trader.brokers import BrokerError
from india_trader.core import entry, load_bars, plan, read, risk, size, stamp
from india_trader.manual import confirm_account
from india_trader.upstox import Upstox, normalize_master

NOW = stamp("2026-10-30T09:35:00+05:30")
TOKEN = "NSE_EQ|INE009A01021"
MASTER = [
    {
        "segment": "NSE_EQ",
        "instrument_type": "EQ",
        "security_type": "NORMAL",
        "lot_size": 1,
        "tick_size": 5,
        "trading_symbol": "INFY",
        "isin": "INE009A01021",
        "instrument_key": TOKEN,
        "cas_eligible": True,
    }
]


def quote_row():
    return {
        "instrument_token": TOKEN,
        "last_price": 1500,
        "last_trade_time": str(int(NOW.timestamp() * 1000)),
        "depth": {
            "buy": [{"price": 1499.95, "quantity": 10}],
            "sell": [{"price": 1500, "quantity": 20}],
        },
    }


class UpstoxTests(unittest.TestCase):
    def client(self, transport=None):
        return Upstox(
            transport=transport,
            instruments=normalize_master(MASTER),
            credentials={"access_token": "synthetic-not-a-real-token"},
            clock=lambda: NOW,
        )

    def test_master_paise_identity_and_explicit_classification(self):
        result = normalize_master(MASTER)["NSE:INFY"]
        self.assertEqual(result["tick_size"], "0.05")
        self.assertEqual(result["session_class"], "CAS")
        self.assertIsNone(result["intraday_allowed"])
        bad = copy.deepcopy(MASTER)
        bad[0]["instrument_key"] = "NSE_EQ|WRONG"
        with self.assertRaises(ValueError):
            normalize_master(bad)
        bad[0]["instrument_key"] = TOKEN
        bad[0].pop("cas_eligible")
        self.assertEqual(normalize_master(bad)["NSE:INFY"]["session_class"], "UNVERIFIED")

    def test_master_excludes_other_assets_and_ambiguous_symbols(self):
        for field, value in [
            ("security_type", "SME"),
            ("lot_size", 100),
            ("instrument_type", "FUT"),
        ]:
            rows = copy.deepcopy(MASTER)
            rows[0][field] = value
            with self.assertRaises(ValueError):
                normalize_master(rows)
        with self.assertRaises(ValueError):
            normalize_master(MASTER * 2)

    def test_quote_uses_instrument_identity_and_exchange_trade_clock(self):
        calls = []

        def transport(path, params):
            calls.append((path, params))
            return {"NSE_EQ:INFY": quote_row()}

        result = self.client(transport).quote("NSE", "INFY")["NSE:INFY"]
        self.assertEqual(result["timestamp"], NOW.isoformat())
        self.assertEqual(result["source"], "upstox")
        self.assertEqual(result["ask_quantity"], 20)
        self.assertEqual(calls, [("/v2/market-quote/quotes", {"instrument_key": TOKEN})])

    def test_quote_rejects_partial_wrong_identity_and_seconds_clock(self):
        for row in (
            {},
            {"x": dict(quote_row(), instrument_token="WRONG")},
            {"x": dict(quote_row(), last_trade_time=1793333100)},
        ):
            with self.assertRaises(ValueError):
                self.client(lambda *args: row).quote("NSE", "INFY")
        missing = quote_row()
        del missing["last_trade_time"]
        with self.assertRaises(KeyError):
            self.client(lambda *args: {"x": missing}).quote("NSE", "INFY")

    def test_no_account_or_order_routes_and_no_redirects(self):
        client = self.client()
        for path in (
            "/v2/order/place",
            "/v2/user/profile",
            "/v2/portfolio/holdings",
            "https://example.com",
            "/v3/historical-candle/../../orders",
        ):
            with self.assertRaises(ValueError):
                client._get(path)
        with self.assertRaises(BrokerError):
            client.account_snapshot({}, NOW)
        self.assertEqual(client.headers()["Authorization"], "Bearer synthetic-not-a-real-token")

    def test_auth_errors_redacted_fixed_origin_get(self):
        import io
        from urllib.error import HTTPError

        client = self.client()
        error = HTTPError(
            "https://api.upstox.com",
            401,
            "unauthorized",
            Message(),
            io.BytesIO(b'{"message":"synthetic-secret"}'),
        )
        opener = MagicMock()
        opener.open.side_effect = error
        with patch("india_trader.brokers.build_opener", return_value=opener):
            with self.assertRaises(BrokerError) as caught:
                client._get("/v2/market-quote/quotes", {"instrument_key": TOKEN})
        self.assertEqual(caught.exception.state, "AUTH_REQUIRED")
        self.assertNotIn("synthetic-secret", str(caught.exception))
        request = opener.open.call_args[0][0]
        self.assertEqual(request.get_method(), "GET")
        self.assertTrue(
            request.full_url.startswith("https://api.upstox.com/v2/market-quote/quotes?")
        )

    def test_candles_split_historical_and_current_day_excluding_open_bar(self):
        calls = []

        def transport(path, params):
            calls.append(path)
            day = "2026-10-30" if "/intraday/" in path else "2026-10-29"
            return {
                "candles": [
                    [day + "T09:30:00+05:30", 100, 102, 99, 101, 50],
                    [day + "T09:35:00+05:30", 101, 103, 100, 102, 60],
                ]
            }

        rows = self.client(transport).candles(
            "NSE", "INFY", "2026-10-29T00:00:00+05:30", NOW.isoformat()
        )
        self.assertEqual(len(rows), 3)
        self.assertTrue(calls[0].endswith("/2026-10-29/2026-10-29"))
        self.assertIn("/intraday/NSE_EQ%7CINE009A01021/minutes/5", calls[1])
        self.assertFalse(any(r["timestamp"] == NOW.isoformat() for r in rows))

    def test_history_is_chunked_and_conflicting_bars_rejected(self):
        calls = []

        def transport(path, params):
            calls.append(path)
            return {"candles": [["2026-09-01T09:15:00+05:30", 100, 102, 99, 101, 50]]}

        self.client(transport).candles("NSE", "INFY", "2026-09-01T00:00:00+05:30", NOW.isoformat())
        self.assertEqual(len(calls), 4)
        with self.assertRaises(ValueError):
            self.client(
                lambda *args: {
                    "candles": [
                        ["2026-10-30T09:30:00+05:30", 100, 102, 99, 101, 50],
                        ["2026-10-30T09:30:00+05:30", 100, 103, 99, 101, 50],
                    ]
                }
            ).candles("NSE", "INFY", "2026-10-30T09:00:00+05:30", NOW.isoformat())

    def setup_workspace(self, w):
        return onboarding.setup(
            w, "groww", "NSE:INFY", "100000", "500", "1500", data_provider="upstox"
        )

    def test_data_only_sync_preserves_manual_exposure_and_execution_broker(self):
        with tempfile.TemporaryDirectory() as directory:
            w = Path(directory)
            self.setup_workspace(w)
            client = self.client(lambda *args: {"NSE_EQ:INFY": quote_row()})
            client.master = lambda: normalize_master(MASTER)
            client.account_snapshot = MagicMock(
                side_effect=AssertionError("Must not fetch Upstox account")
            )
            confirmation = confirm_account(w, "50000", "BSE:INFY", NOW, True)
            client.candles = lambda *args: [
                {
                    "exchange": "NSE",
                    "symbol": "INFY",
                    "timestamp": "2026-10-30T09:30:00+05:30",
                    "open": "1490",
                    "high": "1500",
                    "low": "1480",
                    "close": "1500",
                    "volume": "100",
                }
            ]
            result = onboarding.sync(w, NOW, client=client)
            self.assertEqual(result["status"], "SYNCED")
            self.assertEqual(read(w / "broker-snapshot.json"), confirmation)
            self.assertEqual(read(w / "config.json")["broker"], "groww")
            self.assertEqual(read(w / "settings.json")["data_provider"], "upstox")
            self.assertIn("NSE:INFY", confirmation["exposed_instruments"])
            client.account_snapshot.assert_not_called()
            checks = onboarding.doctor(w, NOW, online=True, client=client)["checks"]
            self.assertEqual(next(c for c in checks if c["name"] == "login")["state"], "DATA_ONLY")
            self.assertEqual(
                next(c for c in checks if c["name"] == "broker_account")["state"], "MANUAL_ATTESTED"
            )
            later = onboarding.doctor(w, NOW + timedelta(seconds=121), client=client)["checks"]
            self.assertEqual(
                next(c for c in later if c["name"] == "broker_account")["state"], "STALE"
            )

    def test_auth_uses_hidden_prompt_without_replacing_execution_broker(self):
        with tempfile.TemporaryDirectory() as directory:
            w = Path(directory)
            self.setup_workspace(w)
            with patch("india_trader.auth.Keychain") as store:
                result = auth.connect(w, "upstox", prompt=lambda _: "synthetic-token")
                store.return_value.set.assert_called_once_with(
                    "upstox", "access_token", "synthetic-token"
                )
            self.assertEqual(result["status"], "STORED")
            self.assertNotIn("synthetic-token", str(result))
            self.assertNotIn("synthetic-token", (w / "settings.json").read_text())
            self.assertEqual(read(w / "settings.json")["broker"], "groww")

    def test_attestation_requires_review_valid_cash_and_instruments(self):
        with tempfile.TemporaryDirectory() as directory:
            w = Path(directory)
            self.setup_workspace(w)
            for cash, exposed, reviewed in [
                ("100", "", False),
                ("-1", "", True),
                ("NaN", "", True),
                ("100", "INFY", True),
            ]:
                with self.assertRaises(ValueError):
                    confirm_account(w, cash, exposed, NOW, reviewed)
            self.assertFalse((w / "broker-snapshot.json").exists())

    def test_manual_risk_rechecks_cash_overlap_and_freshness(self):
        fixture = Path(__file__).resolve().parents[1] / "india_trader/templates/demo"
        config, account, quotes, calendar = [
            read(fixture / name)
            for name in ("config.json", "account.json", "quotes.json", "calendar.json")
        ]
        at = stamp("2026-10-19T09:35:00+05:30")
        config.update(
            instruments=read(fixture / "instruments.json"),
            broker="groww",
            data_provider="upstox",
            account_source="MANUAL_ATTESTATION",
            require_broker_snapshot=True,
        )
        instrument = "NSE:RELIANCE"
        quotes[instrument].update(bid="1007.95", ask="1008", ask_quantity=1000)
        order = size(
            plan(entry(load_bars(fixture / "bars.csv"), instrument, at, calendar), "0.05"),
            config,
            account,
        )
        config["broker_snapshot"] = {
            "broker": "groww",
            "status": "MANUAL_ATTESTED",
            "source": "USER_ATTESTATION",
            "checked_at": at.isoformat(),
            "available_cash_inr": "100000",
            "exposed_instruments": [],
        }
        verdict = risk(order, config, account, quotes, calendar, at)
        self.assertEqual(verdict["status"], "PASS", verdict["reasons"])
        config["broker_snapshot"]["exposed_instruments"] = [instrument]
        self.assertTrue(
            any(
                "overlaps" in r
                for r in risk(order, config, account, quotes, calendar, at)["reasons"]
            )
        )
        config["broker_snapshot"]["exposed_instruments"] = []
        config["broker_snapshot"]["available_cash_inr"] = "1"
        self.assertTrue(
            any("cash" in r for r in risk(order, config, account, quotes, calendar, at)["reasons"])
        )
        config["broker_snapshot"]["checked_at"] = (at - timedelta(seconds=121)).isoformat()
        self.assertTrue(
            any(
                "snapshot required" in r
                for r in risk(order, config, account, quotes, calendar, at)["reasons"]
            )
        )

    def test_malformed_public_and_quote_payloads_fail_explicitly(self):
        for payload in ({}, [None], ["invalid"]):
            with self.assertRaises(ValueError):
                normalize_master(payload)
        for payload in ([], {"x": None}):
            with self.assertRaises(ValueError):
                self.client(lambda *args: payload).quote("NSE", "INFY")

    def test_public_master_reads_no_credentials(self):
        import gzip
        import json

        response = MagicMock()
        response.__enter__.return_value.read.return_value = gzip.compress(
            json.dumps(MASTER).encode()
        )
        opener = MagicMock()
        opener.open.return_value = response
        with patch("india_trader.upstox.build_opener", return_value=opener):
            self.assertIn("NSE:INFY", Upstox().master())
        request = opener.open.call_args[0][0]
        self.assertEqual(request.get_method(), "GET")
        self.assertNotIn("Authorization", dict(request.header_items()))

    def test_cli_separates_broker_from_data_provider(self):
        from india_trader.cli import parser

        args = parser().parse_args(["setup", "--broker", "groww", "--data-provider", "upstox"])
        self.assertEqual((args.broker, args.data_provider), ("groww", "upstox"))
        args = parser().parse_args(["auth", "--broker", "upstox", "--flow", "token"])
        self.assertEqual(args.broker, "upstox")

    def test_manual_form_route_preserves_provenance_and_rejects_missing_review(self):
        import os

        if os.environ.get("INDIA_TRADER_HTTP_TESTS") != "1":
            self.skipTest("Set INDIA_TRADER_HTTP_TESTS=1 for loopback socket test")
        import json
        import threading
        from http.client import HTTPConnection

        from india_trader.server import DeskServer
        from india_trader.store import Store

        with tempfile.TemporaryDirectory() as directory:
            w = Path(directory)
            self.setup_workspace(w)
            server = DeskServer(w, 0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:

                def request(payload):
                    connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                    connection.request(
                        "POST",
                        "/api/confirm-account",
                        json.dumps(payload),
                        {
                            "Content-Type": "application/json",
                            "Origin": server.origin,
                            "X-Desk-Token": server.token,
                        },
                    )
                    response = connection.getresponse()
                    body = json.loads(response.read())
                    connection.close()
                    return response.status, body

                self.assertEqual(request({"cash": "1000", "reviewed": False})[0], 400)
                status, body = request({"cash": "1000", "exposed": "BSE:INFY", "reviewed": True})
                self.assertEqual(status, 200, body)
                self.assertEqual(body["status"], "MANUAL_ATTESTED")
                self.assertEqual(body["source"], "USER_ATTESTATION")
                self.assertIn("NSE:INFY", body["exposed_instruments"])
                self.assertEqual(Store(w).get("desk_snapshot")["data_provider"], "upstox")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_interactive_setup_selects_free_data_without_credentials(self):
        answers = iter(["connected", "groww", "upstox", "NSE:INFY", "100000", "500", "1500"])
        with tempfile.TemporaryDirectory() as directory:
            w = Path(directory)
            onboarding.interactive_setup(w, ask=lambda _: next(answers))
            self.assertEqual(read(w / "settings.json")["data_provider"], "upstox")
            self.assertEqual(read(w / "config.json")["broker"], "groww")
