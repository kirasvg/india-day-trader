"""GET-only official broker data adapters; no order submission endpoints."""

import csv
import io
import json
import threading
import time
from _thread import LockType
from datetime import datetime, timedelta
from typing import Dict, TypedDict
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .core import IST, iso_text, key, load_bars, number, stamp
from .secrets import credentials as environment_credentials


class _Pacer(TypedDict):
    lock: LockType
    last: float


_PACERS: Dict[str, _Pacer] = {
    name: {"lock": threading.Lock(), "last": 0.0} for name in ("groww", "zerodha", "upstox")
}


class BrokerError(ValueError):
    def __init__(self, state, message, http_status=None):
        super().__init__(message)
        self.state, self.http_status = state, http_status


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Broker:
    def __init__(self, name, transport=None, credentials=None):
        if name not in ("groww", "zerodha", "upstox"):
            raise ValueError("Unknown broker")
        self.name = name
        self.transport = transport or self._get
        self.credentials = credentials
        self._last_request = 0

    def headers(self):
        values = (
            self.credentials if self.credentials is not None else environment_credentials(self.name)
        )
        if self.name == "zerodha":
            api_key, token = values.get("api_key"), values.get("access_token")
            if not api_key or not token:
                raise BrokerError(
                    "MISSING",
                    "Connect Zerodha with auth or set KITE_API_KEY and KITE_ACCESS_TOKEN outside chat",
                )
            return {"X-Kite-Version": "3", "Authorization": "token " + api_key + ":" + token}
        token = values.get("access_token")
        if not token:
            raise BrokerError(
                "MISSING",
                "Connect with auth or set the documented access-token environment variable outside chat",
            )
        if self.name == "upstox":
            return {"Authorization": "Bearer " + token, "Accept": "application/json"}
        return {
            "X-API-VERSION": "1.0",
            "Authorization": "Bearer " + token,
            "Accept": "application/json",
        }

    def _get(self, path, params=None):
        # Fixed origin and GET only: callers cannot redirect secrets to supplied URLs.
        base = {
            "zerodha": "https://api.kite.trade",
            "groww": "https://api.groww.in",
            "upstox": "https://api.upstox.com",
        }[self.name]
        url = base + path + ("?" + urlencode(params, doseq=True) if params else "")
        request = Request(url, headers=self.headers(), method="GET")
        for attempt in range(3):
            try:
                pacer = _PACERS[self.name]
                with pacer["lock"]:
                    delay = (1.05 if self.name == "zerodha" and path == "/quote" else 0.4) - (
                        time.monotonic() - pacer["last"]
                    )
                    if delay > 0:
                        time.sleep(delay)
                    pacer["last"] = time.monotonic()
                    self._last_request = pacer["last"]
                with build_opener(NoRedirect).open(request, timeout=25) as response:
                    body = json.load(response)
                if not isinstance(body, dict):
                    raise BrokerError("ERROR", "Unexpected broker response shape")
                expected = "SUCCESS" if self.name == "groww" else "success"
                if body.get("status") != expected:
                    raise BrokerError(
                        "ERROR",
                        "Broker returned unsuccessful response; inspect your broker dashboard",
                    )
                return body.get("payload" if self.name == "groww" else "data", {})
            except HTTPError as exc:
                if exc.code in (429, 502, 503, 504) and attempt < 2:
                    time.sleep(attempt + 1)
                    continue
                try:
                    error_body = json.loads(exc.read(16384))
                except (ValueError, OSError):
                    error_body = {}
                # Use response evidence to classify, never reflect server text/tokens into errors.
                evidence = str(error_body.get("message", "")).lower()
                state = (
                    "NOT_ENTITLED"
                    if any(w in evidence for w in ("subscription", "entitlement", "subscribe"))
                    else "AUTH_REQUIRED"
                    if exc.code in (401, 403)
                    else "RATE_LIMITED"
                    if exc.code == 429
                    else "ERROR"
                )
                raise BrokerError(
                    state,
                    "Broker HTTP %s (%s); run doctor --online for next steps" % (exc.code, state),
                    exc.code,
                ) from None
            except (URLError, TimeoutError):
                raise BrokerError(
                    "ERROR", "Broker network request failed; verify network and provider status"
                ) from None

    def profile(self):
        data = self.transport("/user/profile" if self.name == "zerodha" else "/v1/user/detail")
        if not isinstance(data, dict):
            raise BrokerError("ERROR", "Unexpected broker profile response shape")
        # Return capabilities, not the customer's name, email or account identifiers.
        return {
            "status": "AVAILABLE",
            "broker": self.name,
            "exchanges": data.get(
                "exchanges", [e for e in ("NSE", "BSE") if data.get(e.lower() + "_enabled")]
            ),
            "segments": data.get("active_segments", []),
        }

    def master(self):
        url = (
            "https://api.kite.trade/instruments"
            if self.name == "zerodha"
            else "https://growwapi-assets.groww.in/instruments/instrument.csv"
        )
        headers = (
            self.headers() if self.name == "zerodha" else {"User-Agent": "india-day-trader/0.2"}
        )
        try:
            with build_opener(NoRedirect).open(
                Request(url, headers=headers, method="GET"), timeout=30
            ) as response:
                content = response.read(50_000_001)
            if len(content) > 50_000_000:
                raise BrokerError("ERROR", "Instrument master exceeds supported size")
            return normalize_master(
                list(csv.DictReader(io.StringIO(content.decode("utf-8-sig")))),
                self.name,
                complete=True,
            )
        except HTTPError as error:
            raise BrokerError(
                "AUTH_REQUIRED" if error.code in (401, 403) else "ERROR",
                "Instrument download HTTP %d" % error.code,
            ) from None
        except (URLError, TimeoutError, UnicodeError):
            raise BrokerError("ERROR", "Unable to download broker instrument CSV") from None

    def account_snapshot(self, instruments, now=None):
        """Complete GET-only snapshot; partial results must never imply zero exposure."""
        now = now or datetime.now(IST)
        if self.name == "zerodha":
            holdings = self.transport("/portfolio/holdings")
            positions = self.transport("/portfolio/positions")["net"]
            orders = self.transport("/orders")
            margin = self.transport("/user/margins/equity")
            cash = max(
                number(0),
                min(
                    number(margin["available"]["cash"]), number(margin["available"]["live_balance"])
                )
                - max(number(0), number(margin["utilised"]["debits"])),
            )
        else:
            holdings = self.transport("/v1/holdings/user")["holdings"]
            positions = self.transport("/v1/positions/user", {"segment": "CASH"})["positions"]
            orders = []
            for page in range(100):
                batch = self.transport(
                    "/v1/order/list", {"segment": "CASH", "page": page, "page_size": 100}
                )["order_list"]
                orders.extend(batch)
                if len(batch) < 100:
                    break
            else:
                raise BrokerError(
                    "ERROR", "Order pagination incomplete; account exposure remains unverified"
                )
            cash = max(number(0), number(self.transport("/v1/margins/detail/user")["clear_cash"]))
        if not all(isinstance(v, list) for v in (holdings, positions, orders)) or any(
            not isinstance(r, dict) for group in (holdings, positions, orders) for r in group
        ):
            raise BrokerError(
                "ERROR", "Unexpected portfolio response shape; refusing an empty-account assumption"
            )

        if any("quantity" not in row for row in holdings + positions):
            raise BrokerError("ERROR", "Incomplete quantity in account exposure response")

        def symbol(row):
            return row.get("tradingsymbol", row.get("trading_symbol"))

        terminal = {"COMPLETE", "COMPLETED", "EXECUTED", "CANCELLED", "REJECTED", "FAILED"}
        active_orders = [
            r for r in orders if r.get("status", r.get("order_status", "UNKNOWN")) not in terminal
        ]
        occupied = {
            symbol(r)
            for r in holdings + positions
            if number(r.get("quantity", 0)) != 0 or number(r.get("t1_quantity", 0)) != 0
        }
        occupied.update(symbol(r) for r in active_orders)
        if None in occupied:
            raise BrokerError("ERROR", "Unidentified account exposure; inspect broker records")
        occupied_isins = {
            r.get("isin") or r.get("symbol_isin")
            for r in holdings + positions
            if number(r.get("quantity", 0)) != 0 or number(r.get("t1_quantity", 0)) != 0
        } - {None}
        from .market import instrument_on

        exposed = []
        for instrument in instruments:
            try:
                metadata = instrument_on(instruments, instrument, now.date())
            except ValueError:
                metadata = {}
            if instrument.split(":")[1] in occupied or metadata.get("isin") in occupied_isins:
                exposed.append(instrument)
        exposed.sort()
        clean_positions = [
            {
                "instrument": (r.get("exchange", "UNMAPPED") + ":" + symbol(r)),
                "quantity": str(number(r.get("quantity", 0))),
                "product": r.get("product", "HOLDING"),
                "origin": "BROKER_READ_ONLY",
            }
            for r in positions + holdings
            if symbol(r)
        ]
        return {
            "status": "AVAILABLE",
            "broker": self.name,
            "checked_at": now.isoformat(),
            "available_cash_inr": str(cash),
            "exposed_instruments": exposed,
            "positions": clean_positions,
            "open_orders": len(active_orders),
            "holdings_count": len(holdings),
            "source": "Official provider portfolio/order/margin GET endpoints",
            "cash_note": "Conservative unleveraged cash view; broker margin credit is excluded. Account is not modified or merged into the paper balance.",
        }

    def quote(self, exchange, symbol):
        instrument = key(exchange, symbol)
        if self.name == "zerodha":
            data = self.transport("/quote", {"i": instrument}).get(instrument)
            if not data or not data.get("last_trade_time"):
                raise ValueError("Missing instrument or exchange trade timestamp")
            dt = broker_stamp(data["last_trade_time"])
        else:
            data = self.transport(
                "/v1/live-data/quote",
                {"exchange": exchange, "segment": "CASH", "trading_symbol": symbol},
            )
            if not data.get("last_trade_time"):
                raise ValueError("Missing exchange trade timestamp")
            dt = datetime.fromtimestamp(float(number(data["last_trade_time"]) / 1000), IST)
        return {instrument: self._quote_record(data, dt)}

    def _quote_record(self, data, dt):
        depth = data.get("depth", {})
        bid = data.get("bid_price") or (depth.get("buy") or [{}])[0].get("price")
        ask = data.get("offer_price") or (depth.get("sell") or [{}])[0].get("price")
        quantity = data.get("offer_quantity") or (depth.get("sell") or [{}])[0].get("quantity")
        return {
            "price": str(number(data["last_price"], True)),
            "timestamp": dt.isoformat(),
            "source": self.name,
            "received_at": datetime.now(IST).isoformat(),
            "bid": str(number(bid)) if bid else None,
            "ask": str(number(ask)) if ask else None,
            "ask_quantity": quantity,
            "lower_circuit": data.get("lower_circuit_limit"),
            "upper_circuit": data.get("upper_circuit_limit"),
        }

    def quotes(self, instruments):
        if not 1 <= len(instruments) <= 50:
            raise ValueError("Choose 1..50 instruments for a personal quote batch")
        for instrument in instruments:
            key(*instrument.split(":"))
        if self.name == "zerodha":
            data = self.transport("/quote", {"i": instruments})
            result = {}
            for instrument in instruments:
                row = data.get(instrument)
                if not row or not row.get("last_trade_time"):
                    raise BrokerError(
                        "ERROR", "Incomplete quote batch; missing instrument or trade timestamp"
                    )
                result[instrument] = self._quote_record(row, broker_stamp(row["last_trade_time"]))
            return result
        result = {}
        for instrument in instruments:
            result.update(self.quote(*instrument.split(":")))
        return result

    def candles(self, exchange, symbol, start, end, instrument_token=None, groww_symbol=None):
        key(exchange, symbol)
        start, end = stamp(start), stamp(end)
        if end <= start:
            raise ValueError("End must follow start")
        if self.name == "zerodha" and (not instrument_token or not str(instrument_token).isdigit()):
            raise ValueError("Use instrument_token from today's Kite instrument master")
        if self.name == "groww" and not groww_symbol:
            raise ValueError("Use groww_symbol from today's Groww instrument master")
        # 29-day chunks fit Groww's documented 30-day five-minute request limit.
        rows = {}
        cursor = start
        while cursor < end:
            chunk_end = min(cursor + timedelta(days=29), end)
            if self.name == "zerodha":
                data = self.transport(
                    "/instruments/historical/%s/5minute" % instrument_token,
                    {
                        "from": cursor.strftime("%Y-%m-%d %H:%M:%S"),
                        "to": chunk_end.strftime("%Y-%m-%d %H:%M:%S"),
                    },
                )
            else:
                data = self.transport(
                    "/v1/historical/candles",
                    {
                        "exchange": exchange,
                        "segment": "CASH",
                        "groww_symbol": groww_symbol,
                        "start_time": cursor.strftime("%Y-%m-%d %H:%M:%S"),
                        "end_time": chunk_end.strftime("%Y-%m-%d %H:%M:%S"),
                        "candle_interval": "5minute",
                    },
                )
            for candle in data.get("candles", []):
                dt = broker_stamp(candle[0])
                if start <= dt < end:
                    row = dict(
                        zip(
                            ("open", "high", "low", "close", "volume"),
                            (str(number(v)) for v in candle[1:6]),
                        )
                    )
                    row.update(exchange=exchange, symbol=symbol, timestamp=dt.isoformat())
                    rows[dt] = row
            cursor = chunk_end
            if cursor < end:
                time.sleep(1)
        if not rows:
            raise ValueError("Broker returned no candles")
        return [rows[t] for t in sorted(rows)]


def broker_stamp(value):
    # Official broker examples omit timezone on some timestamps; these APIs use IST.
    dt = datetime.fromisoformat(iso_text(value))
    return dt.replace(tzinfo=IST) if dt.tzinfo is None else dt.astimezone(IST)


def import_master(path, broker):
    """Conservative standard-lot equity selection; SME/series restrictions need review."""
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return normalize_master(list(csv.DictReader(handle)), broker)


def normalize_master(rows, broker, complete=False):
    result = {}
    underlyings = {
        r.get("name") if broker == "zerodha" else r.get("underlying_symbol")
        for r in rows
        if r.get("instrument_type") == "FUT"
        and (
            r.get("segment", "").startswith("NFO")
            if broker == "zerodha"
            else r.get("segment") == "FNO"
        )
    }
    for row in rows:
        exchange = row.get("exchange")
        if exchange not in ("NSE", "BSE"):
            continue
        if broker == "zerodha":
            if row.get("instrument_type") != "EQ" or row.get("segment") != exchange:
                continue
            symbol = row["tradingsymbol"]
            extra = {"instrument_token": row["instrument_token"]}
        else:
            if (
                row.get("segment") != "CASH"
                or row.get("instrument_type") != "EQ"
                or not row.get("isin", "").startswith("IN")
                or row.get("series") not in ("EQ", "A", "B")
            ):
                continue
            symbol = row["trading_symbol"]
            extra = {"groww_symbol": row["groww_symbol"]}
        lot = int(row["lot_size"])
        if lot != 1:
            continue
        result[key(exchange, symbol)] = dict(
            extra,
            asset="EQUITY",
            lot_size=lot,
            tick_size=str(number(row["tick_size"], True)),
            name=row.get("name", symbol),
            isin=row.get("isin") or None,
            series=row.get("series") or None,
            session_class="CAS"
            if exchange == "NSE" and symbol in underlyings
            else "NON_CAS"
            if exchange == "NSE" and complete and underlyings
            else "UNVERIFIED",
            intraday_allowed=None,
            provider=broker,
            classification_note="Derivative-underlying membership inferred from complete current master"
            if complete
            else "Partial imports need explicit classification review",
        )
    if not result:
        raise ValueError("No supported cash equities in master")
    return result


def save_candles(path, rows, append=False):
    from pathlib import Path

    if append and Path(path).exists():
        # Validate existing data before merging; new observations replace overlap.
        old = load_bars(path)
        merged = {
            (r["exchange"], r["symbol"], r["timestamp"].isoformat()): {
                k: v for k, v in r.items() if k != "key"
            }
            for r in old
        }
        for r in rows:
            merged[(r["exchange"], r["symbol"], stamp(r["timestamp"]).isoformat())] = r
        rows = [merged[k] for k in sorted(merged)]
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    with open(temp, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                "exchange",
                "symbol",
                "timestamp",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ),
        )
        writer.writeheader()
        writer.writerows(rows)
    temp.replace(path)
