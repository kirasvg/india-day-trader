"""Resumable foreground observation campaign using real clocks and read-only sync."""

import json
import os
import sys
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from time import monotonic

from .auth import broker_client
from .core import IST, read
from .market import resolve_session
from .store import Store
from .validation import record, scorecard


def window(workspace, now):
    """No default weekday calendar, no guessed special-session hours."""
    config = read(workspace / "config.json")
    calendar = read(workspace / "calendar.json")
    instruments = read(workspace / "instruments.json")
    sessions = []
    for instrument in config["watchlist"]:
        try:
            sessions.append(
                resolve_session(
                    calendar,
                    instrument.split(":")[0],
                    now.date(),
                    instrument,
                    instruments,
                    config["broker"],
                )
            )
        except ValueError as error:
            if str(error).startswith("Session CLOSED"):
                continue
            return {"status": "UNVERIFIED", "detail": str(error)}
    if not sessions:
        return {"status": "CLOSED"}
    opening = min(s["open"] for s in sessions) - timedelta(minutes=10)
    closing = max(s["close"] for s in sessions) + timedelta(minutes=5)
    return {
        "status": "COLLECT" if opening <= now <= closing else "WAITING",
        "opens_at": opening.isoformat(),
        "ends_at": closing.isoformat(),
    }


@contextmanager
def campaign_lock(workspace):
    path = workspace / ".observer.lock"
    try:
        descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise ValueError(
            "An observer lock exists; verify its PID is no longer active before removing it"
        ) from None
    try:
        os.write(descriptor, str(os.getpid()).encode())
        os.close(descriptor)
        yield
    finally:
        path.unlink(missing_ok=True)


def cycle(workspace, interval=30):
    """Exactly one actual-clock collection; failures are observations too."""
    from . import desk
    from .cli import locked
    from .onboarding import sync

    started = monotonic()
    store = Store(workspace)
    now = datetime.now(IST)
    with locked(workspace):
        try:
            result = sync(workspace, now)
            observed = desk.refresh(workspace, datetime.now(IST))
            healthy = result["status"] == "SYNCED"
            detail = None if healthy else result["results"]
        except (ValueError, KeyError, OSError, ArithmeticError) as error:
            healthy = False
            detail = str(error)
            try:
                observed = desk.refresh(workspace, datetime.now(IST))
            except (ValueError, KeyError, OSError, ArithmeticError):
                observed = {
                    "origin": "BROKER_RESEARCH",
                    "watchlist": [],
                    "processing_ms": 0,
                    "broker_account": {},
                }
        now = datetime.now(IST)
        config = desk.configuration(workspace)
        record(
            store,
            observed,
            config,
            read(workspace / "calendar.json"),
            now,
            interval,
            healthy=healthy,
            issue=detail,
            cycle_ms=round((monotonic() - started) * 1000, 2),
        )
        state = {
            "status": "AVAILABLE" if healthy else "DEGRADED",
            "at": now.isoformat(),
            "transport": "Read-only REST observation campaign",
            "interval_seconds": interval,
            "cycle_ms": round((monotonic() - started) * 1000, 2),
        }
        store.put("collector", state)
        return state


def context_worker(workspace, stop):
    from .context import collect

    store = Store(workspace)
    while not stop.is_set():
        try:
            if window(workspace, datetime.now(IST))["status"] == "COLLECT":
                collect(workspace)
        except (ValueError, KeyError, OSError, ArithmeticError) as error:
            store.put("context_error", {"at": datetime.now(IST).isoformat(), "detail": str(error)})
        stop.wait(60)


def run(workspace, target=20, interval=30, once=False, stop=None):
    workspace = Path(workspace)
    if not 5 <= interval <= 300 or not 1 <= target <= 250:
        raise ValueError("Use an interval of 5..300 seconds and target of 1..250 distinct sessions")
    config = read(workspace / "config.json")
    if config.get("data_mode") != "CONNECTED":
        raise ValueError("Only a connected workspace can run an actual observation campaign")
    # Preflight credentials without printing them; no repeated unauthenticated network traffic.
    broker_client(workspace, config["broker"]).headers()
    store = Store(workspace)
    stop = stop or threading.Event()
    bootstrapped_day = None
    failures = 0
    last_notice = None
    with campaign_lock(workspace):
        context_stop = threading.Event()
        context_thread = None
        if not once:
            context_thread = threading.Thread(
                target=context_worker, args=(workspace, context_stop), daemon=True
            )
            context_thread.start()
        try:
            while not stop.is_set():
                if scorecard(store, target)["qualified_sessions"] >= target:
                    store.put(
                        "observer",
                        {
                            "status": "TARGET_REACHED",
                            "target": target,
                            "at": datetime.now(IST).isoformat(),
                        },
                    )
                    return scorecard(store, target)
                started = monotonic()
                now = datetime.now(IST)
                state = window(workspace, now)
                if state["status"] == "UNVERIFIED" and bootstrapped_day != str(now.date()):
                    # Load today's metadata once, then resolve the dated window again.
                    from .cli import locked
                    from .onboarding import sync

                    try:
                        with locked(workspace):
                            sync(workspace, now)
                        bootstrapped_day = str(now.date())
                        state = window(workspace, datetime.now(IST))
                    except (ValueError, KeyError, OSError, ArithmeticError) as error:
                        state = {"status": "DEGRADED", "detail": str(error)}
                        store.event(
                            "OBSERVATION_BOOTSTRAP_ERROR",
                            state,
                            datetime.now(IST).isoformat(),
                            "BROKER_RESEARCH",
                        )
                if state["status"] == "COLLECT":
                    state = cycle(workspace, interval)
                progress = dict(
                    state,
                    target=target,
                    at=datetime.now(IST).isoformat(),
                    qualified_sessions=scorecard(store, target)["qualified_sessions"],
                )
                store.put("observer", progress)
                notice = (state["status"], str(now.date()), progress["qualified_sessions"])
                if notice != last_notice:
                    print(json.dumps(progress), file=sys.stderr, flush=True)
                    last_notice = notice
                if once:
                    return store.get("observer")
                failures = failures + 1 if state["status"] == "DEGRADED" else 0
                wait = (
                    min(60, interval * (2 ** min(failures, 4)))
                    if state["status"] in ("AVAILABLE", "DEGRADED")
                    else 60
                )
                stop.wait(max(0.05, wait - (monotonic() - started)))
        except KeyboardInterrupt:
            pass
        finally:
            context_stop.set()
            if context_thread:
                context_thread.join(timeout=2)
            store.put(
                "collector",
                {
                    "status": "STOPPED",
                    "at": datetime.now(IST).isoformat(),
                    "transport": "Read-only observation campaign",
                },
            )
    return scorecard(store, target)
