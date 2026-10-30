"""Loopback-only daily desk. All broker traffic remains read-only."""

import json
import secrets
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlparse

from . import desk
from .core import IST, closed_bars, load_bars, read, stamp
from .filings import normalize_events
from .onboarding import doctor, setup, sync
from .replay import run as replay
from .store import Store
from .validation import scorecard

WEB = Path(__file__).resolve().parent / "web"


def collector(workspace, stop, interval):
    from .observation import run

    try:
        run(workspace, target=20, interval=interval, stop=stop)
    except (ValueError, KeyError, OSError, ArithmeticError) as error:
        Store(workspace).put(
            "collector",
            {"status": "ERROR", "at": datetime.now(IST).isoformat(), "detail": str(error)},
        )


class DeskServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, workspace, port=8765, demo=False):
        self.workspace = Path(workspace).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        if demo and not (self.workspace / "config.json").exists():
            setup(self.workspace, demo=True)
        self.demo = demo
        if demo and read(self.workspace / "config.json").get("data_mode") != "DEMO":
            raise ValueError(
                "A frozen demonstration clock cannot be used with a connected workspace"
            )
        self.token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), Handler)
        self.origin = "http://127.0.0.1:" + str(self.server_port)
        self.stop_event = threading.Event()

    def clock(self):
        return stamp("2026-10-19T09:35:00+05:30") if self.demo else datetime.now(IST)


class Handler(BaseHTTPRequestHandler):
    @property
    def desk_server(self) -> DeskServer:
        return cast(DeskServer, self.server)

    server_version = "IndiaDesk/0.2"

    def log_message(self, format, *args):
        pass  # URLs, payloads and user financial state are not written into access logs.

    def trusted(self, writing=False):
        if self.headers.get("Host") != "127.0.0.1:" + str(self.desk_server.server_port):
            return False
        if self.headers.get("Origin") not in (None, self.desk_server.origin):
            return False
        if self.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
            return False
        return not writing or secrets.compare_digest(
            self.headers.get("X-Desk-Token", ""), self.desk_server.token
        )

    def send(self, status, value, kind="application/json; charset=utf-8"):
        raw = value if isinstance(value, bytes) else json.dumps(value, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        )
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self):
        self.send(403, {"error": "Cross-origin access is disabled"})

    def do_GET(self):
        if not self.trusted():
            self.send(403, {"error": "Loopback same-origin access required"})
            return
        parsed = urlparse(self.path)
        files = {
            "/": ("index.html", "text/html; charset=utf-8"),
            "/app.js": ("app.js", "text/javascript; charset=utf-8"),
            "/style.css": ("style.css", "text/css; charset=utf-8"),
        }
        if parsed.path in files:
            name, kind = files[parsed.path]
            self.send(200, (WEB / name).read_bytes(), kind)
            return
        try:
            w, now = self.desk_server.workspace, self.desk_server.clock()
            if parsed.path == "/api/bootstrap":
                self.send(
                    200,
                    {
                        "token": self.desk_server.token,
                        "configured": (w / "config.json").exists(),
                        "demo": self.desk_server.demo,
                    },
                )
                return
            if not (w / "config.json").exists():
                self.send(
                    200, {"status": "NEEDS_SETUP", "checks": [], "candidates": [], "watchlist": []}
                )
                return
            store = Store(w)
            if parsed.path == "/api/state":
                result = store.get("desk_snapshot")
                if result:
                    result["feed_health"] = store.get("collector", {"status": "NOT_RUNNING"})
                self.send(
                    200, result or {"status": "NEEDS_REFRESH", "watchlist": [], "candidates": []}
                )
            elif parsed.path == "/api/health":
                self.send(200, doctor(w, now))
            elif parsed.path == "/api/review":
                self.send(200, store.review())
            elif parsed.path == "/api/research":
                self.send(
                    200,
                    {
                        "runs": store.get("research_runs", []),
                        "latest": store.get("latest_replay"),
                        "earnings": read(w / "earnings.json")
                        if (w / "earnings.json").exists()
                        else None,
                    },
                )
            elif parsed.path == "/api/context":
                from .context import snapshot

                self.send(200, snapshot(store, now))
            elif parsed.path == "/api/evidence":
                from .verification import readiness

                self.send(200, readiness(w))
            elif parsed.path == "/api/validation":
                self.send(200, scorecard(store))
            elif parsed.path == "/api/chart":
                instrument = parse_qs(parsed.query).get("instrument", [""])[0]
                bars = load_bars(w / "bars.csv") if (w / "bars.csv").exists() else []
                config = desk.configuration(w)
                try:
                    bars = closed_bars(
                        bars,
                        instrument,
                        now,
                        read(w / "calendar.json"),
                        config["instruments"],
                        config.get("broker"),
                    )[0]
                except ValueError:
                    bars = []
                result = [
                    {
                        "time": r["timestamp"].isoformat(),
                        "open": str(r["open"]),
                        "high": str(r["high"]),
                        "low": str(r["low"]),
                        "close": str(r["close"]),
                    }
                    for r in bars
                    if r["key"] == instrument
                    and r["timestamp"].date() == now.date()
                    and r["timestamp"].timestamp() + 300 <= now.timestamp()
                ]
                self.send(200, result)
            else:
                self.send(404, {"error": "Unknown local route"})
        except (ValueError, KeyError, OSError, ArithmeticError) as error:
            self.send(400, {"error": str(error)})

    def do_POST(self):
        if (
            not self.trusted(True)
            or self.headers.get("Content-Type", "").split(";")[0] != "application/json"
        ):
            self.send(403, {"error": "Same-origin JSON request with desk token required"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1_000_000:
                raise ValueError("Request must be 1..1000000 bytes")
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Expected a JSON object")
            from .cli import locked

            w, now = self.desk_server.workspace, self.desk_server.clock()
            with locked(w):
                if self.path == "/api/setup":
                    result = setup(
                        w,
                        broker=payload.get("broker"),
                        instruments=payload.get("watchlist"),
                        capital=payload.get("capital"),
                        max_loss=payload.get("max_loss"),
                        daily_risk=payload.get("daily_risk"),
                        demo=payload.get("demo") is True,
                    )
                    if result["mode"] == "DEMO":
                        self.desk_server.demo = True
                    self.send(200, result)
                    return
                if self.path == "/api/refresh":
                    result = desk.refresh(w, now)
                elif self.path == "/api/action":
                    result = desk.act(
                        w,
                        payload.get("action"),
                        now,
                        payload.get("id"),
                        payload.get("reason", ""),
                        payload.get("instrument"),
                    )
                    desk.refresh(w, now)
                elif self.path == "/api/sync":
                    if self.desk_server.demo:
                        raise ValueError("Demonstration mode never contacts brokers")
                    result = sync(w, now)
                    desk.refresh(w, now)
                elif self.path == "/api/context":
                    if self.desk_server.demo:
                        raise ValueError("Synthetic desks never contact external context providers")
                    from .context import collect

                    result = collect(w, public_only=payload.get("public_only") is True, force=True)
                    desk.refresh(w, now)
                elif self.path == "/api/validate-broker":
                    if self.desk_server.demo:
                        raise ValueError("Synthetic desks cannot validate authenticated accounts")
                    from .verification import validate_broker

                    result = validate_broker(w, payload.get("broker"))
                elif self.path == "/api/replay":
                    config = desk.configuration(w)
                    instrument = (
                        payload.get("instrument") or config.get("watchlist", ["NSE:RELIANCE"])[0]
                    )
                    result = replay(
                        load_bars(w / "bars.csv"),
                        instrument,
                        read(w / "calendar.json"),
                        config,
                        now,
                    )
                    store = Store(w)
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
                    store.event(
                        "RESEARCH_RUN",
                        {"run_id": result["run_id"]},
                        now.isoformat(),
                        "RESEARCH",
                        identity=result["run_id"],
                    )
                elif self.path == "/api/filings":
                    rows = normalize_events(payload.get("items"), now)
                    result = {
                        "items": Store(w).filings(rows, now.isoformat()),
                        "imported": len(rows),
                    }
                    desk.refresh(w, now)
                else:
                    self.send(404, {"error": "Unknown local action"})
                    return
            self.send(200, result)
        except (ValueError, KeyError, OSError, TypeError, ArithmeticError) as error:
            self.send(409 if "busy" in str(error).lower() else 400, {"error": str(error)})


def serve(workspace, port=8765, demo=False, collect=False, interval=30):
    if not 5 <= interval <= 3600:
        raise ValueError("Collector interval must be 5..3600 seconds")
    server = DeskServer(workspace, port, demo)
    worker = None
    if collect and server.demo:
        server.server_close()
        raise ValueError("Synthetic demonstrations never start a broker collector")
    if collect:
        if not (workspace / "config.json").exists():
            raise ValueError("Complete setup before starting the collector")
        worker = threading.Thread(
            target=collector, args=(workspace, server.stop_event, interval), daemon=True
        )
        worker.start()
    elif (workspace / "config.json").exists():
        from .cli import locked

        with locked(workspace):
            desk.refresh(workspace, server.clock())
    print("India Trader daily desk: " + server.origin, flush=True)
    print(
        "Synthetic replay clock enabled"
        if server.demo
        else "Local account data stays on this machine",
        flush=True,
    )
    try:
        server.serve_forever(poll_interval=0.3)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop_event.set()
        server.server_close()
        if worker:
            worker.join(timeout=2)
