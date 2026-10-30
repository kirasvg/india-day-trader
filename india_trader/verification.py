"""Read-only broker probes and honest release-evidence summaries."""

from datetime import datetime, timedelta
from pathlib import Path
from time import monotonic

from .auth import broker_client
from .core import IST, fingerprint, read, stamp, write
from .store import Store


def validate_broker(workspace, broker=None, client=None, now=None):
    """Only internally constructed adapters count as live evidence; injected clients are tests."""
    workspace = Path(workspace)
    config = read(workspace / "config.json")
    if config.get("data_mode") != "CONNECTED":
        raise ValueError(
            "Use a connected workspace; demonstrations cannot validate broker accounts"
        )
    broker = broker or config["broker"]
    clock = now or datetime.now(IST)
    origin = "TEST_DOUBLE" if client is not None or now is not None else "BROKER_LIVE_READ_ONLY"
    client = client or broker_client(workspace, broker)
    checks = []

    def probe(name, operation):
        started = monotonic()
        try:
            value = operation()
            checks.append(
                {
                    "capability": name,
                    "status": "AVAILABLE",
                    "latency_ms": round((monotonic() - started) * 1000, 2),
                }
            )
            return value
        except (ValueError, KeyError, OSError, ArithmeticError) as error:
            checks.append(
                {
                    "capability": name,
                    "status": getattr(error, "state", "ERROR"),
                    "detail": str(error),
                    "latency_ms": round((monotonic() - started) * 1000, 2),
                }
            )
            return None

    profile = probe("profile", client.profile)
    master = probe("instrument_master", client.master) if profile is not None else None
    if master is None and profile is None:
        checks.append(
            {
                "capability": "instrument_master",
                "status": "UNVERIFIED",
                "detail": "Authenticate before downloading the account instrument universe",
            }
        )
    selected = config["watchlist"][:2]
    quotes = probe("quote_batch", lambda: client.quotes(selected))
    if quotes is not None:
        for name in selected:
            row = quotes.get(name, {})
            age = (
                (
                    (clock if now is not None else datetime.now(IST)) - stamp(row["timestamp"])
                ).total_seconds()
                if row.get("timestamp")
                else None
            )
            checks.append(
                {
                    "capability": "quote_clock:" + name,
                    "status": "AVAILABLE"
                    if age is not None and 0 <= age <= config["max_quote_age_seconds"]
                    else "STALE",
                    "exchange_trade_age_seconds": age,
                }
            )
    snapshot = probe(
        "complete_account_snapshot", lambda: client.account_snapshot(master or {}, clock)
    )
    if master is not None:
        name = selected[0]
        meta = master.get(name)
        if not meta:
            checks.append(
                {
                    "capability": "history",
                    "status": "MISSING",
                    "detail": "Watchlist symbol absent from this broker master",
                }
            )
        else:
            # A completed prior weekday supplies a small bounded entitlement probe, not a reliability test.
            start = (clock - timedelta(days=7)).replace(hour=9, minute=15, second=0, microsecond=0)
            rows = probe(
                "history",
                lambda: client.candles(
                    *name.split(":"),
                    start.isoformat(),
                    clock.isoformat(),
                    meta.get("instrument_token"),
                    meta.get("groww_symbol"),
                ),
            )
            if rows is not None and not rows:
                checks[-1].update(status="MISSING", detail="History response contained no candles")
    else:
        checks.append(
            {
                "capability": "history",
                "status": "UNVERIFIED",
                "detail": "Instrument master is required for provider history identity",
            }
        )
    success = all(c["status"] == "AVAILABLE" for c in checks)
    result = {
        "schema_version": 1,
        "broker": broker,
        "origin": origin,
        "checked_at": clock.isoformat(),
        "status": "PASSED_READ_ONLY_PROBES" if success else "NEEDS_ATTENTION",
        "checks": checks,
        "summary": {
            "master_instruments": len(master or {}),
            "quotes_returned": len(quotes or {}),
            "account_snapshot_complete": bool(snapshot and snapshot.get("status") == "AVAILABLE"),
        },
        "note": "No orders submitted. One successful probe is time-bounded integration evidence; subscriptions, daily login and session reliability remain separate. Reports omit tokens, customer identity and portfolio details.",
    }
    # Reject malformed custom adapter success rather than reporting a complete account by inference.
    if not result["summary"]["account_snapshot_complete"]:
        result["status"] = "NEEDS_ATTENTION"
    if now is None:
        result["checked_at"] = datetime.now(IST).isoformat()
    identity = fingerprint(result)
    result["report_id"] = identity
    if origin == "BROKER_LIVE_READ_ONLY":
        write(workspace / "evidence" / ("broker-" + broker + "-" + identity[:16] + ".json"), result)
        store = Store(workspace)
        reports = store.get("broker_validation", {})
        reports[broker] = result
        store.put("broker_validation", reports)
        store.event("BROKER_VALIDATION", result, clock.isoformat(), origin, identity=identity)
    return result


def readiness(workspace):
    from .validation import scorecard

    store = Store(workspace)
    reports = store.get("broker_validation", {})
    broker_rows = {
        broker: {
            "status": "OBSERVED"
            if reports.get(broker, {}).get("status") == "PASSED_READ_ONLY_PROBES"
            and reports[broker].get("origin") == "BROKER_LIVE_READ_ONLY"
            else "MISSING_EVIDENCE",
            "checked_at": reports.get(broker, {}).get("checked_at"),
        }
        for broker in ("groww", "zerodha")
    }
    notes = store.get("contract_reconciliations", [])
    note_rows = {
        broker: {
            "matched_dates": sorted(
                {
                    r["date"]
                    for r in notes
                    if r["broker"] == broker
                    and r.get("evidence_origin") == "USER_REVIEWED_CONTRACT_NOTE"
                    and r["status"] == "MATCHED"
                    and r.get("source_sha256")
                }
            ),
            "mismatched_notes": sum(
                r["broker"] == broker and r["status"] == "MISMATCH" for r in notes
            ),
        }
        for broker in ("groww", "zerodha")
    }
    for row in note_rows.values():
        row["status"] = (
            "OBSERVED"
            if len(row["matched_dates"]) >= 3 and row["mismatched_notes"] == 0
            else "NEEDS_EVIDENCE"
        )
    from .context import snapshot

    context = snapshot(store)
    observed = scorecard(store)
    return {
        "broker_validation": broker_rows,
        "contract_note_reconciliation": note_rows,
        "context": {
            "status": context.get("status", "NOT_COLLECTED"),
            "collected_at": context.get("at"),
            "coverage_claim": "Source-specific observations, never a complete-market guarantee",
        },
        "sessions": observed,
        "status": "EVIDENCE_COLLECTED_REVIEW_REQUIRED"
        if all(r["status"] == "OBSERVED" for r in broker_rows.values())
        and all(r["status"] == "OBSERVED" for r in note_rows.values())
        and observed["qualified_sessions"] >= 20
        and context.get("status") == "OBSERVED_SOURCE_COVERAGE"
        and context.get("origin") == "PUBLIC_AND_BROKER"
        else "GATES_OPEN",
        "note": "No automatic production certification. Review three distinct dated complete notes per provider, component differences, context coverage and session incidents. Source-file hashes establish identity, not authenticity or a digital-signature audit.",
    }
