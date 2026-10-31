"""One CLI shared by the eleven skills. State is isolated in --workspace."""

import argparse
import json
import os
import shutil
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from . import __version__
from .auth import broker_client
from .brokers import import_master, save_candles
from .core import (
    IST,
    alerts,
    entry,
    fingerprint,
    load_bars,
    paper_close,
    paper_fill,
    plan,
    read,
    risk,
    session,
    simulate,
    size,
    stamp,
    ticket,
    write,
)
from .market import instrument_on, merge_instruments, resolve_session
from .research import earnings, fetch_feed, monitor, parse_feed

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = Path(__file__).resolve().parent / "templates"


@contextmanager
def locked(workspace):
    workspace.mkdir(parents=True, exist_ok=True)
    lock = workspace / ".lock"
    try:
        descriptor = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError(
            "Workspace busy. Remove .lock only after verifying no process uses it."
        ) from None
    try:
        os.write(descriptor, str(os.getpid()).encode())
        os.close(descriptor)
        yield
    finally:
        lock.unlink(missing_ok=True)


def parser():
    p = argparse.ArgumentParser(
        description="Indian cash-equity research, manual broker tickets and local paper trading"
    )
    p.add_argument("--workspace", type=Path, default=Path("trader"))
    p.add_argument(
        "--now",
        help="Timezone-aware ISO timestamp for reproducible research; actual IST clock by default",
    )
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)
    q = sub.add_parser(
        "validate", help="Run read-only live integration probes or show release evidence"
    )
    q.add_argument("view", choices=("broker", "readiness"))
    q.add_argument("--broker", choices=("groww", "zerodha"))
    q = sub.add_parser(
        "reconcile",
        help="Reconcile a complete supported contract note without changing paper balances",
    )
    q.add_argument(
        "--file", type=Path, required=True, help="Reviewed normalized daily contract-note JSON"
    )
    q.add_argument(
        "--source-file",
        type=Path,
        help="Original local contract note; hashed privately, never uploaded",
    )
    q.add_argument("--tolerance", default="0.10")
    q = sub.add_parser(
        "context", help="Collect official corporate feeds and optional broker ETF proxies"
    )
    q.add_argument("view", choices=("refresh", "show"))
    q.add_argument("--public-only", action="store_true")
    q.add_argument("--force", action="store_true")
    q = sub.add_parser(
        "observe", help="Resume actual-market observation until the distinct-session target"
    )
    q.add_argument("view", choices=("run", "report"))
    q.add_argument("--sessions", type=int, default=20)
    q.add_argument("--interval", type=int, default=30)
    q.add_argument("--once", action="store_true")
    q = sub.add_parser(
        "serve", help="Open the local daily desk; optional foreground broker collection"
    )
    q.add_argument("--port", type=int, default=8765)
    q.add_argument("--demo", action="store_true")
    q.add_argument("--collect", action="store_true")
    q.add_argument("--interval", type=int, default=30)
    q = sub.add_parser("desk", help="Refresh the session desk or read its decision journal")
    q.add_argument("view", choices=("today", "review", "validation"), default="today", nargs="?")
    q = sub.add_parser("decision", help="Record a local paper decision or pause new ideas")
    q.add_argument("action", choices=("track", "close", "save", "skip", "note", "pause", "resume"))
    q.add_argument("--id")
    q.add_argument("--instrument")
    q.add_argument("--reason", default="")
    q = sub.add_parser(
        "fees", help="Explain broker charges and optionally reconcile an actual exported total"
    )
    q.add_argument("--broker", choices=("groww", "zerodha"), required=True)
    q.add_argument("--exchange", choices=("NSE", "BSE"), default="NSE")
    q.add_argument("--entry", required=True)
    q.add_argument("--exit", required=True)
    q.add_argument("--quantity", type=int, required=True)
    q.add_argument("--day")
    q.add_argument("--tick", default="0.05")
    q.add_argument("--actual-total")
    q = sub.add_parser(
        "replay", help="Run a deterministic chronological ORB evaluation with explicit exclusions"
    )
    q.add_argument("instrument")
    q.add_argument("--split", default="0.70")
    q = sub.add_parser(
        "filings", help="Import sourced events or supported three-month XBRL financials"
    )
    q.add_argument("action", choices=("import", "xbrl", "poll"))
    q.add_argument("--file", type=Path)
    q.add_argument("--feed")
    q.add_argument("--instrument")
    q.add_argument("--source")
    q.add_argument("--published-at")
    q.add_argument("--basis", choices=("standalone", "consolidated"))
    q = sub.add_parser(
        "confirm-account",
        help="Manually attest execution-account cash and all exposure; never broker-verified",
    )
    q.add_argument("--cash", required=True)
    q.add_argument(
        "--exposed",
        default="",
        help="All holdings, positions and pending-order instruments, comma-separated",
    )
    q.add_argument("--reviewed", action="store_true", required=True)
    q = sub.add_parser("setup", help="Configure a personal workspace without editing JSON")
    q.add_argument(
        "--data-provider",
        choices=("upstox",),
        help="Free data-only connection; --broker remains manual execution broker",
    )
    q.add_argument(
        "--account-source",
        choices=("broker", "manual"),
        help="Read execution-broker exposure or explicitly attest it manually",
    )
    q.add_argument("--demo", action="store_true")
    q.add_argument("--interactive", action="store_true")
    q.add_argument("--broker", choices=("groww", "zerodha"))
    q.add_argument("--watchlist")
    q.add_argument("--capital")
    q.add_argument("--max-loss")
    q.add_argument("--daily-risk")
    q.add_argument("--json", action="store_true")
    for command in ("doctor", "status"):
        q = sub.add_parser(
            command, help="Show actionable workspace health without exposing credentials"
        )
        q.add_argument(
            "--online",
            action="store_true",
            help="Explicitly probe read-only broker profile and quote access",
        )
        q.add_argument("--json", action="store_true")
    q = sub.add_parser(
        "auth", help="Connect using hidden prompts and macOS Keychain, or remove stored credentials"
    )
    q.add_argument("--broker", choices=("groww", "zerodha", "upstox"), required=True)
    q.add_argument("--flow", choices=("token", "login"), default="token")
    q.add_argument("--clear", action="store_true")
    q.add_argument("--json", action="store_true")
    q = sub.add_parser(
        "sync", help="Download instrument master, quotes and history using official read-only APIs"
    )
    q.add_argument("--master-file", type=Path)
    q.add_argument("--quotes-only", action="store_true")
    q.add_argument("--history-days", type=int, default=30)
    q.add_argument("--json", action="store_true")
    q = sub.add_parser(
        "market", help="Inspect market phases and explicitly import reviewed eligibility/policies"
    )
    q.add_argument(
        "action",
        choices=("show", "verify-instrument", "set-cutoff", "load-calendar", "load-instruments"),
    )
    q.add_argument("--instrument")
    q.add_argument("--day")
    q.add_argument("--session-class", choices=("CAS", "NON_CAS"))
    q.add_argument("--intraday", choices=("yes", "no"))
    q.add_argument("--source")
    q.add_argument("--file", type=Path)
    q.add_argument("--broker", choices=("groww", "zerodha"))
    q.add_argument("--valid-through")
    q.add_argument("--cutoff")
    q.add_argument("--exchange", choices=("NSE", "BSE"), default="NSE")
    q = sub.add_parser(
        "init", help="Create state without overwriting; --demo installs synthetic fixtures"
    )
    q.add_argument("--demo", action="store_true")
    q = sub.add_parser("data", help="Official broker quotes, candles or instrument-master import")
    q.add_argument("action", choices=("quote", "candles", "master"))
    q.add_argument("--broker", choices=("zerodha", "groww"), required=True)
    q.add_argument("--instrument", default="NSE:RELIANCE")
    q.add_argument("--file", type=Path)
    q.add_argument("--start")
    q.add_argument("--end")
    q.add_argument("--out", type=Path)
    q.add_argument(
        "--append",
        action="store_true",
        help="Merge candles by exchange, symbol and timestamp; replace overlapping observations",
    )
    for command in ("scan", "entry", "exit", "simulate", "budget", "risk", "alerts"):
        q = sub.add_parser(command)
        if command in ("entry", "exit"):
            q.add_argument("instrument")
        if command == "exit":
            q.add_argument("--target-r", default="2")
        if command == "simulate":
            q.add_argument("--replays", type=int, default=10000)
            q.add_argument("--seed", type=int, default=19)
    q = sub.add_parser("broker", help="Draft manual tickets or operate the local paper journal")
    q.add_argument("action", choices=("ticket", "paper-fill", "paper-close", "journal"))
    q.add_argument("--broker", choices=("groww", "zerodha"), default="zerodha")
    q.add_argument("--instrument")
    for command in ("news", "disclosures"):
        q = sub.add_parser(command)
        source = q.add_mutually_exclusive_group(required=True)
        source.add_argument("--feed", help="HTTPS RSS/Atom URL")
        source.add_argument(
            "--file", type=Path, help="Saved .xml RSS/Atom or normalized .json items"
        )
        q.add_argument("--hours", type=float, default=24)
        q.add_argument(
            "--new-only",
            action="store_true",
            help="Deduplicate against this workspace's prior delivered items",
        )
    q = sub.add_parser("analyst")
    q.add_argument("--file", type=Path, required=True, help="Sourced quarterly financial JSON")
    q = sub.add_parser(
        "watch", help="Bounded foreground polling; stops on errors, never places trades"
    )
    q.add_argument("mode", choices=("entry", "alerts", "news", "disclosures"))
    q.add_argument("--broker", choices=("groww", "zerodha"))
    q.add_argument("--instrument")
    q.add_argument("--feed")
    q.add_argument("--file", type=Path)
    q.add_argument("--every", type=int, default=30)
    q.add_argument("--polls", type=int, default=20)
    return p


def execute(a):
    w = a.workspace.resolve()
    now = stamp(a.now) if a.now else datetime.now(IST)
    if a.command in ("validate", "reconcile", "context", "observe"):
        from .store import Store

        if a.now:
            raise ValueError("Evidence and observation commands use the actual clock; omit --now")
        if a.command == "validate":
            from .verification import readiness, validate_broker

            return validate_broker(w, a.broker) if a.view == "broker" else readiness(w)
        if a.command == "reconcile":
            from .reconciliation import import_note

            config = read(w / "config.json") if (w / "config.json").exists() else {}
            return import_note(
                w, read(a.file), a.source_file, config.get("fee_profiles"), a.tolerance
            )
        if a.command == "context":
            from .context import collect, snapshot

            return (
                collect(w, a.public_only, force=a.force)
                if a.view == "refresh"
                else snapshot(Store(w))
            )
        from .observation import run
        from .validation import scorecard

        return (
            run(w, a.sessions, a.interval, a.once)
            if a.view == "run"
            else scorecard(Store(w), a.sessions)
        )
    if a.command in ("desk", "decision", "replay", "filings", "fees"):
        from . import desk
        from .store import Store

        if a.command == "fees":
            from .fees import breakeven, estimate, profile_for, reconcile

            profile = profile_for(a.broker, a.exchange, a.day or now.date())
            result = estimate(
                profile,
                [{"price": a.entry, "quantity": a.quantity}],
                [{"price": a.exit, "quantity": a.quantity}],
            )
            result["breakeven_inr"] = breakeven(profile, a.entry, a.quantity, a.tick)
            if a.actual_total is not None:
                result["reconciliation"] = reconcile(result, a.actual_total)
            return result
        store = Store(w)
        if a.command == "desk":
            if a.view == "today":
                return desk.refresh(w, now)
            if a.view == "review":
                return store.review()
            from .validation import scorecard

            return scorecard(store)
        if a.command == "decision":
            return desk.act(w, a.action, now, a.id, a.reason, a.instrument)
        if a.command == "replay":
            from .replay import run

            result = run(
                load_bars(w / "bars.csv"),
                a.instrument,
                read(w / "calendar.json"),
                desk.configuration(w),
                now,
                a.split,
            )
            store.put("latest_replay", result)
            runs = store.get("research_runs", [])
            if not any(r["run_id"] == result["run_id"] for r in runs):
                runs.append(
                    {
                        k: result[k]
                        for k in (
                            "run_id",
                            "engine",
                            "instrument",
                            "as_of",
                            "summary",
                            "holdout",
                            "data_provenance",
                        )
                    }
                )
            store.put("research_runs", runs)
            write(w / "replay.json", result)
            return result
        from .filings import extract_xbrl, normalize_events

        if a.action == "xbrl":
            if not all((a.file, a.instrument, a.source, a.published_at, a.basis)):
                raise ValueError(
                    "XBRL requires --file, --instrument, --source URL, --published-at and --basis"
                )
            result = extract_xbrl(
                a.file.read_bytes(), a.instrument, a.source, a.published_at, a.basis
            )
            if stamp(a.published_at) > now:
                raise ValueError("Filing publication is after the research clock")
            write(w / "extracted-financials.json", result)
            return {
                "quarters": result,
                "file": str(w / "extracted-financials.json"),
                "next": "Review field evidence, then pass this file to analyst",
            }
        if a.action == "poll":
            if not a.feed:
                raise ValueError("Specify --feed with a sourced HTTPS RSS/Atom URL")
            rows = fetch_feed(a.feed)
            config = read(w / "config.json")
            rows = monitor(rows, now, 48, config.get("watchlist_aliases"))["items"]
        else:
            if not a.file:
                raise ValueError("Specify --file with normalized sourced events")
            rows = read(a.file)
        imported = normalize_events(rows, now)
        result = store.filings(imported, now.isoformat())
        return {
            "imported": len(imported),
            "stored": len(result),
            "items": result,
            "coverage": "UNVERIFIED",
        }
    if a.command == "confirm-account":
        if a.now:
            raise ValueError("Manual account confirmation uses the actual clock")
        from .manual import confirm_account

        return confirm_account(w, a.cash, a.exposed, now, a.reviewed)
    if a.command in ("setup", "doctor", "status", "auth", "sync", "market"):
        from . import onboarding

        if a.command == "setup":
            return (
                onboarding.interactive_setup(
                    w, data_provider=a.data_provider, account_source=a.account_source
                )
                if a.interactive
                else onboarding.setup(
                    w,
                    a.broker,
                    a.watchlist,
                    a.capital,
                    a.max_loss,
                    a.daily_risk,
                    a.demo,
                    a.data_provider,
                    a.account_source,
                )
            )
        if a.command in ("doctor", "status"):
            if a.online and a.now:
                raise ValueError("Online checks use the actual clock; omit --now")
            return onboarding.doctor(w, now, a.online)
        if a.command == "auth":
            if not sys.stdin.isatty():
                raise ValueError(
                    "Run auth directly in a local terminal for hidden credential entry; never pass secrets as arguments"
                )
            from .auth import connect

            return connect(w, a.broker, a.flow, a.clear)
        if a.command == "sync":
            if a.now:
                raise ValueError(
                    "Sync records current provider observations; omit --now and use explicit dated imports for historical metadata"
                )
            return onboarding.sync(
                w,
                now,
                master_file=a.master_file,
                quotes_only=a.quotes_only,
                history_days=a.history_days,
            )
        return market_command(a, w, now)
    if a.command == "init":
        for name in ("config", "calendar", "account", "quotes", "instruments"):
            if (w / (name + ".json")).exists():
                raise ValueError("Workspace already initialized; choose another directory")
        if a.demo:
            for path in (TEMPLATES / "demo").iterdir():
                if path.is_file():
                    shutil.copy2(path, w / path.name)
        else:
            shutil.copy2(TEMPLATES / "config.json", w / "config.json")
            write(
                w / "calendar.json",
                {
                    "source": "Add verified exchange sessions; absent dates are blocked",
                    "sessions": {},
                },
            )
            write(w / "instruments.json", {})
            write(w / "quotes.json", {})
            write(
                w / "account.json",
                {"cash_inr": read(w / "config.json")["capital_inr"], "positions": {}, "trades": []},
            )
        return {
            "workspace": str(w),
            "demo": a.demo,
            "message": "Synthetic demo only; use --now 2026-10-19T09:35:00+05:30"
            if a.demo
            else "Add verified calendar, instruments and bars before research",
        }
    if a.command == "data":
        if a.action == "master":
            if not a.file:
                raise ValueError(
                    "Supply --file downloaded from official broker instrument endpoint"
                )
            result = import_master(a.file, a.broker)
            calendar = read(w / "calendar.json")
            if calendar.get("schema_version") == 2:
                if a.now:
                    raise ValueError(
                        "Do not backdate a current master with --now; use market load-instruments for sourced historical versions"
                    )
                result = merge_instruments(
                    read(w / "instruments.json"),
                    result,
                    now.date(),
                    "User-supplied %s CSV" % a.broker,
                )
            write(w / "instruments.json", result)
            return {
                "instruments": len(result),
                "broker": a.broker,
                "warning": "Review trading restrictions, series eligibility and today's tick sizes before using",
            }
        exchange, symbol = a.instrument.split(":")
        broker = broker_client(w, a.broker)
        if a.action == "quote":
            result = broker.quote(exchange, symbol)
            quotes = read(w / "quotes.json") if (w / "quotes.json").exists() else {}
            quotes.update(result)
            write(w / "quotes.json", quotes)
            return result
        if not a.start or not a.end:
            raise ValueError("Candles require --start and --end with timezone offsets")
        meta = instrument_on(
            read(w / "instruments.json"),
            a.instrument,
            now.date(),
            strict=read(w / "calendar.json").get("schema_version") == 2,
        )
        result = broker.candles(
            exchange, symbol, a.start, a.end, meta.get("instrument_token"), meta.get("groww_symbol")
        )
        destination = a.out or w / "bars.csv"
        destination.parent.mkdir(parents=True, exist_ok=True)
        save_candles(destination, result, a.append)
        return {"candles_fetched": len(result), "file": str(destination), "merged": a.append}
    if a.command in ("news", "disclosures"):
        if a.feed:
            rows = fetch_feed(a.feed)
        elif a.file.suffix.lower() == ".json":
            rows = read(a.file)
        else:
            rows = parse_feed(a.file.read_bytes(), str(a.file))
        aliases = read(w / "config.json").get("watchlist_aliases", {})
        state_path = w / (a.command + "-seen.json")
        seen = read(state_path) if a.new_only and state_path.exists() else []
        result = monitor(rows, now, a.hours, aliases, a.command == "disclosures", seen)
        if a.new_only:
            # Bounded persistent cache. Repeat polls older than this window may repeat items.
            write(state_path, (seen + [r["id"] for r in result["items"]])[-10000:])
        write(w / (a.command + ".json"), result)
        return result
    if a.command == "analyst":
        rows = [r for r in read(a.file) if stamp(r["published_at"]) <= now]
        result = earnings(rows)
        write(w / "earnings.json", result)
        return result
    from .desk import configuration
    from .store import Store

    config = configuration(w)
    calendar = read(w / "calendar.json")
    account = Store(w).account() if (w / "desk.sqlite3").exists() else read(w / "account.json")
    quotes = read(w / "quotes.json")
    if a.command in ("scan", "entry", "exit", "simulate"):
        bars = load_bars(w / "bars.csv")
        if a.command == "scan":
            results = []
            for instrument in sorted({r["key"] for r in bars}):
                try:
                    results.append(
                        entry(
                            bars,
                            instrument,
                            now,
                            calendar,
                            config["instruments"],
                            config.get("broker"),
                        )
                    )
                except ValueError as exc:
                    results.append(
                        {"instrument": instrument, "status": "unavailable", "reason": str(exc)}
                    )
            write(w / "scan.json", results)
            return results
        if a.command in ("entry", "exit"):
            result = entry(
                bars, a.instrument, now, calendar, config["instruments"], config.get("broker")
            )
            if a.command == "exit":
                result = plan(
                    result,
                    instrument_on(
                        config["instruments"],
                        a.instrument,
                        now.date(),
                        strict=calendar.get("schema_version") == 2,
                    )["tick_size"],
                    a.target_r,
                )
                write(w / "plan.json", result)
            else:
                write(w / "entry.json", result)
            return result
        p = read(w / "plan.json")
        if stamp(p["entry_time"]) > now:
            raise ValueError("Cannot simulate a plan whose entry is after the research clock")
        result = simulate(p, bars, calendar, config, a.replays, a.seed)
        write(w / "simulation.json", result)
        return result
    if a.command == "budget":
        result = size(read(w / "plan.json"), config, account)
        write(w / "order.json", result)
        return result
    if a.command == "risk":
        result = risk(read(w / "order.json"), config, account, quotes, calendar, now)
        write(w / "risk.json", result)
        return result
    if a.command == "alerts":
        p = read(w / "plan.json")
        current = alerts(p, quotes, now, int(config["max_quote_age_seconds"]))
        state = read(w / "alerts-seen.json") if (w / "alerts-seen.json").exists() else []
        prefix = fingerprint(p)
        events = [
            {"event": event, "instrument": p["instrument"], "at": now.isoformat()}
            for event in current
            if prefix + event not in state
        ]
        write(w / "alerts-seen.json", (state + [prefix + event for event in current])[-1000:])
        return {
            "new_events": events,
            "active_conditions": current,
            "warning": "One poll only; no background service or automatic exit",
        }
    if a.command == "broker":
        if a.action == "journal":
            return account
        if a.action == "paper-close":
            if not a.instrument:
                raise ValueError("Specify --instrument to close a local paper position")
            result = paper_close(
                a.instrument, account, quotes, now, int(config["max_quote_age_seconds"])
            )
            Store(w).commit_account(account, result, "PAPER_CLOSE", now.isoformat())
            return result
        order = read(w / "order.json")
        if a.action == "ticket":
            verdict = risk(order, config, account, quotes, calendar, now)
            if verdict["status"] != "PASS":
                raise ValueError("Risk BLOCK: " + "; ".join(verdict["reasons"]))
            result = ticket(order, a.broker)
            write(w / (a.broker + "-ticket.json"), result)
            return result
        result = paper_fill(order, config, account, quotes, calendar, now)
        Store(w).commit_account(account, result, "PAPER_FILL", now.isoformat())
        return result
    raise ValueError("Unhandled command")


def market_command(a, w, now):
    calendar = read(w / "calendar.json")
    instruments = read(w / "instruments.json")
    config = read(w / "config.json")
    broker = a.broker or config.get("broker")
    day = a.day or str(now.date())
    datetime.fromisoformat(day)
    if a.action == "show":
        if not a.instrument:
            raise ValueError("Specify --instrument EXCHANGE:SYMBOL")
        return resolve_session(
            calendar, a.instrument.split(":")[0], day, a.instrument, instruments, broker
        )
    if a.action in ("load-calendar", "load-instruments"):
        if not a.file:
            raise ValueError("Specify --file with sourced, reviewed JSON")
        incoming = read(a.file)
        if a.action == "load-calendar":
            if incoming.get("schema_version") != 2 or not all(
                k in incoming for k in ("days", "policies", "reviewed_on")
            ):
                raise ValueError("Expected a schema-v2 sourced calendar")
            for record in incoming["days"].values():
                if not record.get("source") or record.get("status") not in (
                    "OPEN",
                    "CLOSED",
                    "UNVERIFIED",
                ):
                    raise ValueError("Every calendar date needs source and explicit status")
            target, original = "calendar.json", calendar
        else:
            for instrument, record in incoming.items():
                versions = record.get("versions", [])
                if not versions:
                    raise ValueError("Historical imports need explicit dated versions")
                for version in versions:
                    instrument_on(
                        {instrument: record}, instrument, version["valid_from"], strict=True
                    )
            target, original = "instruments.json", instruments
        backup = w / "backups" / (target + "." + fingerprint(original)[:16])
        write(backup, original)
        write(w / target, incoming)
        return {
            "status": "IMPORTED",
            "file": target,
            "backup": str(backup),
            "note": "Source assertions preserved; run doctor to evaluate coverage",
        }
    if not a.source or not a.source.startswith("https://"):
        raise ValueError("Provide --source with the HTTPS page/notice you reviewed")
    if a.action == "verify-instrument":
        if not a.instrument or not a.intraday:
            raise ValueError(
                "Specify --instrument and --intraday yes|no after checking the selected broker"
            )
        metadata = instrument_on(instruments, a.instrument, day, strict=True)
        if a.session_class:
            metadata["session_class"] = a.session_class
        if metadata.get("session_class") not in ("CAS", "NON_CAS"):
            raise ValueError(
                "Session class remains unknown; provide --session-class after verifying it"
            )
        metadata.update(
            intraday_allowed=a.intraday == "yes",
            eligibility_source=a.source,
            eligibility_broker=broker,
            eligibility_reviewed_on=day,
        )
        incoming = merge_instruments(instruments, {a.instrument: metadata}, day, metadata["source"])
        write(w / "instruments.json", incoming)
        return {
            "status": "RECORDED",
            "instrument": a.instrument,
            "note": "User-reviewed eligibility assertion with source; not an automatic exchange verification",
        }
    if not a.session_class or not a.cutoff or not broker:
        raise ValueError("Provide --broker, --session-class and --cutoff HH:MM:SS")
    end = a.valid_through or day
    if end < day:
        raise ValueError("Validity end precedes start")
    stamp(day + "T" + a.cutoff + "+05:30")
    record = {
        "broker": broker,
        "exchange": a.exchange,
        "session_class": a.session_class,
        "cutoff": a.cutoff,
        "valid_from": day,
        "valid_to": end,
        "published_on": day,
        "reviewed_on": str(now.date()),
        "source": a.source,
    }
    for existing in calendar.get("broker_cutoffs", []):
        if all(existing[k] == record[k] for k in ("broker", "exchange", "session_class")) and max(
            existing["valid_from"], day
        ) <= min(existing.get("valid_to") or "9999-12-31", end):
            raise ValueError(
                "Cutoff overlaps an existing policy; import an explicitly revised calendar instead"
            )
    calendar.setdefault("broker_cutoffs", []).append(record)
    write(w / "calendar.json", calendar)
    return {"status": "RECORDED", "policy": record}


def watch(a):
    if a.now:
        raise ValueError(
            "watch uses the current clock; --now is only for individual research commands"
        )
    if not 5 <= a.every <= 3600 or not 1 <= a.polls <= 10000 or a.every * (a.polls - 1) > 86400:
        raise ValueError("Choose 5..3600 seconds, 1..10000 polls, and at most 24 hours total")
    if a.mode == "entry" and not a.instrument:
        raise ValueError("Entry watch requires --instrument")
    if a.mode in ("news", "disclosures") and bool(a.feed) == bool(a.file):
        raise ValueError("News/disclosure watch requires exactly one of --feed and --file")
    for poll in range(a.polls):
        with locked(a.workspace.resolve()):
            instrument = a.instrument
            if a.mode == "alerts":
                instrument = read(a.workspace / "plan.json")["instrument"]
                if a.instrument and a.instrument != instrument:
                    raise ValueError("Alert instrument must match plan.json")
            if a.broker and a.mode in ("entry", "alerts"):
                execute(
                    argparse.Namespace(
                        workspace=a.workspace,
                        now=None,
                        command="data",
                        action="quote",
                        broker=a.broker,
                        instrument=instrument,
                    )
                )
                if a.mode == "entry":
                    now = datetime.now(IST)
                    config = read(a.workspace / "config.json")
                    s = session(
                        read(a.workspace / "calendar.json"),
                        instrument.split(":")[0],
                        now.date(),
                        instrument,
                        read(a.workspace / "instruments.json"),
                        config.get("broker"),
                    )
                    execute(
                        argparse.Namespace(
                            workspace=a.workspace,
                            now=None,
                            command="data",
                            action="candles",
                            broker=a.broker,
                            instrument=instrument,
                            start=s["open"].isoformat(),
                            end=now.isoformat(),
                            out=None,
                            append=True,
                        )
                    )
            result = execute(
                argparse.Namespace(
                    workspace=a.workspace,
                    now=None,
                    command=a.mode,
                    instrument=instrument,
                    feed=a.feed,
                    file=a.file,
                    hours=24,
                    new_only=True,
                )
            )
        print(
            json.dumps({"poll": poll + 1, "mode": a.mode, "result": result}, default=str),
            flush=True,
        )
        if a.mode == "entry" and result.get("status") in ("triggered", "expired"):
            break
        if poll + 1 < a.polls:
            time.sleep(a.every)
    return 0


def main(argv=None):
    a = parser().parse_args(argv)
    try:
        if a.command == "serve":
            if a.now:
                raise ValueError(
                    "Serve uses the current clock; --demo provides an explicitly synthetic replay clock"
                )
            from .server import serve

            serve(a.workspace.resolve(), a.port, a.demo, a.collect, a.interval)
            return 0
        if a.command == "watch":
            return watch(a)
        if a.command == "observe" and a.view == "run":
            result = execute(a)
        else:
            with locked(a.workspace.resolve()):
                result = execute(a)
        if a.command in ("setup", "doctor", "status", "auth", "sync") and not a.json:
            from .onboarding import render

            print(render(result))
        else:
            print(json.dumps(result, indent=2, default=str))
        return (
            2
            if isinstance(result, dict)
            and result.get("status") in ("BLOCK", "NEEDS_SETUP", "NEEDS_ATTENTION", "PARTIAL")
            else 0
        )
    except (ValueError, KeyError, OSError, TypeError, ArithmeticError) as exc:
        print(json.dumps({"error": str(exc), "command": a.command}), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(json.dumps({"status": "stopped", "command": a.command}), file=sys.stderr)
        return 130
