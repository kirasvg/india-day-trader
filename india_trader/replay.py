"""Chronological ORB research replay with causal fills and consistent costs."""

from collections import defaultdict
from datetime import timedelta

from .core import costs, entry, fingerprint, number, path_outcome, plan, size, stamp
from .market import bar_grid, instrument_on, resolve_session


def metrics(trades):
    pnl = [number(t["net_pnl_inr"]) for t in trades if t["status"] == "CLOSED"]
    equity = peak = drawdown = number(0)
    for value in pnl:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "filled_trades": len(pnl),
        "net_pnl_inr": str(sum(pnl, number(0))),
        "fees_inr": str(
            sum((number(t["fees_inr"]) for t in trades if t["status"] == "CLOSED"), number(0))
        ),
        "max_drawdown_inr": str(drawdown),
        "win_fraction": sum(p > 0 for p in pnl) / len(pnl) if pnl else None,
        "average_net_pnl_inr": str(sum(pnl, number(0)) / len(pnl)) if pnl else None,
        "sample_status": "SMALL_SAMPLE" if len(pnl) < 30 else "DESCRIPTIVE_ONLY",
    }


def run(rows, instrument, calendar, config, as_of, split_fraction="0.70"):
    fraction = number(split_fraction, True)
    if not fraction < 1:
        raise ValueError("Training split must lie strictly between zero and one")
    groups = defaultdict(list)
    for row in rows:
        if row["key"] == instrument and row["timestamp"].date() < as_of.date():
            groups[str(row["timestamp"].date())].append(row)
    days = sorted(groups)
    split = int(len(days) * fraction)
    trades, excluded = [], []
    account = {"cash_inr": config["capital_inr"], "positions": {}, "trades": []}
    for day in days:
        raw = groups[day]
        try:
            metadata = instrument_on(
                config["instruments"], instrument, day, strict=calendar.get("schema_version") == 2
            )
            if metadata.get("corporate_action_unadjusted"):
                raise ValueError("Corporate-action adjustment unavailable")
            s = resolve_session(
                calendar,
                instrument.split(":")[0],
                day,
                instrument,
                config["instruments"],
                config.get("broker"),
            )
            expected = bar_grid(s)
            bars = sorted(
                [b for b in raw if b["timestamp"] in set(expected)], key=lambda b: b["timestamp"]
            )
            if [b["timestamp"] for b in bars] != expected:
                raise ValueError("Incomplete continuous-session grid")
            signal = entry(
                bars, instrument, s["close"], calendar, config["instruments"], config.get("broker")
            )
            if signal["status"] != "triggered":
                trades.append({"date": day, "status": "NO_SIGNAL", "reason": signal["status"]})
                continue
            p = plan(signal, metadata["tick_size"], config.get("target_r", "2"))
            order = size(p, config, account)
            future = [
                b
                for b in bars
                if b["timestamp"] >= stamp(p["entry_time"])
                and b["timestamp"] + timedelta(minutes=5) <= stamp(p["flat_by"])
            ]
            # Signal-close fills are forbidden: the first executable observation is the next bar.
            if not future or not number(p["stop"]) < future[0]["open"] <= number(p["entry"]):
                trades.append(
                    {
                        "date": day,
                        "status": "NOT_FILLED",
                        "plan": p,
                        "reason": "Next-bar open did not permit a valid marketable buy limit; later touch/queue fills are not assumed",
                    }
                )
                continue
            observed = []
            for bar in future:
                observed.append(bar)
                outcome, exit_price = path_outcome(
                    observed, number(p["entry"]), number(p["stop"]), number(p["target"])
                )
                if outcome != "neither":
                    break
            if outcome != "target":
                tick = number(p["tick_size"])
                exit_price = max(
                    tick,
                    ((exit_price * (1 - number(config["slippage_bps"]) / 10000)) // tick) * tick,
                )
            qty = order["quantity"]
            fee = costs(config, number(p["entry"]), qty, exit_price, day, instrument.split(":")[0])
            gross = (exit_price - number(p["entry"])) * qty
            net = gross - fee
            account["cash_inr"] = str(number(account["cash_inr"]) + net)
            trades.append(
                {
                    "date": day,
                    "status": "CLOSED",
                    "outcome": outcome,
                    "plan": p,
                    "quantity": qty,
                    "entry_inr": p["entry"],
                    "exit_inr": str(exit_price),
                    "gross_pnl_inr": str(gross),
                    "fees_inr": str(fee),
                    "net_pnl_inr": str(net),
                    "maximum_favorable_excursion_inr": str(
                        max(b["high"] for b in observed) - number(p["entry"])
                    ),
                    "maximum_adverse_excursion_inr": str(
                        max(number(0), number(p["entry"]) - min(b["low"] for b in observed))
                    ),
                }
            )
        except (ValueError, KeyError, ArithmeticError) as error:
            excluded.append({"date": day, "reason": str(error)})
    boundary = days[split] if split < len(days) else None
    training = [r for r in trades if boundary is None or r["date"] < boundary]
    holdout = [r for r in trades if boundary is not None and r["date"] >= boundary]
    identity = fingerprint(
        {
            "rows": rows,
            "instrument": instrument,
            "calendar": calendar,
            "config": config,
            "as_of": as_of.isoformat(),
            "split": str(fraction),
            "engine": "causal-orb-v2",
        }
    )
    return {
        "run_id": identity,
        "engine": "causal-orb-v2",
        "instrument": instrument,
        "as_of": as_of.isoformat(),
        "strategy": "Frozen long ORB midpoint baseline; no parameter selection performed",
        "data_provenance": config.get(
            "data_label",
            "User-supplied broker/history data; adjustments and universe coverage need verification",
        ),
        "summary": metrics(trades),
        "training": metrics(training),
        "holdout": metrics(holdout),
        "holdout_starts": boundary,
        "sessions_seen": len(days),
        "trades": trades,
        "excluded_sessions": excluded,
        "limitations": [
            "Chronological split is descriptive and is not proof of an edge; repeated trials must be reported",
            "OHLC replay cannot prove queue fills, liquidity or execution at a locked circuit",
            "No automatic corporate-action adjustment or historical universe reconstruction",
            "Excursions include the exit bar OHLC; intra-bar order and exact tick-level excursions are unavailable",
            "Only completed sessions strictly before as_of are included; historical fee/metadata gaps are excluded",
        ],
    }
