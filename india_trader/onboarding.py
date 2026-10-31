"""Guided local setup, read-only sync and actionable health diagnostics."""

import shutil
from datetime import datetime, timedelta
from pathlib import Path

from .auth import broker_client
from .brokers import BrokerError, import_master, save_candles
from .core import IST, key, load_bars, number, read, stamp, validate_config, write
from .market import (
    bar_grid,
    bundled_calendar,
    eligibility,
    instrument_on,
    merge_instruments,
    phase_at,
    resolve_session,
)
from .secrets import ENV_NAMES, credentials

TEMPLATES = Path(__file__).resolve().parent / "templates"


def watchlist(value):
    values = [v.strip().upper() for v in value.split(",") if v.strip()]
    if not 1 <= len(values) <= 50 or len(values) != len(set(values)):
        raise ValueError("Choose 1..50 distinct EXCHANGE:SYMBOL instruments")
    for value in values:
        parts = value.split(":")
        if len(parts) != 2:
            raise ValueError("Use exchange-qualified symbols, for example NSE:INFY")
        key(*parts)
    return values


def setup(
    workspace,
    broker=None,
    instruments=None,
    capital=None,
    max_loss=None,
    daily_risk=None,
    demo=False,
    data_provider=None,
    account_source=None,
):
    if account_source not in (None, "broker", "manual"):
        raise ValueError("Account source must be broker or manual")
    if account_source == "manual" and data_provider != "upstox":
        raise ValueError("Manual account mode requires the separate Upstox data provider")
    if demo and account_source is not None:
        raise ValueError("Demo setup cannot select a real account connection")
    if data_provider not in (None, "upstox"):
        raise ValueError("Separate data provider currently supports Upstox only")
    if data_provider and (demo or broker not in ("groww", "zerodha")):
        raise ValueError(
            "Upstox data requires a connected Groww/Zerodha manual-execution workspace"
        )
    if any(
        (workspace / name).exists()
        for name in ("settings.json", "config.json", "account.json", "calendar.json")
    ):
        raise ValueError(
            "Workspace already initialized; use doctor, auth or sync. Setup never resets balances."
        )
    workspace.mkdir(parents=True, exist_ok=True)
    if demo:
        for path in (TEMPLATES / "demo").iterdir():
            if path.is_file():
                shutil.copy2(path, workspace / path.name)
        config = read(workspace / "config.json")
        config.update(broker=broker or "zerodha", watchlist=["NSE:RELIANCE"], data_mode="DEMO")
        if (workspace / "context.json").exists():
            from .store import Store

            Store(workspace).put("context_snapshot", read(workspace / "context.json"))
    else:
        if broker not in ENV_NAMES or not instruments or capital is None or max_loss is None:
            raise ValueError(
                "Use setup --broker groww|zerodha --watchlist NSE:INFY,... --capital INR --max-loss INR, or setup --demo"
            )
        selected = watchlist(instruments)
        if data_provider == "upstox" and any(not name.startswith("NSE:") for name in selected):
            raise ValueError(
                "The Upstox data-only adapter currently supports NSE cash equities only"
            )
        capital, max_loss = number(capital, True), number(max_loss, True)
        daily = number(daily_risk, True) if daily_risk else max_loss * 3
        if max_loss > daily or daily > capital:
            raise ValueError("Require per-trade loss <= daily risk <= starting capital")
        config = read(TEMPLATES / "config.json")
        config.update(
            capital_inr=str(capital),
            max_loss_per_trade_inr=str(max_loss),
            max_daily_risk_inr=str(daily),
            broker=broker,
            watchlist=selected,
            data_mode="CONNECTED",
            limits_reviewed=True,
            fee_mode="published_snapshot",
            require_broker_snapshot=True,
            cost_note="Dated published NSE intraday estimates; contract-note reconciliation remains required. Legacy aggregate fee settings are ignored in this mode.",
        )
        validate_config(config)
        write(workspace / "calendar.json", bundled_calendar())
        write(workspace / "instruments.json", {})
        write(workspace / "quotes.json", {})
        write(
            workspace / "account.json",
            {"cash_inr": str(capital), "positions": {}, "trades": [], "mode": "LOCAL_PAPER"},
        )
    if data_provider:
        config.update(
            data_provider=data_provider,
            execution_mode="MANUAL",
            account_source="BROKER" if account_source == "broker" else "MANUAL_ATTESTATION",
        )
    write(workspace / "config.json", config)
    (workspace / ".gitignore").write_text("*\n!.gitignore\n", encoding="utf-8")
    write(
        workspace / "settings.json",
        {
            "schema_version": 1,
            "broker": config["broker"],
            "data_provider": config.get("data_provider", config["broker"]),
            "account_source": config.get("account_source", "BROKER"),
            "mode": config["data_mode"],
            "watchlist": config["watchlist"],
            "credentials": "environment unless auth explicitly enables Keychain",
            "cost_status": "ILLUSTRATIVE_ESTIMATE" if demo else "PUBLISHED_ESTIMATE",
        },
    )
    return {
        "status": "CONFIGURED",
        "mode": config["data_mode"],
        "broker": config["broker"],
        "watchlist": config["watchlist"],
        "workspace": str(workspace),
        "next_steps": [
            "Run doctor",
            "For real data: connect locally with auth or environment credentials, then run sync",
            "Review any unverified intraday eligibility/cutoff shown by doctor",
        ],
        "note": "Demo uses synthetic data. Connected setup uses a reviewed NSE calendar snapshot; BSE and unknown special sessions require sourced calendar imports. No account order tools enabled.",
    }


def interactive_setup(workspace, ask=input, data_provider=None, account_source=None):
    print("India Trader setup — local research and paper trading")
    mode = ask("Mode [demo/connected]: ").strip().lower()
    if mode == "demo":
        return setup(
            workspace, demo=True, data_provider=data_provider, account_source=account_source
        )
    if mode != "connected":
        raise ValueError("Choose demo or connected")
    broker = ask("Execution broker [groww/zerodha]: ").strip().lower()
    provider = data_provider or ask("Market data [broker/upstox; blank=broker]: ").strip().lower()
    if provider not in ("", "broker", "upstox"):
        raise ValueError("Choose broker or upstox for market data")
    source = account_source
    if provider == "upstox" and source is None:
        source = (
            ask("Execution-account exposure [broker/manual; blank=manual]: ").strip().lower()
            or "manual"
        )
    return setup(
        workspace,
        broker=broker,
        account_source=source,
        data_provider="upstox" if provider == "upstox" else None,
        instruments=ask("Watchlist, comma separated (e.g. NSE:INFY,NSE:RELIANCE): "),
        capital=ask("Starting paper capital in INR: "),
        max_loss=ask("Maximum planned loss per trade in INR: "),
        daily_risk=ask("Maximum daily reserved risk in INR: "),
    )


def check(name, state, detail, action=None, **extra):
    return dict(name=name, state=state, detail=detail, next_action=action, **extra)


def doctor(workspace, now=None, online=False, client=None, account_client=None):
    now = now or datetime.now(IST)
    checks = []
    if not (workspace / "config.json").exists():
        return {
            "status": "NEEDS_SETUP",
            "checks": [
                check(
                    "workspace",
                    "MISSING",
                    "No configured workspace",
                    "Run setup --demo or setup --interactive",
                )
            ],
            "ready_for_live_trading": False,
        }
    config = read(workspace / "config.json")
    settings = read(workspace / "settings.json") if (workspace / "settings.json").exists() else {}
    demo = config.get("data_mode") == "DEMO" or "SYNTHETIC" in config.get("data_label", "")
    selected = config.get("watchlist", list(config.get("watchlist_aliases", {})))
    broker = settings.get("broker", config.get("broker", "zerodha"))
    provider = config.get("data_provider", broker)
    try:
        validate_config(config)
        checks.append(
            check("configuration", "AVAILABLE", "Limits and cash settings are structurally valid")
        )
    except (ValueError, KeyError, ArithmeticError) as error:
        checks.append(check("configuration", "ERROR", str(error), "Review setup limits"))
    if demo:
        checks.append(
            check(
                "provenance",
                "SYNTHETIC",
                "Invented demonstration data; no connection or real-market readiness is implied",
            )
        )
    else:
        try:
            values = credentials(
                provider, workspace, settings.get("credential_store") == "keychain"
            )
            present = all(values.values())
            checks.append(
                check(
                    "credentials",
                    "AVAILABLE" if present else "MISSING",
                    "Required values present; actual authentication is a separate check"
                    if present
                    else "Required credentials are missing",
                    "Run doctor --online"
                    if present
                    else "Run auth locally on macOS, or set the documented environment variables",
                )
            )
        except ValueError as error:
            checks.append(
                check(
                    "credentials",
                    "ERROR",
                    str(error),
                    "Unlock Keychain or use environment credentials",
                )
            )
    separate_account = provider != broker and config.get("account_source") == "BROKER"
    if separate_account and not demo:
        try:
            values = credentials(broker, workspace, settings.get("credential_store") == "keychain")
            checks.append(
                check(
                    "account_credentials",
                    "AVAILABLE" if all(values.values()) else "MISSING",
                    "Execution-account credentials are separate from the market-data token",
                    "Connect %s locally with auth; no market-data subscription is inferred"
                    % broker,
                )
            )
            if online:
                account_client = account_client or broker_client(workspace, broker)
                account_client.profile()
                checks.append(
                    check(
                        "account_login",
                        "AVAILABLE",
                        "Execution-broker profile authenticated; complete exposure remains checked by sync",
                    )
                )
        except (ValueError, KeyError, OSError) as error:
            checks.append(
                check(
                    "account_login",
                    getattr(error, "state", "ERROR"),
                    str(error),
                    "Reconnect the execution broker locally; manual exposure is not substituted",
                )
            )
    calendar = read(workspace / "calendar.json") if (workspace / "calendar.json").exists() else {}
    instruments = (
        read(workspace / "instruments.json") if (workspace / "instruments.json").exists() else {}
    )
    quotes = read(workspace / "quotes.json") if (workspace / "quotes.json").exists() else {}
    if calendar.get("schema_version") == 2:
        age = (now.date() - datetime.fromisoformat(calendar["reviewed_on"]).date()).days
        checks.append(
            check(
                "calendar_snapshot",
                "STALE" if age > calendar.get("review_interval_days", 7) else "AVAILABLE",
                "Snapshot reviewed %s; not a live calendar service" % calendar["reviewed_on"],
                "Import a newly reviewed sourced calendar with market load-calendar"
                if age > 7
                else None,
            )
        )
    elif not demo:
        checks.append(
            check(
                "calendar_snapshot",
                "UNVERIFIED",
                "Legacy explicit calendar lacks policy classes and dated rule sources",
                "Import a reviewed schema-v2 calendar",
            )
        )
    if online and not demo:
        try:
            client = client or broker_client(workspace, provider)
            if provider == "upstox":
                if not client.instruments:
                    client.master()
                result = {"status": "MARKET_DATA_ONLY", "provider": provider}
            else:
                result = client.profile()
            checks.append(
                check(
                    "login",
                    "AVAILABLE" if provider != "upstox" else "DATA_ONLY",
                    "Quote authentication checked below; this token has market-data scope only"
                    if provider == "upstox"
                    else "Read-only profile authenticated",
                    capabilities=result,
                )
            )
            write(
                workspace / "connection-health.json",
                {
                    "broker": broker,
                    "data_provider": provider,
                    "checked_at": now.isoformat(),
                    "profile": "DATA_ONLY" if provider == "upstox" else "AVAILABLE",
                },
            )
            if selected:
                exchange, symbol = selected[0].split(":")
                result = client.quote(exchange, symbol)
                quotes.update(result)
                write(workspace / "quotes.json", quotes)
                checks.append(
                    check(
                        "market_data_entitlement",
                        "AVAILABLE",
                        "Quote endpoint returned a trade timestamp; historical access remains separately checked by sync",
                    )
                )
        except BrokerError as error:
            checks.append(
                check(
                    "connection",
                    error.state,
                    str(error),
                    "Reconnect for AUTH_REQUIRED; inspect subscription for NOT_ENTITLED; otherwise retry after checking network/provider status",
                )
            )
        except (ValueError, KeyError, OSError) as error:
            checks.append(
                check("connection", "ERROR", str(error), "Check the broker capability and retry")
            )
    elif not demo:
        cached = (
            read(workspace / "connection-health.json")
            if (workspace / "connection-health.json").exists()
            else {}
        )
        fresh = (
            cached.get("broker") == broker
            and cached.get("data_provider", broker) == provider
            and cached.get("checked_at")
            and 0 <= (now - stamp(cached["checked_at"])).total_seconds() <= 900
        )
        checks.append(
            check(
                "login",
                "DATA_ONLY"
                if fresh and provider == "upstox"
                else "AVAILABLE"
                if fresh
                else "UNVERIFIED",
                "Connection checked within the last 15 minutes; account scope depends on provider"
                if fresh
                else "Authentication has not been checked recently",
                None if fresh else "Run doctor --online",
            )
        )
    try:
        bars = load_bars(workspace / "bars.csv") if (workspace / "bars.csv").exists() else []
    except (ValueError, KeyError, OSError, ArithmeticError) as error:
        bars = []
        checks.append(check("bars", "ERROR", str(error), "Refresh or repair the candle import"))
    closed_count = 0
    for instrument in selected:
        try:
            metadata = instrument_on(
                instruments, instrument, now.date(), strict=calendar.get("schema_version") == 2
            )
            age = (
                now.date()
                - datetime.fromisoformat(metadata.get("observed_on", str(now.date()))).date()
            ).days
            checks.append(
                check(
                    "instrument:" + instrument,
                    "STALE" if age > 1 else "AVAILABLE",
                    "Dated instrument snapshot"
                    if "valid_from" in metadata
                    else "Legacy demonstration metadata",
                    "Run sync to refresh master" if age > 1 else None,
                )
            )
            eligible = eligibility(metadata, broker)
            if not demo:
                checks.append(
                    check(
                        "eligibility:" + instrument,
                        eligible["status"],
                        "; ".join(eligible["reasons"])
                        or "Broker intraday eligibility explicitly reviewed",
                        "Run market verify-instrument after checking the selected broker"
                        if eligible["status"] != "AVAILABLE"
                        else None,
                    )
                )
        except ValueError as error:
            checks.append(
                check(
                    "instrument:" + instrument,
                    "MISSING",
                    str(error),
                    "Run sync; partial master imports may require explicit classification review",
                )
            )
            continue
        try:
            s = resolve_session(
                calendar, instrument.split(":")[0], now.date(), instrument, instruments, broker
            )
            phase = phase_at(s, now)
            if phase != "continuous":
                closed_count += 1
            checks.append(
                check(
                    "session:" + instrument,
                    "AVAILABLE",
                    "Phase %s; flat by %s IST; policy %s"
                    % (phase, s["flat_by"].strftime("%H:%M"), s["policy_id"]),
                    phase=phase,
                    expected_bars=len(bar_grid(s)),
                )
            )
            if not demo:
                checks.append(
                    check(
                        "broker_cutoff:" + instrument,
                        "AVAILABLE" if s["cutoff_status"] == "VERIFIED_SNAPSHOT" else "UNVERIFIED",
                        s.get("cutoff_note", "Legacy cutoff"),
                        "Import a sourced broker cutoff with market set-cutoff"
                        if s["cutoff_status"] != "VERIFIED_SNAPSHOT"
                        else None,
                    )
                )
            expected = {t for t in bar_grid(s) if t + timedelta(minutes=5) <= min(now, s["close"])}
            observed = {
                r["timestamp"]
                for r in bars
                if r["key"] == instrument and r["timestamp"] in expected
            }
            state = (
                "AVAILABLE"
                if expected and observed == expected
                else "WAITING"
                if not expected
                else "MISSING"
            )
            checks.append(
                check(
                    "candles:" + instrument,
                    state,
                    "%d/%d closed session bars available" % (len(observed), len(expected)),
                    "Run sync to backfill missing bars" if state == "MISSING" else None,
                    observed=len(observed),
                    expected=len(expected),
                )
            )
        except ValueError as error:
            state = "CLOSED" if str(error).startswith("Session CLOSED") else "UNVERIFIED"
            closed_count += int(state == "CLOSED")
            checks.append(
                check(
                    "session:" + instrument,
                    state,
                    str(error),
                    "Import verified session metadata"
                    if state != "CLOSED"
                    else "Run status on the next trading session",
                )
            )
        quote = quotes.get(instrument)
        if quote:
            age = (now - stamp(quote["timestamp"])).total_seconds()
            checks.append(
                check(
                    "quote:" + instrument,
                    "AVAILABLE" if 0 <= age <= config["max_quote_age_seconds"] else "STALE",
                    "Last trade age %.0f seconds; this is separate from network heartbeat" % age,
                    "Run sync --quotes-only"
                    if not 0 <= age <= config["max_quote_age_seconds"]
                    else None,
                )
            )
        else:
            checks.append(
                check(
                    "quote:" + instrument,
                    "MISSING",
                    "No timestamped quote",
                    "Run sync --quotes-only",
                )
            )
    if not demo:
        from .fees import profile_for

        try:
            for exchange in {i.split(":")[0] for i in selected}:
                profile = profile_for(
                    broker, exchange, now.date(), records=config.get("fee_profiles")
                )
                checks.append(
                    check(
                        "fees:" + exchange,
                        "AVAILABLE",
                        "Published estimate %s; contract-note reconciliation remains required"
                        % profile["id"],
                    )
                )
        except ValueError as error:
            checks.append(
                check("fees", "MISSING", str(error), "Import a reviewed dated fee profile")
            )
        snapshot = (
            read(workspace / "broker-snapshot.json")
            if (workspace / "broker-snapshot.json").exists()
            else {}
        )
        age = (
            (now - stamp(snapshot["checked_at"])).total_seconds()
            if snapshot.get("checked_at")
            else None
        )
        fresh = (
            (
                snapshot.get("status") == "AVAILABLE"
                or (
                    config.get("account_source") == "MANUAL_ATTESTATION"
                    and snapshot.get("status") == "MANUAL_ATTESTED"
                    and snapshot.get("source") == "USER_ATTESTATION"
                )
            )
            and snapshot.get("broker") == broker
            and age is not None
            and 0 <= age <= config.get("max_account_age_seconds", 120)
        )
        checks.append(
            check(
                "broker_account",
                snapshot["status"] if fresh else "STALE" if snapshot else "MISSING",
                "User-attested cash/exposure is fresh; not broker-verified"
                if fresh and config.get("account_source") == "MANUAL_ATTESTATION"
                else "Complete read-only account snapshot is fresh"
                if fresh
                else "A fresh complete account snapshot is required for exposure checks",
                None
                if fresh
                else "Confirm cash, holdings, positions and pending orders in Settings"
                if provider == "upstox" and config.get("account_source") == "MANUAL_ATTESTATION"
                else "Run sync",
            )
        )
    blocking = {
        "MISSING",
        "STALE",
        "UNVERIFIED",
        "ERROR",
        "AUTH_REQUIRED",
        "NOT_ENTITLED",
        "BLOCKED",
        "RATE_LIMITED",
    }
    status = (
        "DEMO"
        if demo
        else "NEEDS_ATTENTION"
        if any(c["state"] in blocking for c in checks)
        else "MARKET_CLOSED"
        if selected and closed_count == len(selected)
        else "DATA_READY"
    )
    return {
        "status": status,
        "broker": broker,
        "mode": "DEMO" if demo else "CONNECTED",
        "at": now.isoformat(),
        "checks": checks,
        "ready_for_live_trading": False,
        "note": "Data readiness is not a strategy endorsement, fill guarantee or live-order capability. Approximate-cost mode remains labeled until fee schedules are reviewed.",
    }


def sync(
    workspace,
    now,
    client=None,
    master_file=None,
    quotes_only=False,
    history_days=30,
    account_client=None,
):
    if not 1 <= history_days <= 365:
        raise ValueError("History days must be between 1 and 365")
    config = read(workspace / "config.json")
    if config.get("data_mode") == "DEMO" or "SYNTHETIC" in config.get("data_label", ""):
        raise ValueError(
            "Demo workspace never connects to broker services; create a separate connected workspace"
        )
    broker = config["broker"]
    provider = config.get("data_provider", broker)
    client = client or broker_client(workspace, provider)
    instruments = read(workspace / "instruments.json")
    results = []
    try:
        current_master = bool(instruments) and all(
            instrument_on(instruments, name, now.date(), strict=True).get("observed_on")
            == str(now.date())
            for name in config["watchlist"]
        )
    except (ValueError, KeyError):
        current_master = False
    if not quotes_only and (master_file or not current_master):
        if master_file and provider == "upstox":
            from .upstox import normalize_master

            incoming = normalize_master(read(master_file))
        else:
            incoming = import_master(master_file, broker) if master_file else client.master()
        instruments = merge_instruments(
            instruments,
            incoming,
            now.date(),
            "User-supplied %s master snapshot" % provider
            if master_file
            else "Official %s full instrument endpoint" % provider,
        )
        write(workspace / "instruments.json", instruments)
        results.append({"capability": "master", "state": "AVAILABLE", "instruments": len(incoming)})
    quotes = read(workspace / "quotes.json")
    if provider == "upstox":
        client.instruments = {
            name: instrument_on(instruments, name, now.date(), strict=True)
            for name in config["watchlist"]
        }
    manual_account = provider == "upstox" and config.get("account_source") == "MANUAL_ATTESTATION"
    if manual_account:
        results.append(
            {
                "capability": "account",
                "state": "MANUAL_REQUIRED",
                "detail": "Data-only connection; Groww/Zerodha exposure must be confirmed manually",
            }
        )
    else:
        try:
            source = account_client or (
                broker_client(workspace, broker) if provider != broker else client
            )
            snapshot = source.account_snapshot(instruments, now)
            if snapshot.get("status") != "AVAILABLE" or snapshot.get("broker") != broker:
                raise ValueError(
                    "Execution-account snapshot is incomplete or belongs to the wrong broker"
                )
            write(workspace / "broker-snapshot.json", snapshot)
            results.append({"capability": "account", "state": "AVAILABLE"})
        except (BrokerError, ValueError, KeyError, OSError, TypeError, ArithmeticError) as error:
            write(
                workspace / "broker-snapshot.json",
                {
                    "status": getattr(error, "state", "ERROR"),
                    "broker": broker,
                    "checked_at": now.isoformat(),
                },
            )
            results.append(
                {
                    "capability": "account",
                    "state": getattr(error, "state", "ERROR"),
                    "detail": str(error),
                }
            )
    try:
        batch = client.quotes(config["watchlist"])
        quotes.update(batch)
        write(workspace / "quotes.json", quotes)
    except (BrokerError, ValueError, KeyError, OSError) as error:
        results.append(
            {
                "capability": "quotes",
                "state": getattr(error, "state", "ERROR"),
                "detail": str(error),
            }
        )
        batch = {}
    cached = load_bars(workspace / "bars.csv") if (workspace / "bars.csv").exists() else []
    for instrument in config["watchlist"]:
        try:
            metadata = instrument_on(instruments, instrument, now.date(), strict=True)
            exchange, symbol = instrument.split(":")
            if instrument not in batch:
                raise ValueError("No successful quote in this sync batch")
            quote_age = (now - stamp(batch[instrument]["timestamp"])).total_seconds()
            quote_state = (
                "AVAILABLE" if 0 <= quote_age <= config["max_quote_age_seconds"] else "STALE"
            )
            results.append(
                {
                    "capability": "quote",
                    "instrument": instrument,
                    "state": quote_state,
                    "timestamp": batch[instrument]["timestamp"],
                }
            )
            if not quotes_only:
                start = (now - timedelta(days=history_days)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                prior = [
                    r["timestamp"]
                    for r in cached
                    if r["key"] == instrument and r["timestamp"] <= now
                ]
                if prior:
                    start = max(start, max(prior) - timedelta(minutes=5))
                rows = client.candles(
                    exchange,
                    symbol,
                    start.isoformat(),
                    now.isoformat(),
                    metadata.get("instrument_token"),
                    metadata.get("groww_symbol"),
                )
                save_candles(workspace / "bars.csv", rows, append=True)
                results.append(
                    {
                        "capability": "history",
                        "instrument": instrument,
                        "state": "AVAILABLE",
                        "candles": len(rows),
                        "requested_from": start.isoformat(),
                    }
                )
        except (BrokerError, ValueError, KeyError, OSError, ArithmeticError) as error:
            results.append(
                {
                    "instrument": instrument,
                    "state": getattr(error, "state", "ERROR"),
                    "detail": str(error),
                }
            )
    result = {
        "status": "SYNCED"
        if all(
            r["state"] == "AVAILABLE"
            or (
                manual_account
                and r.get("capability") == "account"
                and r["state"] == "MANUAL_REQUIRED"
            )
            for r in results
        )
        else "PARTIAL",
        "data_provider": provider,
        "execution_mode": config.get("execution_mode", "PAPER"),
        "broker": broker,
        "at": now.isoformat(),
        "results": results,
        "note": "Today's instrument snapshot never supplies historical tick/classification coverage for prior dates. Sync does not verify broker intraday eligibility.",
    }
    write(workspace / "sync-health.json", result)
    return result


def render(report):
    lines = ["India Trader — " + report.get("status", "STATUS")]
    if "checks" in report:
        for item in report["checks"]:
            lines.append("[%s] %s: %s" % (item["state"], item["name"], item["detail"]))
            if item.get("next_action"):
                lines.append("  Next: " + item["next_action"])
    else:
        for name in ("mode", "broker", "workspace", "watchlist", "storage", "next", "note"):
            if name in report:
                lines.append(
                    name.replace("_", " ").title()
                    + ": "
                    + (
                        ", ".join(report[name])
                        if isinstance(report[name], list)
                        else str(report[name])
                    )
                )
        for step in report.get("next_steps", []):
            lines.append("Next: " + step)
        for result in report.get("results", []):
            lines.append(
                "[%s] %s %s"
                % (
                    result["state"],
                    result.get("capability", "request"),
                    result.get("instrument", ""),
                )
            )
    if report.get("note") and "checks" in report:
        lines.append(report["note"])
    return "\n".join(lines)
