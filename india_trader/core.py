"""Deterministic research primitives. Money calculations use Decimal."""

import csv
import hashlib
import json
import random
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Any, Dict

IST = timezone(timedelta(hours=5, minutes=30), "IST")
D = Decimal


def number(value, positive=False) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("Boolean is not a number")
    result = D(str(value))
    if not result.is_finite() or (positive and result <= 0):
        raise ValueError("Expected a finite%s number" % (" positive" if positive else ""))
    return result


def stamp(value):
    dt = datetime.fromisoformat(iso_text(value))
    if dt.tzinfo is None:
        raise ValueError("Timestamp must include a timezone offset")
    return dt.astimezone(IST)


def iso_text(value):
    """Support broker offsets such as +0530 on Python 3.9 as well as +05:30."""
    return re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", str(value).replace("Z", "+00:00"))


def read(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, indent=2, default=str) + "\n", encoding="utf-8")
    temp.replace(path)


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def key(exchange, symbol):
    if (
        exchange not in ("NSE", "BSE")
        or not symbol
        or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789&-." for c in symbol)
    ):
        raise ValueError("Expected NSE/BSE and an exact uppercase broker symbol")
    return exchange + ":" + symbol


def session(calendar, exchange, day, instrument=None, instruments=None, broker=None):
    from .market import resolve_session

    return resolve_session(calendar, exchange, day, instrument, instruments, broker)


def load_bars(path):
    rows, seen = [], set()
    with open(path, newline="", encoding="utf-8") as handle:
        for raw in csv.DictReader(handle):
            row: Dict[str, Any] = dict(raw)
            row["key"] = key(row["exchange"], row["symbol"])
            row["timestamp"] = stamp(row["timestamp"])
            for field in ("open", "high", "low", "close", "volume"):
                row[field] = number(row[field], positive=field != "volume")
            if (
                row["volume"] < 0
                or row["low"] > min(row["open"], row["close"])
                or row["high"] < max(row["open"], row["close"])
            ):
                raise ValueError("Invalid OHLCV candle")
            identity = (row["key"], row["timestamp"])
            if identity in seen:
                raise ValueError("Duplicate candle")
            seen.add(identity)
            rows.append(row)
    return sorted(rows, key=lambda r: (r["key"], r["timestamp"]))


def closed_bars(rows, instrument, now, calendar, instruments=None, broker=None):
    from .market import bar_grid

    exchange = instrument.split(":")[0]
    s = session(calendar, exchange, now.date(), instrument, instruments, broker)
    grid = set(bar_grid(s))
    result = [
        r
        for r in rows
        if r["key"] == instrument
        and any(start <= r["timestamp"] < end for start, end in s["continuous"])
        and r["timestamp"] + timedelta(minutes=5) <= now
    ]
    for row in result:
        if row["timestamp"] not in grid:
            raise ValueError("Candles must be 5-minute bars aligned to session open")
    return result, s


def entry(rows, instrument, now, calendar, instruments=None, broker=None):
    from .market import bar_grid, instrument_on

    bars, s = closed_bars(rows, instrument, now, calendar, instruments, broker)
    opening = [r for r in bars if r["timestamp"] < s["open"] + timedelta(minutes=15)]
    if len(opening) != 3:
        return {
            "status": "waiting",
            "reason": "Need all three closed opening-range bars",
            "instrument": instrument,
        }
    top, bottom = max(r["high"] for r in opening), min(r["low"] for r in opening)
    expected = bar_grid(s)
    for index, bar in enumerate(bars):
        if index >= len(expected) or bar["timestamp"] != expected[index]:
            return {
                "status": "unavailable",
                "reason": "Missing candle in session",
                "instrument": instrument,
            }
        if bar["timestamp"] >= s["open"] + timedelta(minutes=15) and bar["close"] > top:
            at = bar["timestamp"] + timedelta(minutes=5)
            eligible = s["entry_after"] <= at <= s["entry_before"]
            result = {
                "status": "triggered" if eligible else "expired",
                "instrument": instrument,
                "entry": str(bar["close"]),
                "entry_time": at.isoformat(),
                "range_high": str(top),
                "range_low": str(bottom),
                "flat_by": s["flat_by"].isoformat(),
                "setup": "15-minute-orb",
                "session_policy_id": s["policy_id"],
                "session_status": s["policy_status"],
            }
            if instruments:
                meta = instrument_on(
                    instruments, instrument, now.date(), strict=calendar.get("schema_version") == 2
                )
                result["instrument_tick_size"] = meta["tick_size"]
            return result
    return {
        "status": "expired" if now > s["entry_before"] else "waiting",
        "instrument": instrument,
        "range_high": str(top),
        "range_low": str(bottom),
    }


def plan(signal, tick, target_r=2):
    if signal["status"] != "triggered":
        raise ValueError("A triggered entry is required")
    tick, multiple = number(tick, True), number(target_r, True)
    price = number(signal["entry"], True)
    # Floor midpoint stop and target to exact multiples, including non-decimal ticks.
    stop = (
        (number(signal["range_high"]) + number(signal["range_low"])) / 2 / tick
    ).to_integral_value(rounding=ROUND_FLOOR) * tick
    target = ((price + multiple * (price - stop)) / tick).to_integral_value(
        rounding=ROUND_FLOOR
    ) * tick
    if price % tick or not 0 < stop < price < target:
        raise ValueError("Invalid entry or tick grid")
    return dict(
        signal,
        stop=str(stop),
        target=str(target),
        tick_size=str(tick),
        target_r=str(multiple),
        side="BUY",
    )


def validate_plan(p):
    key(*p["instrument"].split(":"))
    price, stop, target, tick = (
        number(p[k], True) for k in ("entry", "stop", "target", "tick_size")
    )
    if (
        p.get("side") != "BUY"
        or not stop < price < target
        or any(v % tick for v in (price, stop, target))
    ):
        raise ValueError("Only long cash-equity plans on the instrument tick grid are supported")
    if stamp(p["flat_by"]) <= stamp(p["entry_time"]):
        raise ValueError("Flat-by must follow entry")
    return price, stop, target


def costs(config, price, qty, exit_price=None, day=None, exchange="NSE"):
    if config.get("fee_mode") == "published_snapshot":
        from .fees import roundtrip

        return number(
            roundtrip(
                config,
                price,
                price if exit_price is None else exit_price,
                qty,
                day or datetime.now(IST).date(),
                exchange,
            )["total_inr"]
        )
    return price * qty * number(config["roundtrip_cost_bps"]) / 10000 + number(
        config["fixed_roundtrip_cost_inr"]
    )


def estimated_loss(config, p, qty, price=None):
    entry_price, stop, _ = validate_plan(p)
    price = max(entry_price, number(price, True)) if price is not None else entry_price
    return qty * (price - stop + price * number(config["slippage_bps"]) / 10000) + costs(
        config, price, qty, stop, stamp(p["entry_time"]).date(), p["instrument"].split(":")[0]
    )


def validate_config(c):
    for field in (
        "capital_inr",
        "max_loss_per_trade_inr",
        "max_daily_risk_inr",
        "max_trades_per_day",
        "max_quote_age_seconds",
        "max_plan_age_seconds",
        "min_reward_risk",
    ):
        number(c[field], True)
    for field in ("max_trades_per_day", "max_quote_age_seconds", "max_plan_age_seconds"):
        if type(c[field]) is not int:
            raise ValueError(field + " must be a positive integer")
    for field in ("roundtrip_cost_bps", "fixed_roundtrip_cost_inr", "slippage_bps"):
        if number(c[field]) < 0:
            raise ValueError("Costs cannot be negative")
    if (
        not 0 < number(c["max_position_fraction"]) <= 1
        or not 0 <= number(c["cash_buffer_fraction"]) < 1
    ):
        raise ValueError("Invalid position or cash-buffer fraction")


def size(p, config, account):
    validate_config(config)
    price, stop, _ = validate_plan(p)
    if config.get("fee_mode") == "published_snapshot":
        day, exchange = stamp(p["entry_time"]).date(), p["instrument"].split(":")[0]
        capital = number(config["capital_inr"])
        cash = number(account["cash_inr"]) - capital * number(config["cash_buffer_fraction"])
        upper = int(min(cash / price, capital * number(config["max_position_fraction"]) / price))
        low, high, best = 1, upper, 0
        while low <= high:
            qty = (low + high) // 2
            reserve = max(
                costs(config, price, qty, stop, day, exchange),
                costs(config, price, qty, number(p["target"]), day, exchange),
            )
            fits = (
                estimated_loss(config, p, qty) <= number(config["max_loss_per_trade_inr"])
                and price * qty + reserve <= cash
            )
            if fits:
                best, low = qty, qty + 1
            else:
                high = qty - 1
        if not best:
            raise ValueError("Budget cannot fund one share after broker-specific fees and limits")
        return {
            "plan": p,
            "quantity": best,
            "product": "INTRADAY",
            "order_type": "LIMIT",
            "paper": True,
            "estimated_risk_inr": str(estimated_loss(config, p, best)),
            "fee_mode": "published_snapshot",
        }
    budget = number(config["max_loss_per_trade_inr"]) - number(config["fixed_roundtrip_cost_inr"])
    per_share = (
        price
        - stop
        + price * (number(config["slippage_bps"]) + number(config["roundtrip_cost_bps"])) / 10000
    )
    cash = number(account["cash_inr"])
    capital = number(config["capital_inr"])
    available = (
        cash
        - capital * number(config["cash_buffer_fraction"])
        - number(config["fixed_roundtrip_cost_inr"])
    )
    position_cap = capital * number(config["max_position_fraction"])
    qty = int(
        min(
            budget / per_share,
            available / (price * (1 + number(config["roundtrip_cost_bps"]) / 10000)),
            position_cap / price,
        ).to_integral_value(rounding=ROUND_FLOOR)
    )
    if qty < 1:
        raise ValueError("Budget cannot fund one share within limits")
    return {
        "plan": p,
        "quantity": qty,
        "product": "INTRADAY",
        "order_type": "LIMIT",
        "paper": True,
        "estimated_risk_inr": str(estimated_loss(config, p, qty)),
    }


def risk(order, config, account, quotes, calendar, now):
    validate_config(config)
    p = order["plan"]
    price, stop, target = validate_plan(p)
    qty = order["quantity"]
    if type(qty) is not int or qty < 1:
        raise ValueError("Quantity must be a positive integer")
    reasons = []
    instrument = p["instrument"]
    from .market import eligibility, instrument_on, phase_at

    try:
        metadata = instrument_on(
            config.get("instruments", {}),
            instrument,
            now.date(),
            strict=calendar.get("schema_version") == 2,
        )
    except ValueError:
        metadata = {}
    if (
        metadata.get("asset") != "EQUITY"
        or metadata.get("lot_size") != 1
        or number(metadata.get("tick_size", 0)) != number(p["tick_size"])
    ):
        reasons.append(
            "Instrument missing from verified cash-equity master, unsupported lot, or incorrect tick"
        )
    s = session(
        calendar,
        instrument.split(":")[0],
        now.date(),
        instrument,
        config.get("instruments"),
        config.get("broker"),
    )
    if calendar.get("schema_version") == 2:
        eligible = eligibility(metadata, config.get("broker"))
        if eligible["status"] != "AVAILABLE":
            reasons.extend(eligible["reasons"])
        if s["cutoff_status"] != "VERIFIED_SNAPSHOT":
            reasons.append("Broker-specific exit deadline is UNVERIFIED")
        if phase_at(s, now) != "continuous":
            reasons.append("Entry is outside continuous trading")
    if (
        order.get("paper") is not True
        or order.get("product") != "INTRADAY"
        or order.get("order_type") != "LIMIT"
    ):
        reasons.append("Only local paper intraday limit entries are enabled")
    if not s["entry_after"] <= now <= s["entry_before"]:
        reasons.append("Outside verified entry window")
    age = (now - stamp(p["entry_time"])).total_seconds()
    if not 0 <= age <= int(config["max_plan_age_seconds"]):
        reasons.append("Entry plan is stale or future-dated")
    if stamp(p["flat_by"]) != s["flat_by"]:
        reasons.append("Plan flat-by differs from verified session")
    quote = quotes.get(instrument)
    fresh = False
    if quote:
        age = (now - stamp(quote["timestamp"])).total_seconds()
        fresh = 0 <= age <= int(config["max_quote_age_seconds"])
        price = max(price, number(quote["price"], True))
        if number(quote["price"]) <= stop or number(quote["price"]) >= target:
            reasons.append("Setup already invalidated: quote at/past stop or target")
        if quote.get("bid") and quote.get("ask"):
            bid, ask = number(quote["bid"], True), number(quote["ask"], True)
            if ask < bid or (ask - bid) / price * 10000 > number(
                config.get("max_spread_bps", "20")
            ):
                reasons.append("Invalid order book or spread exceeds configured limit")
    if quote and config.get("require_broker_snapshot"):
        if (
            not quote.get("bid")
            or not quote.get("ask")
            or number(quote.get("ask_quantity") or 0) < qty
        ):
            reasons.append(
                "Connected paper entry requires a visible bid/ask and enough displayed ask quantity"
            )
        for boundary in ("lower_circuit", "upper_circuit"):
            if quote.get(boundary) is not None:
                level = number(quote[boundary])
                if level > 0 and (
                    number(quote["price"]) <= level
                    if boundary == "lower_circuit"
                    else number(quote["price"]) >= level
                ):
                    reasons.append(
                        "Quote is at or beyond a circuit limit; executable exit liquidity is unverified"
                    )
    if not fresh:
        reasons.append("Missing, future-dated or stale exchange quote")
    estimated = estimated_loss(config, p, qty, price)
    day, exchange = now.date(), instrument.split(":")[0]
    net_reward = qty * (target - price) - costs(config, price, qty, target, day, exchange)
    ratio = net_reward / estimated
    if estimated > number(config["max_loss_per_trade_inr"]):
        reasons.append("Per-trade risk exceeded")
    if ratio < number(config["min_reward_risk"]):
        reasons.append("Net reward/risk below minimum")
    entries = [r for r in account.get("trades", []) if stamp(r["timestamp"]).date() == now.date()]
    if len(entries) >= int(config["max_trades_per_day"]):
        reasons.append("Daily trade count exceeded")
    if sum((number(r["reserved_risk_inr"]) for r in entries), D(0)) + estimated > number(
        config["max_daily_risk_inr"]
    ):
        reasons.append("Daily risk budget exceeded")
    if instrument in config.get("blocked", []):
        reasons.append("Blocked instrument")
    if instrument in account.get("positions", {}) or any(
        r["instrument"] == instrument for r in entries
    ):
        reasons.append("Existing position or duplicate entry today")
    capital = number(config["capital_inr"])
    if price * qty > capital * number(config["max_position_fraction"]):
        reasons.append("Position cap exceeded")
    if number(account["cash_inr"]) - price * qty - max(
        costs(config, price, qty, stop, day, exchange),
        costs(config, price, qty, target, day, exchange),
    ) < capital * number(config["cash_buffer_fraction"]):
        reasons.append("Insufficient cash after cost reserve and buffer")
    if calendar.get("schema_version") == 2:
        if (
            now.date() - datetime.fromisoformat(s["policy_reviewed_on"]).date()
        ).days > calendar.get("review_interval_days", 7):
            reasons.append("Market policy snapshot is stale; import a reviewed update")
    if config.get("require_broker_snapshot"):
        snapshot = config.get("broker_snapshot", {})
        fresh = (
            snapshot.get("broker") == config.get("broker")
            and snapshot.get("checked_at")
            and 0 <= (now - stamp(snapshot["checked_at"])).total_seconds() <= 120
        )
        if not fresh or snapshot.get("status") != "AVAILABLE":
            reasons.append("Fresh, complete read-only broker account snapshot required")
        else:
            if instrument in snapshot.get("exposed_instruments", []):
                reasons.append(
                    "Existing broker position, holding or open order overlaps this instrument"
                )
            if price * qty + costs(config, price, qty, stop, day, exchange) > number(
                snapshot["available_cash_inr"]
            ):
                reasons.append("Proposed notional exceeds verified unleveraged broker cash")
    return {
        "status": "BLOCK" if reasons else "PASS",
        "reasons": reasons,
        "order_hash": fingerprint(order),
        "checked_at": now.isoformat(),
        "estimated_risk_inr": str(estimated),
        "net_reward_risk": str(ratio),
        "warning": "Loss estimate includes configured costs; gaps and circuit locks can cause larger losses.",
    }


def ticket(order, broker):
    p = order["plan"]
    validate_plan(p)
    exchange, symbol = p["instrument"].split(":")
    payload = {
        "exchange": exchange,
        "quantity": order["quantity"],
        "transaction_type": "BUY",
        "order_type": "LIMIT",
        "price": p["entry"],
        "validity": "DAY",
    }
    if broker == "zerodha":
        payload.update(tradingsymbol=symbol, product="MIS", tag="india" + fingerprint(order)[:12])
    elif broker == "groww":
        payload.update(
            trading_symbol=symbol,
            segment="CASH",
            product="MIS",
            order_reference_id="india" + fingerprint(order)[:12],
        )
    else:
        raise ValueError("Choose groww or zerodha")
    return {
        "broker": broker,
        "manual_entry_payload": payload,
        "stop": p["stop"],
        "target": p["target"],
        "flat_by": p["flat_by"],
        "order_hash": fingerprint(order),
        "submitted": False,
        "warning": "Entry ticket only. Stop/target are plans, not attached broker orders. Submit and manage exits manually.",
    }


def paper_fill(order, config, account, quotes, calendar, now):
    verdict = risk(order, config, account, quotes, calendar, now)
    if verdict["status"] != "PASS":
        raise ValueError("Risk BLOCK: " + "; ".join(verdict["reasons"]))
    p, qty = order["plan"], order["quantity"]
    quote = number(quotes[p["instrument"]]["price"], True)
    market_quote = quotes[p["instrument"]]
    if market_quote.get("ask"):
        quote = max(quote, number(market_quote["ask"], True))
    if market_quote.get("ask_quantity") is not None and number(market_quote["ask_quantity"]) < qty:
        raise ValueError(
            "Visible ask quantity cannot support a full assumed paper fill; no queue/partial fill is fabricated"
        )
    if quote > number(p["entry"]):
        raise ValueError("Paper buy limit not marketable at current quote; no fill")
    # Conservative fill at limit; reserve the complete estimated roundtrip costs now.
    price = number(p["entry"])
    fee = max(
        costs(config, price, qty, number(p["stop"]), now.date(), p["instrument"].split(":")[0]),
        costs(config, price, qty, number(p["target"]), now.date(), p["instrument"].split(":")[0]),
    )
    account = json.loads(json.dumps(account))
    account["cash_inr"] = str(number(account["cash_inr"]) - qty * price - fee)
    account.setdefault("positions", {})[p["instrument"]] = {
        "quantity": qty,
        "entry": str(price),
        "cost_reserve_inr": str(fee),
        "plan": p,
    }
    if config.get("fee_mode") == "published_snapshot":
        from .fees import profile_for

        account["positions"][p["instrument"]]["fee_profile"] = profile_for(
            config["broker"],
            p["instrument"].split(":")[0],
            now.date(),
            records=config.get("fee_profiles"),
        )
    account.setdefault("trades", []).append(
        {
            "instrument": p["instrument"],
            "timestamp": now.isoformat(),
            "order_hash": fingerprint(order),
            "reserved_risk_inr": verdict["estimated_risk_inr"],
            "quantity": qty,
        }
    )
    return account


def paper_close(instrument, account, quotes, now, max_age):
    position = account.get("positions", {}).get(instrument)
    if not position:
        raise ValueError("No paper position")
    quote = quotes[instrument]
    if not 0 <= (now - stamp(quote["timestamp"])).total_seconds() <= max_age:
        raise ValueError("Fresh quote required for paper close")
    price = number(quote["price"], True)
    fee = number(position["cost_reserve_inr"])
    if position.get("fee_profile"):
        from .fees import estimate

        fee = number(
            estimate(
                position["fee_profile"],
                [{"price": position["entry"], "quantity": position["quantity"]}],
                [{"price": str(price), "quantity": position["quantity"]}],
            )["total_inr"]
        )
    account = json.loads(json.dumps(account))
    account["cash_inr"] = str(
        number(account["cash_inr"])
        + price * position["quantity"]
        + number(position["cost_reserve_inr"])
        - fee
    )
    del account["positions"][instrument]
    account.setdefault("exits", []).append(
        {
            "instrument": instrument,
            "timestamp": now.isoformat(),
            "price": str(price),
            "quantity": position["quantity"],
            "fees_inr": str(fee),
            "net_pnl_inr": str((price - number(position["entry"])) * position["quantity"] - fee),
        }
    )
    return account


def path_outcome(bars, price, stop, target):
    """Open-gap first; ambiguous same-bar touches conservatively hit stop first."""
    for bar in bars:
        o, h, candle_low, c = (number(bar[k]) for k in ("open", "high", "low", "close"))
        if o <= stop:
            return "stop", o
        if o >= target:
            return "target", target
        if candle_low <= stop:
            return "stop", stop
        if h >= target:
            return "target", target
        price = c
    return "neither", price


def simulate(p, rows, calendar, config, replays=10000, seed=19):
    from .market import bar_grid, instrument_on

    price, stop, target = validate_plan(p)
    if not 1 <= replays <= 100000:
        raise ValueError("Replays must be between 1 and 100000")
    at, until = stamp(p["entry_time"]), stamp(p["flat_by"])
    instruments, broker = config.get("instruments"), config.get("broker")
    s = session(
        calendar, p["instrument"].split(":")[0], at.date(), p["instrument"], instruments, broker
    )
    if (
        not s["entry_after"] <= at <= s["entry_before"]
        or until > s["flat_by"]
        or at not in bar_grid(s)
    ):
        raise ValueError("Simulation entry must align with the verified session's five-minute grid")
    groups = defaultdict(list)
    for row in rows:
        if row["key"] == p["instrument"] and row["timestamp"].date() < at.date():
            groups[row["timestamp"].date()].append(row)
    sessions, excluded = [], []
    for day, bars in sorted(groups.items()):
        try:
            hs = session(
                calendar, p["instrument"].split(":")[0], day, p["instrument"], instruments, broker
            )
            if calendar.get("schema_version") == 2:
                instrument_on(instruments or {}, p["instrument"], day, strict=True)
        except ValueError as error:
            excluded.append({"date": str(day), "reason": str(error)})
            continue
        expected = bar_grid(hs)
        bars = [b for b in bars if b["timestamp"] in set(expected)]
        if [b["timestamp"] for b in bars] == expected:
            sessions.append(bars)
        else:
            excluded.append(
                {"date": str(day), "reason": "Incomplete continuous-session candle grid"}
            )
    sessions = sessions[-60:]
    if len(sessions) < 20:
        raise ValueError(
            "Need at least 20 complete prior sessions with verified continuous grids and historical metadata; excluded %d sessions"
            % len(excluded)
        )
    # Time-of-day bootstrap. First ratio uses that bar's open; following ratios
    # use prior close so intraday gaps persist. Entire bars retain OHLC structure.
    slots = defaultdict(list)
    for bars in sessions:
        previous = bars[0]["open"]
        for b in bars:
            slots[b["timestamp"].strftime("%H:%M")].append(
                {k: b[k] / previous for k in ("open", "high", "low", "close")}
            )
            previous = b["close"]
    times = [
        t.strftime("%H:%M") for t in bar_grid(s) if at <= t and t + timedelta(minutes=5) <= until
    ]
    if not times or any(len(slots[slot]) < 20 for slot in times):
        raise ValueError(
            "Need at least 20 prior observations at every simulated continuous-session time slot"
        )
    rng, counts, returns = random.Random(seed), defaultdict(int), []
    for _ in range(replays):
        current, generated = price, []
        for slot in times:
            ratios = rng.choice(slots[slot])
            b = {k: current * ratios[k] for k in ("open", "high", "low", "close")}
            generated.append(b)
            current = b["close"]
        outcome, exit_price = path_outcome(generated, price, stop, target)
        counts[outcome] += 1
        net = (
            exit_price
            - price
            - price
            * (number(config["roundtrip_cost_bps"]) + number(config["slippage_bps"]))
            / 10000
        )
        returns.append(float(net / (price - stop)))
    history = []
    for bars in sessions:
        end = bars[-1]["timestamp"] + timedelta(minutes=5)
        sig = entry(bars, p["instrument"], end, calendar, instruments, broker)
        if sig["status"] != "triggered":
            continue
        historic = plan(sig, sig.get("instrument_tick_size", p["tick_size"]), p["target_r"])
        hp, hs, ht = validate_plan(historic)
        future = [
            b
            for b in bars
            if stamp(historic["entry_time"]) <= b["timestamp"]
            and b["timestamp"] + timedelta(minutes=5) <= stamp(historic["flat_by"])
        ]
        outcome, exit_price = path_outcome(future, hp, hs, ht)
        history.append(
            {
                "date": str(end.date()),
                "outcome": outcome,
                "gross_r": str((exit_price - hp) / (hp - hs)),
            }
        )
    return {
        "seed": seed,
        "replays": replays,
        "prior_sessions": len(sessions),
        "excluded_sessions": excluded,
        "session_policy_id": s["policy_id"],
        "data_provenance": config.get(
            "data_label", "User-supplied bars; verify source and adjustments"
        ),
        "probabilities": {k: counts[k] / replays for k in ("target", "stop", "neither")},
        "mean_r_after_variable_costs": sum(returns) / replays,
        "historical_trades": history,
        "warning": "Resampling is not a forecast. Independent bars lose serial dependence. Fixed per-order fees excluded from per-share R; history R is gross. No corporate-action adjustment is performed.",
    }


def alerts(p, quotes, now, max_age):
    instrument = p["instrument"]
    fired = []
    if now >= stamp(p["flat_by"]):
        fired.append("FLAT_BY")
    quote = quotes.get(instrument)
    if quote and 0 <= (now - stamp(quote["timestamp"])).total_seconds() <= max_age:
        price = number(quote["price"], True)
        if price <= number(p["stop"]):
            fired.append("STOP")
        if price >= number(p["target"]):
            fired.append("TARGET")
    else:
        fired.append("DATA_STALE")
    return fired
