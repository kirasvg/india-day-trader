"""Shared application workflow used by the CLI, local dashboard and collector."""

from datetime import datetime, timedelta
from decimal import Decimal
from time import monotonic
from typing import Dict

from .core import (
    IST,
    alerts,
    closed_bars,
    entry,
    fingerprint,
    load_bars,
    number,
    paper_close,
    paper_fill,
    plan,
    read,
    risk,
    size,
    stamp,
)
from .fees import breakeven, profile_for, roundtrip
from .market import eligibility, instrument_on
from .store import Store


def configuration(workspace):
    config = read(workspace / "config.json")
    config["instruments"] = read(workspace / "instruments.json")
    if (workspace / "broker-snapshot.json").exists():
        config["broker_snapshot"] = read(workspace / "broker-snapshot.json")
    return config


def context_for(rows, instrument, now, calendar=None, instruments=None, broker=None):
    try:
        today = (
            closed_bars(rows, instrument, now, calendar, instruments, broker)[0]
            if calendar
            else [
                r
                for r in rows
                if r["key"] == instrument
                and r["timestamp"].date() == now.date()
                and r["timestamp"] + timedelta(minutes=5) <= now
            ]
        )
    except ValueError:
        today = []
    volume = sum((r["volume"] for r in today), number(0))
    vwap = (
        sum(((r["high"] + r["low"] + r["close"]) / 3 * r["volume"] for r in today), number(0))
        / volume
        if volume
        else None
    )
    prior: Dict[str, Decimal] = {}
    cutoff = today[-1]["timestamp"].strftime("%H:%M") if today else "00:00"
    for row in rows:
        if (
            row["key"] == instrument
            and row["timestamp"].date() < now.date()
            and row["timestamp"].strftime("%H:%M") <= cutoff
        ):
            prior.setdefault(str(row["timestamp"].date()), number(0))
            prior[str(row["timestamp"].date())] += row["volume"]
    history = [prior[k] for k in sorted(prior)[-20:]]
    avg = sum(history, number(0)) / len(history) if len(history) >= 20 else None
    return {
        "closed_bars": len(today),
        "volume": str(volume),
        "vwap_inr": str(vwap.quantize(number("0.01"))) if vwap else None,
        "relative_volume": str((volume / avg).quantize(number("0.01"))) if avg else None,
        "relative_volume_sessions": len(history),
        "note": "Descriptive covered-data context; volume baselines may be incomplete and are not a validated prediction",
    }


def refresh(workspace, now=None):
    now = now or datetime.now(IST)
    began = monotonic()
    store = Store(workspace)
    config = configuration(workspace)
    calendar = read(workspace / "calendar.json")
    account = store.account()
    quotes = read(workspace / "quotes.json")
    bars = load_bars(workspace / "bars.csv") if (workspace / "bars.csv").exists() else []
    selected = config.get("watchlist", sorted({r["key"] for r in bars}))
    origin = (
        "SYNTHETIC"
        if config.get("data_mode") == "DEMO" or "SYNTHETIC" in config.get("data_label", "")
        else "BROKER_RESEARCH"
    )
    paused = store.get("paused", False)
    watch = []
    for instrument in selected:
        row = {
            "instrument": instrument,
            "quote": quotes.get(instrument),
            "context": context_for(
                bars, instrument, now, calendar, config["instruments"], config.get("broker")
            ),
        }
        try:
            metadata = instrument_on(
                config["instruments"],
                instrument,
                now.date(),
                strict=calendar.get("schema_version") == 2,
            )
            row["eligibility"] = eligibility(metadata, config.get("broker"))
            signal = entry(
                bars, instrument, now, calendar, config["instruments"], config.get("broker")
            )
            row["signal"] = signal
            if signal["status"] == "triggered" and not paused:
                p = plan(signal, metadata["tick_size"])
                order = size(p, config, account)
                verdict = risk(order, config, account, quotes, calendar, now)
                evidence = {
                    "order": order,
                    "risk": verdict,
                    "quote": quotes.get(instrument),
                    "context": row["context"],
                    "as_of": now.isoformat(),
                    "setup_version": "orb-midpoint-v2",
                    "disclaimer": "Rule-triggered research candidate, not a trading recommendation",
                }
                if config.get("fee_mode") == "published_snapshot":
                    profile = profile_for(
                        config["broker"],
                        instrument.split(":")[0],
                        now.date(),
                        records=config.get("fee_profiles"),
                    )
                    evidence["target_fees"] = roundtrip(
                        config,
                        p["entry"],
                        p["target"],
                        order["quantity"],
                        now.date(),
                        instrument.split(":")[0],
                    )
                    evidence["stop_fees"] = roundtrip(
                        config,
                        p["entry"],
                        p["stop"],
                        order["quantity"],
                        now.date(),
                        instrument.split(":")[0],
                    )
                    evidence["breakeven_inr"] = breakeven(
                        profile, p["entry"], order["quantity"], p["tick_size"]
                    )
                row["plan_id"] = store.record_plan(p, evidence, now.isoformat(), origin)
        except (ValueError, KeyError, ArithmeticError) as error:
            row["signal"] = {"status": "unavailable", "reason": str(error)}
        watch.append(row)
    # Plans retain their immutable inputs and user decisions; expiry is explicit.
    with store.connect() as db:
        for candidate in store.plans():
            if candidate["state"] in ("PLANNED", "SAVED") and now >= stamp(
                candidate["plan"]["flat_by"]
            ):
                db.execute(
                    "UPDATE plans SET state='EXPIRED',updated_at=? WHERE id=?",
                    (now.isoformat(), candidate["id"]),
                )
    active_alerts = []
    for instrument, position in account.get("positions", {}).items():
        for event in alerts(position["plan"], quotes, now, int(config["max_quote_age_seconds"])):
            identity = fingerprint(
                {"instrument": instrument, "plan": position["plan"], "event": event}
            )
            store.event(
                "ALERT",
                {"instrument": instrument, "event": event},
                now.isoformat(),
                origin,
                identity=identity,
            )
            active_alerts.append(
                {
                    "instrument": instrument,
                    "event": event,
                    "plan_entry_time": position["plan"]["entry_time"],
                }
            )
    from .context import snapshot as context_snapshot

    result = {
        "market_context": context_snapshot(store, now),
        "at": now.isoformat(),
        "origin": origin,
        "broker": config.get("broker", "zerodha"),
        "data_provider": config.get("data_provider", config.get("broker", "zerodha")),
        "account_source": config.get("account_source", "BROKER"),
        "paused": paused,
        "watchlist": watch,
        "candidates": store.plans()[:50],
        "alerts": active_alerts,
        "paper": {"cash_inr": account["cash_inr"], "positions": account.get("positions", {})},
        "broker_account": config.get("broker_snapshot", {"status": "UNVERIFIED"}),
        "filings": [
            r for r in store.filings() if r.get("published_at") and stamp(r["published_at"]) <= now
        ],
        "feed_health": store.get("collector", {"status": "NOT_RUNNING"}),
        "processing_ms": round((monotonic() - began) * 1000, 2),
    }
    store.put("desk_snapshot", result)
    return result


def act(workspace, action, now=None, identity=None, reason="", instrument=None):
    now = now or datetime.now(IST)
    store = Store(workspace)
    if len(reason) > 4000:
        raise ValueError("Keep notes under 4000 characters")
    if action in ("pause", "resume"):
        store.put("paused", action == "pause")
        store.event(
            "IDEAS_PAUSED" if action == "pause" else "IDEAS_RESUMED",
            {"reason": reason},
            now.isoformat(),
            "USER",
        )
        return {
            "paused": action == "pause",
            "scope": "Assistant ideas only; no broker actions and no position closure",
        }
    if action == "note":
        if not reason.strip():
            raise ValueError("Write a note first")
        store.event("NOTE", {"text": reason}, now.isoformat(), "USER", identity)
        return {"status": "SAVED"}
    if action in ("save", "skip"):
        return store.decision(identity, action, reason, now.isoformat())
    config = configuration(workspace)
    quotes = read(workspace / "quotes.json")
    before = store.account()
    if action == "close":
        if not instrument:
            raise ValueError("Choose an existing paper instrument")
        after = paper_close(instrument, before, quotes, now, int(config["max_quote_age_seconds"]))
        store.commit_account(before, after, "PAPER_CLOSE", now.isoformat())
        return {"status": "PAPER_CLOSED", "instrument": instrument}
    if action != "track":
        raise ValueError("Unsupported action")
    candidate = store.plan(identity)
    if not candidate:
        raise ValueError("Unknown plan")
    if store.get("paused", False):
        raise ValueError("Assistant ideas are paused; resume before opening a paper position")
    order = size(candidate["plan"], config, before)
    after = paper_fill(order, config, before, quotes, read(workspace / "calendar.json"), now)
    store.commit_account(before, after, "PAPER_FILL", now.isoformat(), identity)
    store.event(
        "DECISION", {"action": "paper-track", "reason": reason}, now.isoformat(), "USER", identity
    )
    return {
        "status": "PAPER_TRACKED",
        "id": identity,
        "quantity": order["quantity"],
        "submitted": False,
    }
