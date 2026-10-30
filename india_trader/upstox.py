"""Read-only Analytics Token data; execution broker remains independent."""

import gzip
import io
import json
import re
from datetime import datetime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, build_opener

from .brokers import Broker, BrokerError, NoRedirect
from .core import IST, key, number, stamp

MASTER_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"


def normalize_master(rows):
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
        raise ValueError("Upstox master must be a JSON array of objects")
    result = {}
    for row in rows:
        if (
            row.get("segment") != "NSE_EQ"
            or row.get("instrument_type") != "EQ"
            or row.get("security_type") != "NORMAL"
            or row.get("lot_size") != 1
        ):
            continue
        symbol, isin = row["trading_symbol"], row["isin"]
        token = row["instrument_key"]
        if not re.fullmatch(r"IN[A-Z0-9]{10}", isin) or token != "NSE_EQ|" + isin:
            raise ValueError("Invalid Upstox equity identity")
        instrument = key("NSE", symbol)
        if instrument in result:
            raise ValueError("Ambiguous Upstox symbol")
        cas = row.get("cas_eligible")
        result[instrument] = {
            "asset": "EQUITY",
            "lot_size": 1,
            "tick_size": str(number(row["tick_size"], True) / 100),
            "tick_size_unit": "INR (Upstox master paise divided by 100)",
            "name": row.get("name", symbol),
            "isin": isin,
            "series": "EQ",
            "upstox_key": token,
            "provider": "upstox",
            "intraday_allowed": None,
            "session_class": "CAS" if cas is True else "NON_CAS" if cas is False else "UNVERIFIED",
            "classification_note": "Provider cas_eligible flag; execution-broker permission requires review",
        }
    if not result:
        raise ValueError("No supported NSE normal cash equities in Upstox master")
    return result


class Upstox(Broker):
    def __init__(self, transport=None, credentials=None, instruments=None, clock=None):
        super().__init__("upstox", transport, credentials)
        self.instruments = instruments or {}
        self.clock = clock or (lambda: datetime.now(IST))

    def _get(self, path, params=None):
        if path != "/v2/market-quote/quotes" and not re.fullmatch(
            r"/v3/historical-candle/(?:intraday/)?NSE_EQ%7CIN[A-Z0-9]{10}/minutes/5(?:/\d{4}-\d{2}-\d{2}/\d{4}-\d{2}-\d{2})?",
            path,
        ):
            raise ValueError("Only allowlisted Upstox market-data GET endpoints are supported")
        data = super()._get(path, params)
        if not isinstance(data, dict):
            raise BrokerError("ERROR", "Unexpected Upstox market-data response shape")
        return data

    def profile(self):
        raise BrokerError(
            "UNSUPPORTED", "Market-data-only connection; use a quote probe, not profile"
        )

    def account_snapshot(self, instruments, now=None):
        raise BrokerError(
            "MANUAL_REQUIRED", "Groww exposure is not available from Upstox market data"
        )

    def master(self):
        try:
            with build_opener(NoRedirect).open(
                Request(MASTER_URL, method="GET"), timeout=30
            ) as response:
                compressed = response.read(20_000_001)
            if len(compressed) > 20_000_000:
                raise ValueError("Master exceeds download limit")
            with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
                raw = stream.read(80_000_001)
            if len(raw) > 80_000_000:
                raise ValueError("Master exceeds expanded size limit")
            self.instruments = normalize_master(json.loads(raw))
            return self.instruments
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, KeyError, TypeError):
            raise BrokerError(
                "ERROR", "Unable to download or validate Upstox instrument master"
            ) from None

    def instrument_key(self, instrument):
        if instrument not in self.instruments:
            raise ValueError("Run sync to load the Upstox instrument master first")
        token = self.instruments[instrument].get("upstox_key", "")
        if not re.fullmatch(r"NSE_EQ\|IN[A-Z0-9]{10}", token):
            raise ValueError("Missing or invalid Upstox instrument key")
        return token

    def quote(self, exchange, symbol):
        return self.quotes([key(exchange, symbol)])

    def quotes(self, instruments):
        if not 1 <= len(instruments) <= 50 or len(instruments) != len(set(instruments)):
            raise ValueError("Choose 1..50 distinct instruments")
        tokens = {self.instrument_key(name): name for name in instruments}
        data = self.transport("/v2/market-quote/quotes", {"instrument_key": ",".join(tokens)})
        if not isinstance(data, dict):
            raise ValueError("Upstox quotes must be an object")
        result = {}
        for row in data.values():
            if not isinstance(row, dict):
                raise ValueError("Upstox quote must be an object")
            token = row.get("instrument_token")
            if token not in tokens or tokens[token] in result:
                raise ValueError("Unexpected or duplicate Upstox quote identity")
            millis = number(row["last_trade_time"], True)
            if millis < 1_000_000_000_000:
                raise ValueError("Upstox last_trade_time must be epoch milliseconds")
            dt = datetime.fromtimestamp(float(millis / 1000), IST)
            result[tokens[token]] = self._quote_record(row, dt)
        if set(result) != set(instruments):
            raise ValueError("Incomplete Upstox quote batch")
        return result

    def candles(self, exchange, symbol, start, end, instrument_token=None, groww_symbol=None):
        token = quote(self.instrument_key(key(exchange, symbol)), safe="")
        start, end = stamp(start), stamp(end)
        if end <= start:
            raise ValueError("End must follow start")
        today = self.clock().astimezone(IST).date()
        if end.date() > today:
            raise ValueError("Cannot request future candles")
        rows, batches = {}, []
        cursor, last_prior = start.date(), min(end.date(), today - timedelta(days=1))
        while cursor <= last_prior:
            finish = min(cursor + timedelta(days=27), last_prior)
            batches.append("/v3/historical-candle/%s/minutes/5/%s/%s" % (token, finish, cursor))
            cursor = finish + timedelta(days=1)
        if end.date() == today:
            batches.append("/v3/historical-candle/intraday/%s/minutes/5" % token)
        for path in batches:
            for candle in self.transport(path, None)["candles"]:
                if not isinstance(candle, list) or len(candle) < 6:
                    raise ValueError("Malformed Upstox candle")
                dt = stamp(candle[0]).astimezone(IST)
                if start <= dt and dt + timedelta(minutes=5) <= end:
                    row = dict(
                        zip(
                            ("open", "high", "low", "close", "volume"),
                            (str(number(v)) for v in candle[1:6]),
                        )
                    )
                    row.update(exchange=exchange, symbol=symbol, timestamp=dt.isoformat())
                    if dt in rows and rows[dt] != row:
                        raise ValueError("Conflicting Upstox candle")
                    rows[dt] = row
        if not rows:
            raise ValueError("No completed candles returned for requested period")
        return [rows[t] for t in sorted(rows)]
