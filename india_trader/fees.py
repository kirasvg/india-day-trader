"""Dated fee estimates with explicit provenance and contract-note reconciliation."""

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path

from .core import number, read

PAISE = Decimal("0.01")


@lru_cache(maxsize=1)
def profiles():
    return read(Path(__file__).resolve().parent / "templates/fees.json")["profiles"]


def profile_for(broker, exchange, day, product="INTRADAY", records=None):
    matches = [
        r
        for r in (records if records is not None else profiles())
        if r["broker"] == broker
        and r["exchange"] == exchange
        and r["product"] == product
        and r["valid_from"] <= str(day) <= r["valid_to"]
    ]
    if len(matches) != 1:
        raise ValueError(
            "No unique supported fee profile for %s/%s/%s on %s; import reviewed historical fees rather than applying current rates"
            % (broker, exchange, product, day)
        )
    return matches[0]


def estimate(profile, buy_orders, sell_orders):
    """Each input is an executed order's total/average fill, not one fee per partial fill."""
    if not buy_orders or not sell_orders:
        raise ValueError("A roundtrip estimate needs buy and sell orders")
    turnover, brokerage = {"buy": Decimal(0), "sell": Decimal(0)}, Decimal(0)
    quantities = {}
    for side, orders in (("buy", buy_orders), ("sell", sell_orders)):
        total_qty = 0
        ids = set()
        for order in orders:
            qty = order["quantity"]
            if type(qty) is not int or qty < 1:
                raise ValueError("Fee quantity must be positive whole shares")
            if order.get("order_id"):
                if order["order_id"] in ids:
                    raise ValueError(
                        "Combine partial fills by order ID before estimating per-order brokerage"
                    )
                ids.add(order["order_id"])
            notional = qty * number(order["price"], True)
            turnover[side] += notional
            total_qty += qty
            raw = notional * number(profile["brokerage_rate"])
            brokerage += max(
                number(profile["brokerage_min_inr"]), min(number(profile["brokerage_cap_inr"]), raw)
            )
        quantities[side] = total_qty
    if quantities["buy"] != quantities["sell"]:
        raise ValueError("Roundtrip buy and sell quantities must match")
    both = turnover["buy"] + turnover["sell"]
    values = {
        "brokerage": brokerage,
        "exchange": both * number(profile["exchange_rate"]),
        "ipft": both * number(profile["ipft_rate"]),
        "sebi": both * number(profile["sebi_rate"]),
        "stt": turnover["sell"] * number(profile["stt_sell_rate"]),
        "stamp": turnover["buy"] * number(profile["stamp_buy_rate"]),
    }
    values["gst"] = sum((values[k] for k in profile["gst_components"]), Decimal(0)) * number(
        profile["gst_rate"]
    )
    rounded = {k: value.quantize(PAISE, rounding=ROUND_HALF_UP) for k, value in values.items()}
    total = sum(rounded.values(), Decimal(0))
    gross = turnover["sell"] - turnover["buy"]
    return {
        "profile_id": profile["id"],
        "status": profile["status"],
        "source": profile["source"],
        "reviewed_on": profile["reviewed_on"],
        "buy_notional_inr": str(turnover["buy"]),
        "sell_notional_inr": str(turnover["sell"]),
        "components_inr": {k: str(v) for k, v in rounded.items()},
        "total_inr": str(total),
        "gross_pnl_inr": str(gross),
        "net_pnl_inr": str(gross - total),
        "rounding_note": "Component-level paise estimate. Contract-note daily aggregation, statutory rounding, execution count and funding method may differ; reconcile before relying on exact totals.",
        "profile_note": profile.get("note", ""),
    }


def roundtrip(config, entry, exit_price, quantity, day, exchange="NSE"):
    record = profile_for(config["broker"], exchange, day, records=config.get("fee_profiles"))
    return estimate(
        record,
        [{"price": str(entry), "quantity": quantity}],
        [{"price": str(exit_price), "quantity": quantity}],
    )


def breakeven(profile, entry, qty, tick):
    entry, tick = number(entry, True), number(tick, True)
    if type(qty) is not int or qty < 1:
        raise ValueError("Positive integer quantity required")
    low = int((entry / tick).to_integral_value(rounding=ROUND_CEILING))
    high = int(((entry * 2 + Decimal(100) / qty) / tick).to_integral_value(rounding=ROUND_CEILING))

    def net(units):
        return number(
            estimate(
                profile,
                [{"price": str(entry), "quantity": qty}],
                [{"price": str(tick * units), "quantity": qty}],
            )["net_pnl_inr"]
        )

    if net(high) < 0:
        raise ValueError("Could not bracket a breakeven price")
    while low < high:
        middle = (low + high) // 2
        if net(middle) >= 0:
            high = middle
        else:
            low = middle + 1
    return str(tick * low)


def reconcile(record, actual_total, tolerance="0.10"):
    actual, tolerance = number(actual_total), number(tolerance)
    if actual < 0 or tolerance < 0:
        raise ValueError("Charges and tolerance cannot be negative")
    difference = number(record["total_inr"]) - actual
    return {
        "status": "MATCHED" if abs(difference) <= tolerance else "MISMATCH",
        "estimated_inr": record["total_inr"],
        "actual_inr": str(actual),
        "difference_inr": str(difference),
        "tolerance_inr": str(tolerance),
        "profile_id": record["profile_id"],
        "note": "One reconciled case does not validate every instrument, date or charge component",
    }
