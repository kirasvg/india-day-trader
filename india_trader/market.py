"""Dated instrument metadata and session phases. Unknown coverage fails closed."""

from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict

from .core import key, number, read, stamp

TEMPLATES = Path(__file__).resolve().parent / "templates"


def applies(record, day):
    day = str(day)
    return (
        record.get("valid_from", day) <= day <= (record.get("valid_to") or "9999-12-31")
        and record.get("published_on", record.get("valid_from", day)) <= day
    )


def instrument_on(instruments, instrument, day, strict=False):
    key(*instrument.split(":"))
    raw = instruments.get(instrument)
    if not raw:
        raise ValueError("No instrument metadata for " + instrument)
    if "versions" not in raw:
        if strict:
            raise ValueError(
                "Undated legacy metadata; run sync or import a dated instrument snapshot"
            )
        return dict(raw, metadata_status="LEGACY_UNVERIFIED")
    candidates = [r for r in raw["versions"] if applies(r, day)]
    if len(candidates) != 1:
        raise ValueError(
            "Need exactly one dated instrument record for %s on %s" % (instrument, day)
        )
    result = dict(candidates[0])
    if not result.get("source") or not result.get("observed_on"):
        raise ValueError("Dated instrument metadata requires provenance")
    number(result["tick_size"], True)
    return result


def merge_instruments(existing, incoming, day, source):
    """New observations begin today; never apply today's tick or tokens to history."""
    day = str(day)
    result = deepcopy(existing)
    for instrument, metadata in incoming.items():
        old = result.get(instrument, {})
        versions = deepcopy(old.get("versions", []))
        # Legacy metadata lacks a defensible effective date; do not manufacture one.
        active = [r for r in versions if applies(r, day)]
        if len(active) > 1 or any(r["valid_from"] > day for r in versions):
            raise ValueError("Overlapping or future instrument versions; review before merging")
        new = dict(metadata, valid_from=day, valid_to=None, observed_on=day, source=source)
        if active:
            prior = active[0]
            if prior["valid_from"] == day:
                versions.remove(prior)
                # Preserve explicit user-reviewed restrictions only when structural identity agrees.
                if new.get("intraday_allowed") is None and all(
                    prior.get(k) == new.get(k)
                    for k in ("tick_size", "lot_size", "session_class", "asset", "isin")
                ):
                    for field in (
                        "intraday_allowed",
                        "eligibility_source",
                        "eligibility_reviewed_on",
                        "eligibility_broker",
                    ):
                        if field in prior:
                            new[field] = prior[field]
            else:
                prior["valid_to"] = str(date.fromisoformat(day) - timedelta(days=1))
        versions.append(new)
        result[instrument] = {"versions": sorted(versions, key=lambda r: r["valid_from"])}
    return result


def bar_grid(s, minutes=5):
    grid = []
    for start, end in s["continuous"]:
        if (end - start).total_seconds() % (minutes * 60):
            raise ValueError("Continuous interval does not align to candle size")
        cursor = start
        while cursor + timedelta(minutes=minutes) <= end:
            grid.append(cursor)
            cursor += timedelta(minutes=minutes)
    return grid


def _clock(day, value):
    # Policy clock strings are local exchange wall times, not arbitrary timestamps.
    return stamp(str(day) + "T" + value + "+05:30")


def resolve_session(calendar, exchange, day, instrument=None, instruments=None, broker=None):
    result: Dict[str, Any]
    day = str(day)
    if calendar.get("schema_version", 1) == 1:
        record = calendar.get("sessions", {}).get(exchange + ":" + day)
        if not record:
            raise ValueError(
                "No verified session for %s:%s; update calendar.json" % (exchange, day)
            )
        result = {
            k: _clock(day, record[k])
            for k in ("open", "close", "entry_after", "entry_before", "flat_by")
        }
        result.update(
            continuous=[(result["open"], result["close"])],
            policy_id="legacy-explicit-session",
            policy_status="LEGACY_UNVERIFIED",
            cutoff_status="LEGACY_UNVERIFIED",
            session_class="EXPLICIT",
        )
    elif calendar.get("schema_version") == 2:
        record = calendar.get("days", {}).get(exchange + ":" + day)
        if not record:
            raise ValueError("Calendar coverage MISSING for %s:%s" % (exchange, day))
        if record.get("status") != "OPEN":
            raise ValueError(
                "Session %s: %s" % (record.get("status", "UNVERIFIED"), record.get("reason", day))
            )
        if not record.get("source"):
            raise ValueError("Calendar day lacks provenance")
        meta = instrument_on(instruments or {}, instrument, day, strict=True) if instrument else {}
        session_class = meta.get("session_class")
        if session_class not in ("CAS", "NON_CAS"):
            raise ValueError("Session classification UNVERIFIED for " + str(instrument))
        records = [
            r
            for r in calendar.get("policies", [])
            if r["exchange"] == exchange and r["session_class"] == session_class and applies(r, day)
        ]
        if len(records) != 1:
            raise ValueError(
                "Need exactly one effective %s %s session policy on %s"
                % (exchange, session_class, day)
            )
        policy = records[0]
        if not policy.get("source") or not policy.get("reviewed_on"):
            raise ValueError("Session policy lacks provenance")
        phases = record.get("phases", policy["phases"])
        parsed = [
            {"kind": p["kind"], "start": _clock(day, p["start"]), "end": _clock(day, p["end"])}
            for p in phases
        ]
        for i, phase in enumerate(parsed):
            if phase["start"] >= phase["end"] or (i and phase["start"] < parsed[i - 1]["end"]):
                raise ValueError("Overlapping or reversed session phases")
        continuous = [(p["start"], p["end"]) for p in parsed if p["kind"] == "continuous"]
        if not continuous:
            raise ValueError("No supported continuous trading interval")
        cutoffs = [
            r
            for r in calendar.get("broker_cutoffs", [])
            if r["broker"] == broker
            and r["exchange"] == exchange
            and r["session_class"] == session_class
            and applies(r, day)
        ]
        if len(cutoffs) > 1:
            raise ValueError("Ambiguous broker cutoff policies")
        preferences = calendar.get("preferences", {})
        buffer = int(preferences.get("exit_buffer_minutes", 10))
        opening_delay = int(preferences.get("opening_range_minutes", 15))
        entry_buffer = int(preferences.get("last_entry_buffer_minutes", 30))
        if buffer < 1 or opening_delay != 15 or entry_buffer < 1:
            raise ValueError("Invalid session preferences")
        deadline = continuous[-1][1]
        if cutoffs:
            if not cutoffs[0].get("source"):
                raise ValueError("Broker cutoff lacks provenance")
            deadline = min(deadline, _clock(day, cutoffs[0]["cutoff"]))
        if record.get("flat_by"):
            deadline = min(deadline, _clock(day, record["flat_by"]) + timedelta(minutes=buffer))
        flat = deadline - timedelta(minutes=buffer)
        result = {
            "open": continuous[0][0],
            "close": continuous[-1][1],
            "continuous": continuous,
            "entry_after": continuous[0][0] + timedelta(minutes=opening_delay),
            "entry_before": flat - timedelta(minutes=entry_buffer),
            "flat_by": flat,
            "phases": parsed,
            "policy_id": policy["id"],
            "policy_source": policy["source"],
            "policy_reviewed_on": policy["reviewed_on"],
            "session_class": session_class,
            "policy_status": "VERIFIED_SNAPSHOT",
            "cutoff_status": "VERIFIED_SNAPSHOT" if cutoffs else "UNVERIFIED",
            "cutoff_source": cutoffs[0]["source"] if cutoffs else None,
            "cutoff_note": "No broker-specific cutoff verified; exchange deadline minus buffer is only an application safety policy"
            if not cutoffs
            else "Verified provider cutoff minus application safety buffer",
        }
    else:
        raise ValueError("Unsupported calendar schema; refusing implicit conversion")
    if (
        not result["open"]
        <= result["entry_after"]
        <= result["entry_before"]
        < result["flat_by"]
        <= result["close"]
    ):
        raise ValueError("Invalid session boundaries")
    if not any(start < result["flat_by"] <= end for start, end in result["continuous"]):
        raise ValueError("Flat-by is outside continuous trading")
    bar_grid(result)
    return result


def phase_at(s, now):
    for phase in s.get("phases", []):
        if phase["start"] <= now < phase["end"]:
            return phase["kind"]
    if any(start <= now < end for start, end in s["continuous"]):
        return "continuous"
    return "before_open" if now < s["open"] else "closed"


def eligibility(metadata, broker=None):
    reasons = []
    if metadata.get("asset") != "EQUITY" or metadata.get("lot_size") != 1:
        reasons.append("Unsupported asset or non-standard lot")
    if metadata.get("series") in ("BE", "BZ", "SM", "ST", "T", "XT"):
        reasons.append("Trade-to-trade or SME series is unsupported")
    if metadata.get("suspended") is True or metadata.get("gsm_stage"):
        reasons.append("Suspension or GSM restriction requires exclusion")
    if metadata.get("asm_stage") and metadata.get("intraday_allowed") is not True:
        reasons.append("ASM requires stage-specific broker eligibility review")
    if metadata.get("intraday_allowed") is False:
        reasons.append("Broker intraday product is blocked")
    unknown = metadata.get("intraday_allowed") is not True or not metadata.get("eligibility_source")
    if broker and metadata.get("eligibility_broker") != broker:
        unknown = True
    return {
        "status": "BLOCKED" if reasons else "UNVERIFIED" if unknown else "AVAILABLE",
        "reasons": reasons
        or (
            [
                "Verify intraday eligibility in the selected broker; symbol presence alone is insufficient"
            ]
            if unknown
            else []
        ),
    }


def bundled_calendar():
    """Packaged, reviewed snapshot. It is not a live exchange-calendar service."""
    return read(TEMPLATES / "market-2026.json")
