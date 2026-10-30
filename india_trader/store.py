"""Transactional local journal, immutable plans and observable session health."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .core import fingerprint, number, read, write


class Store:
    def __init__(self, workspace):
        self.workspace = Path(workspace)
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.path = self.workspace / "desk.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS plans (id TEXT PRIMARY KEY, family TEXT NOT NULL, version INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, state TEXT NOT NULL, origin TEXT NOT NULL, plan TEXT NOT NULL, context TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, plan_id TEXT, at TEXT NOT NULL, kind TEXT NOT NULL, origin TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS account (id INTEGER PRIMARY KEY CHECK(id=1), hash TEXT NOT NULL, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS filings (id TEXT PRIMARY KEY, published_at TEXT NOT NULL, received_at TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS events_time ON events(at);
                PRAGMA user_version=1;
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(str(self.path), timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=10000")
        db.execute("PRAGMA journal_mode=WAL")
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def put(self, key, value):
        with self.connect() as db:
            db.execute(
                "INSERT INTO kv VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value, default=str)),
            )

    def event(self, kind, payload, at, origin="LOCAL", plan_id=None, identity=None):
        event_id = identity or fingerprint(
            {"kind": kind, "payload": payload, "at": str(at), "plan_id": plan_id}
        )
        with self.connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?)",
                (event_id, plan_id, str(at), kind, origin, json.dumps(payload, default=str)),
            )
        return event_id

    def record_plan(self, plan, context, now, origin):
        identity = "plan_" + fingerprint(plan)[:20]
        family = plan["instrument"] + ":" + plan["entry_time"] + ":" + plan["setup"]
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM plans WHERE id=?", (identity,)).fetchone()
            if existing:
                db.execute(
                    "UPDATE plans SET updated_at=?,context=? WHERE id=?",
                    (str(now), json.dumps(context, default=str), identity),
                )
            else:
                version = db.execute(
                    "SELECT COALESCE(MAX(version),0)+1 FROM plans WHERE family=?", (family,)
                ).fetchone()[0]
                db.execute(
                    "INSERT INTO plans VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        identity,
                        family,
                        version,
                        str(now),
                        str(now),
                        "PLANNED",
                        origin,
                        json.dumps(plan),
                        json.dumps(context, default=str),
                    ),
                )
        return identity

    def plans(self):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM plans ORDER BY created_at DESC,id").fetchall()
        return [
            dict(row, plan=json.loads(row["plan"]), context=json.loads(row["context"]))
            for row in rows
        ]

    def plan(self, identity):
        return next((p for p in self.plans() if p["id"] == identity), None)

    def decision(self, identity, action, reason, now):
        state = {"save": "SAVED", "skip": "SKIPPED"}.get(action)
        if not state or len(reason) > 4000:
            raise ValueError("Use save/skip and a reason under 4000 characters")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM plans WHERE id=?", (identity,)).fetchone()
            if not row or row["state"] not in ("PLANNED", "SAVED"):
                raise ValueError("Plan is absent or no longer open to this decision")
            db.execute(
                "UPDATE plans SET state=?,updated_at=? WHERE id=?", (state, str(now), identity)
            )
            payload = json.dumps(
                {
                    "action": action,
                    "reason": reason,
                    "plan_version": row["version"],
                    "evidence_at_decision": json.loads(row["context"]),
                }
            )
            event_id = fingerprint(
                {"plan": identity, "state": state, "payload": payload, "at": str(now)}
            )
            db.execute(
                "INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?)",
                (event_id, identity, str(now), "DECISION", "USER", payload),
            )
        return {"id": identity, "state": state}

    def account(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM account WHERE id=1").fetchone()
        return json.loads(row["value"]) if row else read(self.workspace / "account.json")

    def commit_account(self, before, after, kind, now, plan_id=None):
        """DB is authoritative once journaled; JSON is a recoverable compatibility mirror."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            current = db.execute("SELECT hash FROM account WHERE id=1").fetchone()
            if current and current["hash"] != fingerprint(before):
                raise ValueError("Paper account changed concurrently; reload before retrying")
            if plan_id:
                state = db.execute("SELECT state FROM plans WHERE id=?", (plan_id,)).fetchone()
                if not state or state["state"] not in ("PLANNED", "SAVED"):
                    raise ValueError("Plan no longer eligible for paper tracking")
                db.execute(
                    "UPDATE plans SET state='PAPER_TRACKED',updated_at=? WHERE id=?",
                    (str(now), plan_id),
                )
            if kind == "PAPER_CLOSE":
                closed = set(before.get("positions", {})) - set(after.get("positions", {}))
                for row in db.execute(
                    "SELECT id,plan FROM plans WHERE state='PAPER_TRACKED'"
                ).fetchall():
                    if json.loads(row["plan"])["instrument"] in closed:
                        db.execute(
                            "UPDATE plans SET state='CLOSED',updated_at=? WHERE id=?",
                            (str(now), row["id"]),
                        )
            encoded = json.dumps(after, sort_keys=True)
            db.execute(
                "INSERT INTO account VALUES (1,?,?) ON CONFLICT(id) DO UPDATE SET hash=excluded.hash,value=excluded.value",
                (fingerprint(after), encoded),
            )
            payload = {
                "before_hash": fingerprint(before),
                "after_hash": fingerprint(after),
                "cash_inr": after["cash_inr"],
                "positions_added": {
                    k: v
                    for k, v in after.get("positions", {}).items()
                    if k not in before.get("positions", {})
                },
                "exits_added": after.get("exits", [])[len(before.get("exits", [])) :],
            }
            db.execute(
                "INSERT OR IGNORE INTO events VALUES (?,?,?,?,?,?)",
                (fingerprint(payload), plan_id, str(now), kind, "LOCAL_PAPER", json.dumps(payload)),
            )
        write(self.workspace / "account.json", after)

    def close_plan(self, instrument, now):
        with self.connect() as db:
            for row in db.execute(
                "SELECT id,plan FROM plans WHERE state='PAPER_TRACKED'"
            ).fetchall():
                if json.loads(row["plan"])["instrument"] == instrument:
                    db.execute(
                        "UPDATE plans SET state='CLOSED',updated_at=? WHERE id=?",
                        (str(now), row["id"]),
                    )

    def review(self):
        account = self.account()
        with self.connect() as db:
            events = [
                dict(r, payload=json.loads(r["payload"]))
                for r in db.execute("SELECT * FROM events ORDER BY at DESC LIMIT 300")
            ]
        exits = account.get("exits", [])
        return {
            "origin": "LOCAL_PAPER",
            "cash_inr": account["cash_inr"],
            "open_positions": account.get("positions", {}),
            "closed_trades": exits,
            "net_pnl_inr": str(sum((number(r["net_pnl_inr"]) for r in exits), number(0))),
            "fees_inr": str(sum((number(r.get("fees_inr", 0)) for r in exits), number(0))),
            "events": events,
            "note": "Paper results remain separate from broker account facts and imported actual trade evidence",
        }

    def filings(self, rows=None, received_at=None):
        if rows is not None:
            with self.connect() as db:
                for row in rows:
                    identity = row.get("id") or fingerprint(row)
                    if not row.get("published_at"):
                        continue
                    db.execute(
                        "INSERT OR IGNORE INTO filings VALUES (?,?,?,?)",
                        (identity, row["published_at"], str(received_at), json.dumps(row)),
                    )
        with self.connect() as db:
            return [
                json.loads(r["payload"])
                for r in db.execute(
                    "SELECT payload FROM filings ORDER BY published_at DESC LIMIT 200"
                )
            ]
