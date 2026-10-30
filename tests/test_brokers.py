import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from india_trader.brokers import Broker, import_master, save_candles


class BrokerTests(unittest.TestCase):
    def test_kite_quote_preserves_trade_timestamp(self):
        calls = []

        def transport(path, params):
            calls.append((path, params))
            return {"NSE:INFY": {"last_price": 1500, "last_trade_time": "2026-10-19 09:35:00"}}

        result = Broker("zerodha", transport).quote("NSE", "INFY")
        self.assertEqual(calls, [("/quote", {"i": "NSE:INFY"})])
        self.assertEqual(result["NSE:INFY"]["timestamp"], "2026-10-19T09:35:00+05:30")

    def test_groww_quote_epoch_milliseconds(self):
        from india_trader.core import stamp

        milliseconds = int(stamp("2026-10-19T09:35:00+05:30").timestamp() * 1000)

        def transport(path, params):
            self.assertEqual(path, "/v1/live-data/quote")
            self.assertEqual(params["segment"], "CASH")
            return {"last_price": 1500, "last_trade_time": milliseconds}

        result = Broker("groww", transport).quote("NSE", "INFY")
        self.assertEqual(result["NSE:INFY"]["timestamp"], "2026-10-19T09:35:00+05:30")

    def test_missing_trade_timestamp_not_replaced_by_fetch_time(self):
        with self.assertRaises(ValueError):
            Broker("groww", lambda *args: {"last_price": 100}).quote("NSE", "INFY")

    def test_history_chunking_and_boundary_deduplication(self):
        calls = []

        def transport(path, params):
            calls.append((path, params))
            return {"candles": [["2026-09-30T09:15:00", 100, 102, 99, 101, 1000]]}

        with patch("india_trader.brokers.time.sleep"):
            rows = Broker("groww", transport).candles(
                "NSE",
                "INFY",
                "2026-09-01T09:15:00+05:30",
                "2026-10-15T15:30:00+05:30",
                groww_symbol="NSE-INFY",
            )
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(rows), 1)
        self.assertEqual(calls[0][1]["candle_interval"], "5minute")

    def test_kite_token_required_and_exact_endpoint(self):
        broker = Broker(
            "zerodha",
            lambda path, params: {"candles": [["2026-10-19T09:15:00+0530", 100, 102, 99, 101, 5]]},
        )
        with self.assertRaises(ValueError):
            broker.candles("NSE", "INFY", "2026-10-19T09:15:00+05:30", "2026-10-19T10:00:00+05:30")
        self.assertEqual(
            len(
                broker.candles(
                    "NSE",
                    "INFY",
                    "2026-10-19T09:15:00+05:30",
                    "2026-10-19T10:00:00+05:30",
                    instrument_token="408065",
                )
            ),
            1,
        )

    def test_credentials_only_read_from_environment(self):
        with patch.dict(os.environ, {}, clear=True):
            for name in ("groww", "zerodha"):
                with self.assertRaises(ValueError):
                    Broker(name).headers()

    def test_master_filters_derivatives_and_sme_lots(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "instruments.csv"
            path.write_text(
                "exchange,tradingsymbol,instrument_type,segment,lot_size,tick_size,instrument_token\nNSE,INFY,EQ,NSE,1,0.05,408065\nNFO,NIFTY26FUT,FUT,NFO-FUT,75,0.05,1\nNSE,SME,EQ,NSE,1000,0.05,2\n"
            )
            result = import_master(path, "zerodha")
            self.assertEqual(list(result), ["NSE:INFY"])

    def test_groww_master_filters_indices(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "instruments.csv"
            path.write_text(
                "exchange,trading_symbol,groww_symbol,instrument_type,segment,series,isin,lot_size,tick_size\nNSE,INFY,NSE-INFY,EQ,CASH,EQ,INE009A01021,1,0.05\nNSE,NIFTY,NSE-NIFTY,IDX,CASH,,,1,0.05\n"
            )
            self.assertEqual(list(import_master(path, "groww")), ["NSE:INFY"])

    def test_candle_append_retains_watchlist_and_refreshes_overlap(self):
        from india_trader.core import load_bars

        row = {
            "exchange": "NSE",
            "symbol": "INFY",
            "timestamp": "2026-10-19T09:15:00+05:30",
            "open": "100",
            "high": "102",
            "low": "99",
            "close": "101",
            "volume": "10",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bars.csv"
            save_candles(path, [row])
            updated = dict(row, close="102")
            another = dict(row, symbol="RELIANCE")
            save_candles(path, [updated, another], append=True)
            rows = load_bars(path)
            self.assertEqual(len(rows), 2)
            self.assertEqual(str(rows[0]["close"]), "102")


class AccountContractTests(unittest.TestCase):
    def test_kite_cross_exchange_exposure_and_cash_are_conservative(self):
        from india_trader.core import stamp

        data = {
            "/portfolio/holdings": [{"tradingsymbol": "INFY", "exchange": "BSE", "quantity": 1}],
            "/portfolio/positions": {"net": []},
            "/orders": [{"tradingsymbol": "RELIANCE", "status": "OPEN"}],
            "/user/margins/equity": {
                "available": {"cash": 10000, "live_balance": 9000},
                "utilised": {"debits": 1000},
            },
        }
        result = Broker("zerodha", lambda path: data[path]).account_snapshot(
            {"NSE:INFY": {}, "NSE:RELIANCE": {}}, stamp("2026-10-30T10:00:00+05:30")
        )
        self.assertEqual(result["exposed_instruments"], ["NSE:INFY", "NSE:RELIANCE"])
        self.assertEqual(result["available_cash_inr"], "8000")
        self.assertEqual(result["open_orders"], 1)

    def test_missing_account_component_does_not_imply_empty_portfolio(self):
        with self.assertRaises(KeyError):
            Broker("zerodha", lambda *args: {}).account_snapshot({})

    def test_groww_order_pagination_cannot_silently_truncate(self):
        from india_trader.brokers import BrokerError

        def transport(path, params=None):
            if path == "/v1/holdings/user":
                return {"holdings": []}
            if path == "/v1/positions/user":
                return {"positions": []}
            return {"order_list": [{"trading_symbol": "INFY", "order_status": "OPEN"}] * 100}

        with self.assertRaisesRegex(BrokerError, "pagination incomplete"):
            Broker("groww", transport).account_snapshot({})

    def test_unknown_order_status_counts_as_exposure(self):
        def transport(path, params=None):
            return {
                "/v1/holdings/user": {"holdings": []},
                "/v1/positions/user": {"positions": []},
                "/v1/order/list": {
                    "order_list": [{"trading_symbol": "INFY", "order_status": "NEW_PROVIDER_STATE"}]
                },
                "/v1/margins/detail/user": {"clear_cash": 1000},
            }[path]

        result = Broker("groww", transport).account_snapshot({"NSE:INFY": {}})
        self.assertEqual(result["exposed_instruments"], ["NSE:INFY"])

    def test_kite_quotes_use_one_batch_and_reject_missing_instrument(self):
        calls = []

        def transport(path, params):
            calls.append((path, params))
            return {"NSE:INFY": {"last_price": 100, "last_trade_time": "2026-10-30 10:00:00"}}

        from india_trader.brokers import BrokerError

        with self.assertRaises(BrokerError):
            Broker("zerodha", transport).quotes(["NSE:INFY", "NSE:RELIANCE"])
        self.assertEqual(calls, [("/quote", {"i": ["NSE:INFY", "NSE:RELIANCE"]})])


class ThreadPacingTests(unittest.TestCase):
    def test_instances_share_one_in_process_provider_pacer(self):
        import io
        import threading
        from unittest.mock import MagicMock

        from india_trader import brokers

        responses = []
        for _ in range(2):
            response = MagicMock()
            response.__enter__.return_value = io.StringIO('{"status":"SUCCESS","payload":{}}')
            responses.append(response)
        pacer = {"lock": threading.Lock(), "last": 0}
        with (
            patch.dict(brokers._PACERS, {"groww": pacer}),
            patch("india_trader.brokers.time.monotonic", return_value=10),
            patch("india_trader.brokers.time.sleep") as sleep,
            patch("india_trader.brokers.build_opener") as opener,
        ):
            opener.return_value.open.side_effect = responses
            for _ in range(2):
                Broker("groww", credentials={"access_token": "SYNTHETIC"})._get("/v1/user/detail")
            sleep.assert_called_once()
            self.assertAlmostEqual(sleep.call_args[0][0], 0.4)
