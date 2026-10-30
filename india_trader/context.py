"""Source-specific corporate coverage and timestamped ETF market/sector proxies."""

from datetime import datetime
from pathlib import Path

from .auth import broker_client
from .brokers import broker_stamp
from .core import IST, number, read, stamp
from .filings import normalize_events
from .research import fetch_feed, monitor
from .store import Store

DIRECTORY = "https://www.nseindia.com/static/rss-feed"
SOURCES = [
    {
        "id": identity,
        "category": category,
        "url": "https://nsearchives.nseindia.com/content/RSS/" + filename,
        "directory": DIRECTORY,
    }
    for identity, category, filename in (
        ("announcements", "announcements", "Online_announcements.xml"),
        ("financial-results", "results", "Financial_Results.xml"),
        ("integrated-financials", "results", "Integrated_Filing_Financials.xml"),
        ("corporate-actions", "corporate-action", "Corporate_action.xml"),
        ("board-meetings", "board-meeting", "Board_Meetings.xml"),
        ("insider-trading", "insider-disclosure", "InsiderTrading.xml"),
        ("pledges", "pledge", "Sast_ReasonForEncumbrance.xml"),
    )
]
PROXIES = [
    {"instrument": "NSE:NIFTYBEES", "label": "Broad market ETF proxy", "role": "MARKET"},
    {"instrument": "NSE:BANKBEES", "label": "Banking ETF proxy", "role": "SECTOR"},
    {"instrument": "NSE:ITBEES", "label": "Information technology ETF proxy", "role": "SECTOR"},
]
PROXY_SOURCE = "https://www.nseindia.com/market-data/exchange-traded-funds-etf"


def broker_proxies(client, now=None, max_age=60):
    """Context-only ETF observations; never insert these into a trade watchlist."""
    output = []
    for definition in PROXIES:
        item = dict(
            definition,
            source=client.name,
            definition_source=PROXY_SOURCE,
            kind="ETF_PROXY_NOT_INDEX",
        )
        try:
            exchange, symbol = definition["instrument"].split(":")
            if client.name == "zerodha":
                raw = client.transport("/quote", {"i": definition["instrument"]})[
                    definition["instrument"]
                ]
                if not raw.get("last_trade_time"):
                    raise ValueError("Proxy exchange trade timestamp missing")
                at = broker_stamp(raw["last_trade_time"])
            else:
                raw = client.transport(
                    "/v1/live-data/quote",
                    {"exchange": exchange, "segment": "CASH", "trading_symbol": symbol},
                )
                if not raw.get("last_trade_time"):
                    raise ValueError("Proxy exchange trade timestamp missing")
                at = datetime.fromtimestamp(float(number(raw["last_trade_time"]) / 1000), IST)
            price = number(raw["last_price"], True)
            ohlc = raw.get("ohlc", {})
            previous = (
                number(ohlc["close"], True)
                if isinstance(ohlc, dict) and ohlc.get("close")
                else None
            )
            change = (
                (price / previous - 1) * 100
                if previous
                else number(raw["day_change_perc"])
                if raw.get("day_change_perc") is not None
                else None
            )
            age = ((now or datetime.now(IST)) - at).total_seconds()
            item.update(
                status="AVAILABLE" if 0 <= age <= max_age else "STALE",
                price_inr=str(price),
                previous_close_inr=str(previous) if previous else None,
                change_pct=str(change.quantize(number("0.01"))) if change is not None else None,
                timestamp=at.isoformat(),
                received_at=datetime.now(IST).isoformat(),
                trade_age_seconds=age,
            )
        except (ValueError, KeyError, OSError, ArithmeticError) as error:
            item.update(status=getattr(error, "state", "ERROR"), detail=str(error))
        output.append(item)
    return output


def collect(workspace, public_only=False, client=None, fetch=None, now=None, force=False):
    workspace = Path(workspace)
    store = Store(workspace)
    config = read(workspace / "config.json") if (workspace / "config.json").exists() else {}
    if config.get("data_mode") == "DEMO":
        raise ValueError(
            "Synthetic desks never contact context providers; use a separate research/connected workspace"
        )
    clock = now or datetime.now(IST)
    origin = (
        "TEST_DOUBLE"
        if fetch is not None or client is not None or now is not None
        else "PUBLIC_AND_BROKER"
        if not public_only
        else "PUBLIC_SOURCE"
    )
    fetch = fetch or fetch_feed
    cached = store.get("context_snapshot", {})
    source_rows = []
    all_events = []
    selected = config.get("watchlist", [])
    aliases = {name: [name.split(":")[1]] for name in selected}
    for name, values in config.get("watchlist_aliases", {}).items():
        if name in aliases:
            aliases[name] = list(set(aliases[name] + values))
    # Current provider names enrich matching, while the UI still labels it a text match.
    instruments = (
        read(workspace / "instruments.json") if (workspace / "instruments.json").exists() else {}
    )
    for name in selected:
        record = instruments.get(name, {})
        versions = record.get("versions", [])
        label = (versions[-1] if versions else record).get("name")
        if label:
            aliases[name].append(label)
    for definition in SOURCES:
        previous = next((r for r in cached.get("sources", []) if r["id"] == definition["id"]), {})
        age = (
            (clock - stamp(previous["checked_at"])).total_seconds()
            if previous.get("checked_at")
            else None
        )
        if not force and cached.get("origin") == origin and age is not None and 0 <= age < 300:
            source_rows.append(previous)
            continue
        row = dict(definition, checked_at=clock.isoformat())
        try:
            rows = fetch(definition["url"])
            undated = sum(not r.get("published_at") for r in rows)
            recent = monitor(rows, clock, 168, aliases or None)
            valid = []
            invalid = 0
            for item in recent["items"]:
                item = dict(item, source=definition["url"], category=definition["category"])
                try:
                    valid.extend(normalize_events([item], clock))
                except (ValueError, KeyError, TypeError):
                    invalid += 1
            all_events.extend(valid)
            known = [
                stamp(r["published_at"])
                for r in rows
                if r.get("published_at") and stamp(r["published_at"]) <= clock
            ]
            latest = max(known) if known else None
            future_count = sum(
                bool(r.get("published_at")) and stamp(r["published_at"]) > clock for r in rows
            )
            state = (
                "EMPTY_UNVERIFIED"
                if not rows
                else "UNVERIFIED"
                if not latest
                else "STALE"
                if (clock - latest).total_seconds() > 86400
                else "PARTIAL_UNVERIFIED"
                if undated or invalid or future_count
                else "AVAILABLE"
            )
            row.update(
                status=state,
                input_items=len(rows),
                matched_items=len(valid),
                undated_items=undated,
                invalid_items=invalid,
                future_items=future_count,
                latest_publication=latest.isoformat() if latest else None,
                coverage="SOURCE_SPECIFIC_NOT_COMPLETE",
            )
        except (ValueError, KeyError, OSError, TypeError, ArithmeticError) as error:
            row.update(status="ERROR", detail=str(error), coverage="UNVERIFIED")
        source_rows.append(row)
    if all_events:
        store.filings(all_events, clock.isoformat())
    if public_only:
        proxies = [dict(p, status="NOT_REQUESTED", kind="ETF_PROXY_NOT_INDEX") for p in PROXIES]
    else:
        try:
            proxies = broker_proxies(
                client or broker_client(workspace, config.get("broker")),
                clock if now is not None else None,
                config.get("max_quote_age_seconds", 60),
            )
        except (ValueError, KeyError, OSError) as error:
            proxies = [
                dict(p, status=getattr(error, "state", "ERROR"), detail=str(error)) for p in PROXIES
            ]
    sources_ready = all(
        any(r["category"] == category and r["status"] == "AVAILABLE" for r in source_rows)
        for category in ("announcements", "results", "corporate-action")
    )
    proxies_ready = all(r["status"] == "AVAILABLE" for r in proxies)
    result = {
        "at": (clock if now is not None else datetime.now(IST)).isoformat(),
        "origin": origin,
        "status": "OBSERVED_SOURCE_COVERAGE" if sources_ready and proxies_ready else "PARTIAL",
        "sources": source_rows,
        "proxies": proxies,
        "watchlist": selected,
        "max_proxy_age_seconds": config.get("max_quote_age_seconds", 60),
        "note": "ETF prices are context proxies, not index levels, breadth, a sector classification of every stock or trading signals. Feed reachability/zero items never establish complete news coverage. Sources poll at most every five minutes unless forced; provider timestamps remain distinct from receipt.",
    }
    current = store.get("context_snapshot", {})
    if current.get("at") and stamp(current["at"]) > stamp(result["at"]):
        return current
    store.put("context_snapshot", result)
    return result


def snapshot(store, now=None):
    value = store.get("context_snapshot", {})
    if not value:
        return {"status": "NOT_COLLECTED", "sources": [], "proxies": []}
    now = now or datetime.now(IST)
    age = (now - stamp(value["at"])).total_seconds()
    if age < 0 or age > 600:
        value["status"] = "STALE"
    value["snapshot_age_seconds"] = age
    for proxy in value.get("proxies", []):
        if proxy.get("timestamp"):
            elapsed = (now - stamp(proxy["timestamp"])).total_seconds()
            proxy["trade_age_seconds"] = elapsed
            if elapsed < 0 or elapsed > value.get("max_proxy_age_seconds", 60):
                proxy["status"] = "STALE"
    if value["status"] == "OBSERVED_SOURCE_COVERAGE" and any(
        r["status"] != "AVAILABLE" for r in value.get("proxies", [])
    ):
        value["status"] = "PARTIAL"
    return value
