"""Reconcile complete same-day NSE intraday contract notes, never paper balances."""

import hashlib
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

from .core import IST, fingerprint, key, number, stamp, write
from .fees import estimate, profile_for
from .store import Store

COMPONENTS = ("brokerage", "exchange", "ipft", "sebi", "stt", "stamp", "gst")


def reconcile_note(note, source_bytes=None, records=None, now=None, tolerance="0.10"):
    now = now or datetime.now(IST)
    if note.get("schema_version") != 1 or note.get("broker") not in ("groww", "zerodha"):
        raise ValueError("Use contract-note schema 1 and Groww/Zerodha")
    day = date.fromisoformat(note["date"])
    if day > now.date():
        raise ValueError("Future contract notes cannot be observed evidence")
    if (
        note.get("exchange") != "NSE"
        or note.get("scope") != "COMPLETE_NSE_INTRADAY_ONLY"
        or note.get("scope_reviewed") is not True
    ):
        raise ValueError(
            "Review the complete note scope: only NSE cash intraday is supported; mixed delivery/F&O/MTF/BSE notes need a separate reviewed model"
        )
    actual = note.get("charges_inr", {})
    if set(actual) != set(COMPONENTS):
        raise ValueError(
            "Provide all seven charge components explicitly; a missing IPFT line cannot be silently assumed zero. Split combined lines only using a documented reviewed allocation."
        )
    if any(number(v) < 0 for v in actual.values()):
        raise ValueError("Negative charges/credit notes require a separate reviewed model")
    if sum((number(v) for v in actual.values()), number(0)) != number(note["total_charges_inr"]):
        raise ValueError("Actual charge components do not sum to the note total")
    if note.get("unmodeled_charges_inr") and number(note["unmodeled_charges_inr"]) != 0:
        raise ValueError(
            "Unmodeled charges must be reviewed separately before reconciling this scope"
        )
    executions = note.get("executions")
    if not isinstance(executions, list) or not 1 <= len(executions) <= 100000:
        raise ValueError("Provide 1..100000 actual executions")
    seen = set()
    orders = {}
    balances = defaultdict(int)
    for fill in executions:
        identity = fill.get("trade_id")
        if not isinstance(identity, str) or not identity.strip() or identity in seen:
            raise ValueError(
                "Every execution needs a distinct nonempty trade_id; duplicate imports are not additional trades"
            )
        seen.add(identity)
        instrument = fill["instrument"]
        key(*instrument.split(":"))
        if (
            not instrument.startswith("NSE:")
            or fill.get("product") != "INTRADAY"
            or fill["side"] not in ("BUY", "SELL")
        ):
            raise ValueError("Only explicit NSE intraday BUY/SELL executions are supported")
        qty = fill["quantity"]
        if type(qty) is not int or qty < 1:
            raise ValueError("Execution quantity must be positive whole shares")
        if stamp(fill["timestamp"]).date() != day or stamp(fill["timestamp"]) > now:
            raise ValueError(
                "Execution timestamp must fall on the contract date and not in the future"
            )
        price = number(fill["price"], True)
        order_id = fill.get("order_id")
        if not isinstance(order_id, str) or not order_id.strip():
            raise ValueError(
                "Per-order brokerage requires actual order IDs; trade IDs alone are insufficient"
            )
        order = orders.setdefault(
            order_id,
            {"instrument": instrument, "side": fill["side"], "quantity": 0, "notional": number(0)},
        )
        if (order["instrument"], order["side"]) != (instrument, fill["side"]):
            raise ValueError("One order ID cannot refer to different sides or instruments")
        order["quantity"] += qty
        order["notional"] += qty * price
        balances[instrument] += qty if fill["side"] == "BUY" else -qty
    if any(balances.values()):
        raise ValueError(
            "Every instrument must balance within the same-day intraday-only note scope"
        )
    grouped = {"BUY": [], "SELL": []}
    for identity, order in orders.items():
        grouped[order["side"]].append(
            {
                "order_id": identity,
                "quantity": order["quantity"],
                "price": str(order["notional"] / order["quantity"]),
            }
        )
    profile = profile_for(note["broker"], "NSE", day, records=records)
    calculated = estimate(profile, grouped["BUY"], grouped["SELL"])
    tolerance = number(tolerance)
    if not 0 <= tolerance <= 1:
        raise ValueError(
            "Component tolerance must be between zero and one rupee; differences stay visible"
        )
    comparisons = {
        k: {
            "estimated_inr": calculated["components_inr"][k],
            "actual_inr": str(number(actual[k])),
            "difference_inr": str(number(calculated["components_inr"][k]) - number(actual[k])),
        }
        for k in COMPONENTS
    }
    total_diff = number(calculated["total_inr"]) - number(note["total_charges_inr"])
    matched = abs(total_diff) <= tolerance and all(
        abs(number(r["difference_inr"])) <= tolerance for r in comparisons.values()
    )
    source_hash = hashlib.sha256(source_bytes).hexdigest() if source_bytes else None
    reviewed = (
        note.get("source_reviewed") is True
        and source_hash
        and note.get("origin") == "BROKER_CONTRACT_NOTE"
    )
    result = {
        "broker": note["broker"],
        "date": str(day),
        "exchange": "NSE",
        "status": "MATCHED" if matched else "MISMATCH",
        "evidence_origin": "SYNTHETIC"
        if note.get("origin") == "SYNTHETIC"
        else "USER_REVIEWED_CONTRACT_NOTE"
        if reviewed
        else "UNVERIFIED_INPUT",
        "source_sha256": source_hash,
        "checked_at": now.isoformat(),
        "profile_id": profile["id"],
        "execution_count": len(executions),
        "order_count": len(orders),
        "instrument_count": len(balances),
        "components": comparisons,
        "estimated_total_inr": calculated["total_inr"],
        "actual_total_inr": str(number(note["total_charges_inr"])),
        "total_difference_inr": str(total_diff),
        "tolerance_inr": str(tolerance),
        "gross_pnl_inr": calculated["gross_pnl_inr"],
        "actual_net_pnl_inr": str(
            number(calculated["gross_pnl_inr"]) - number(note["total_charges_inr"])
        ),
        "note": "Daily complete-scope comparison. Imported declarations/source hash do not authenticate the broker document. Contract-note aggregation/rounding may differ; mismatches never auto-adjust fee profiles or paper balances.",
    }
    result["report_id"] = fingerprint({k: v for k, v in result.items() if k != "checked_at"})
    return result


def import_note(workspace, note, source_file=None, records=None, tolerance="0.10"):
    source = Path(source_file).read_bytes() if source_file else None
    result = reconcile_note(note, source, records, tolerance=tolerance)
    config_path = Path(workspace) / "config.json"
    if config_path.exists():
        from .core import read

        if read(config_path).get("data_mode") == "DEMO":
            result["evidence_origin"] = "SYNTHETIC_WORKSPACE"
            result["report_id"] = fingerprint(
                {k: v for k, v in result.items() if k not in ("report_id", "checked_at")}
            )
    store = Store(workspace)
    existing = store.get("contract_reconciliations", [])
    if not any(r["report_id"] == result["report_id"] for r in existing):
        existing.append(result)
    store.put("contract_reconciliations", existing)
    write(Path(workspace) / "evidence" / ("contract-" + result["report_id"][:16] + ".json"), result)
    store.event(
        "CONTRACT_NOTE_RECONCILIATION",
        result,
        result["checked_at"],
        result["evidence_origin"],
        identity=result["report_id"],
    )
    return result
