"""Record actual collector coverage separately from synthetic demonstrations."""

from datetime import timedelta
from math import ceil

from .core import stamp
from .market import bar_grid, resolve_session


def record(store, desk, config, calendar, now, interval, healthy=True, issue=None, cycle_ms=None):
    if desk["origin"] == "SYNTHETIC" or config.get("data_mode") != "CONNECTED":
        return
    sessions = store.get("validation_sessions", {})
    day = str(now.date())
    entry = sessions.get(
        day,
        {
            "date": day,
            "origin": "CONNECTED_OBSERVATION",
            "broker": config.get("broker"),
            "data_provider": config.get("data_provider", config.get("broker")),
            "account_source": config.get("account_source", "BROKER"),
            "first_sample": now.isoformat(),
            "samples": 0,
            "maximum_gap_seconds": 0,
            "coverage": {},
            "processing_ms": [],
        },
    )
    if entry["broker"] != config.get("broker"):
        return  # Mixed-provider sessions do not silently combine into one qualified observation.
    if entry.get("data_provider", entry["broker"]) != config.get(
        "data_provider", config.get("broker")
    ) or entry.get("account_source", "BROKER") != config.get("account_source", "BROKER"):
        entry["configuration_changed"] = True
    if entry.get("last_sample"):
        entry["maximum_gap_seconds"] = max(
            entry["maximum_gap_seconds"], (now - stamp(entry["last_sample"])).total_seconds()
        )
    if entry.get("interval_seconds", interval) != interval:
        entry["configuration_changed"] = True
    entry.update(
        last_sample=now.isoformat(),
        samples=entry["samples"] + 1,
        interval_seconds=interval,
        schema_version=2,
    )
    current_watchlist = sorted(
        config.get("watchlist", [r["instrument"] for r in desk["watchlist"]])
    )
    if entry.get("watchlist") is not None and entry["watchlist"] != current_watchlist:
        entry["configuration_changed"] = True
    entry["watchlist"] = current_watchlist
    entry["cycle_ms"] = (entry.get("cycle_ms", []) + ([cycle_ms] if cycle_ms is not None else []))[
        -5000:
    ]
    entry["issues"] = (
        entry.get("issues", []) + ([{"at": now.isoformat(), "detail": issue}] if issue else [])
    )[-100:]
    market_open = False
    entry["processing_ms"] = (entry["processing_ms"] + [desk["processing_ms"]])[-5000:]
    for row in desk["watchlist"]:
        try:
            s = resolve_session(
                calendar,
                row["instrument"].split(":")[0],
                now.date(),
                row["instrument"],
                config["instruments"],
                config.get("broker"),
            )
            expected = len(bar_grid(s))
            market_open = market_open or s["open"] <= now < s["close"]
            policies = entry.setdefault("policy_ids", {})
            if row["instrument"] in policies and policies[row["instrument"]] != s["policy_id"]:
                entry["configuration_changed"] = True
            policies[row["instrument"]] = s["policy_id"]
            entry["coverage"][row["instrument"]] = {
                "expected": expected,
                "observed": min(expected, row["context"].get("closed_bars", 0)),
                "open": s["open"].isoformat(),
                "close": s["close"].isoformat(),
            }
        except (ValueError, KeyError):
            entry["coverage"][row["instrument"]] = {"expected": None, "observed": 0}
    # A missing watchlist member cannot disappear from the denominator.
    for instrument in current_watchlist:
        if not any(r["instrument"] == instrument for r in desk["watchlist"]):
            entry["coverage"][instrument] = {"expected": None, "observed": 0}
            try:
                absent = resolve_session(
                    calendar,
                    instrument.split(":")[0],
                    now.date(),
                    instrument,
                    config["instruments"],
                    config.get("broker"),
                )
                market_open = market_open or absent["open"] <= now < absent["close"]
            except (ValueError, KeyError):
                pass
    if market_open:
        entry["market_samples"] = entry.get("market_samples", 0) + 1
        quote_ok = all(
            (r.get("quote") or {}).get("timestamp")
            and 0
            <= (now - stamp(r["quote"]["timestamp"])).total_seconds()
            <= config["max_quote_age_seconds"]
            for r in desk["watchlist"]
        )
        account = desk.get("broker_account", {})
        account_ok = (
            account.get("status") == "AVAILABLE"
            and account.get("checked_at")
            and 0 <= (now - stamp(account["checked_at"])).total_seconds() <= 120
        )
        effective = bool(healthy and quote_ok and account_ok and desk["watchlist"])
        entry["healthy_market_samples"] = entry.get("healthy_market_samples", 0) + int(effective)
    sessions[day] = entry
    store.put("validation_sessions", sessions)


def scorecard(store, target=20):
    rows = []
    for item in sorted(store.get("validation_sessions", {}).values(), key=lambda r: r["date"]):
        coverage = item["coverage"]
        known = bool(coverage) and all(c["expected"] for c in coverage.values())
        ratio = (
            sum(c["observed"] for c in coverage.values())
            / sum(c["expected"] for c in coverage.values())
            if known
            else 0
        )
        full_span = known and all(
            stamp(item["first_sample"]) <= stamp(c["open"]) + timedelta(minutes=5)
            and stamp(item["last_sample"]) >= stamp(c["close"])
            for c in coverage.values()
        )
        health_fraction = (
            item.get("healthy_market_samples", 0) / item["market_samples"]
            if item.get("market_samples")
            else 0
        )
        qualified = (
            item.get("schema_version") == 2
            and item.get("origin") == "CONNECTED_OBSERVATION"
            and ratio >= 0.99
            and full_span
            and item["maximum_gap_seconds"] <= 2 * item["interval_seconds"]
            and health_fraction >= 0.99
            and not item.get("configuration_changed", False)
        )
        delays = sorted(item.get("processing_ms", []))
        cycles = sorted(item.get("cycle_ms", []))
        rows.append(
            dict(
                item,
                coverage_fraction=ratio,
                healthy_market_fraction=health_fraction,
                qualified=bool(qualified),
                processing_p95_ms=delays[max(0, ceil(len(delays) * 0.95) - 1)] if delays else None,
                cycle_p95_ms=cycles[max(0, ceil(len(cycles) * 0.95) - 1)] if cycles else None,
                unhealthy_market_samples=item.get("market_samples", 0)
                - item.get("healthy_market_samples", 0),
            )
        )
    count = sum(int(bool(r["qualified"])) for r in rows)
    return {
        "status": "OBSERVATION_TARGET_REACHED"
        if count >= target
        else "IN_PROGRESS"
        if rows
        else "NOT_STARTED",
        "target_sessions": target,
        "qualified_sessions": count,
        "remaining_sessions": max(0, target - count),
        "sessions": rows,
        "note": "Local operational observations, not a strategy validation or tamper-proof audit. Synthetic demos never count. A session requires known coverage, near-open-to-close span, unchanged watchlist/policies, >=99% healthy market polls with fresh quotes/account snapshots, and heartbeat continuity. Legacy records without these health measurements do not qualify. Broker-account/fee reconciliation and user review remain separate release gates.",
    }
