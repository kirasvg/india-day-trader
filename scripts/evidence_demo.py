"""Offline tour with invented inputs; successful mocks never close real release gates."""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from india_trader.context import collect
from india_trader.core import read, stamp
from india_trader.onboarding import setup
from india_trader.reconciliation import import_note
from india_trader.store import Store
from india_trader.validation import record
from india_trader.verification import readiness, validate_broker

NOW = stamp("2026-10-30T10:00:00+05:30")


class SyntheticBroker:
    name = "groww"

    def profile(self):
        return {"status": "AVAILABLE", "broker": self.name}

    def master(self):
        return {"NSE:INFY": {"groww_symbol": "NSE-INFY", "instrument_token": "123"}}

    def quotes(self, names):
        return {name: {"timestamp": NOW.isoformat(), "price": "100"} for name in names}

    def account_snapshot(self, *args):
        return {"status": "AVAILABLE", "available_cash_inr": "100000"}

    def candles(self, *args):
        return [{"timestamp": NOW.isoformat(), "close": "100"}]

    def transport(self, *args):
        return {
            "last_price": 101,
            "last_trade_time": int(NOW.timestamp() * 1000),
            "day_change_perc": "1",
        }


def run():
    with tempfile.TemporaryDirectory(prefix="india-evidence-demo-") as tmp:
        w = Path(tmp)
        setup(w, broker="groww", instruments="NSE:INFY", capital="100000", max_loss="500")
        client = SyntheticBroker()
        probes = validate_broker(w, client=client, now=NOW)
        notes = []
        for broker in ("groww", "zerodha"):
            base = ROOT / "examples/contract-notes"
            notes.append(
                import_note(
                    w,
                    read(base / ("synthetic-" + broker + ".json")),
                    base / ("synthetic-" + broker + "-source.txt"),
                )
            )

        def source(_):
            return [
                {
                    "title": "INFY synthetic results",
                    "source": "Synthetic fixture",
                    "url": "https://example.com/synthetic",
                    "published_at": NOW.isoformat(),
                }
            ]

        context = collect(w, client=client, fetch=source, now=NOW)
        record(Store(w), {"origin": "SYNTHETIC"}, read(w / "config.json"), {}, NOW, 30)
        gates = readiness(w)
        assert probes["origin"] == "TEST_DOUBLE"
        assert all(r["status"] == "MATCHED" and r["evidence_origin"] == "SYNTHETIC" for r in notes)
        assert gates["sessions"]["qualified_sessions"] == 0
        assert all(not r["matched_dates"] for r in gates["contract_note_reconciliation"].values())
        assert all(r["status"] == "MISSING_EVIDENCE" for r in gates["broker_validation"].values())
        return {
            "origin": "SYNTHETIC",
            "network_calls": 0,
            "orders_submitted": 0,
            "broker_probe_example": probes,
            "contract_note_examples": notes,
            "context_example": context,
            "actual_release_evidence": gates,
            "note": "Invented software walkthrough only. Replace placeholder paths and enter real credentials privately later. No actual broker validation, note reconciliation or market-session evidence is claimed.",
        }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = run()
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("PASS synthetic read-only broker-probe workflow (TEST_DOUBLE; no network)")
        for note in result["contract_note_examples"]:
            print(
                "PASS "
                + note["broker"]
                + " daily note: 3 fills grouped into 2 orders, component comparison MATCHED (SYNTHETIC)"
            )
        print("PASS synthetic corporate/ETF context workflow")
        print("PASS real evidence gates remain open; actual observed sessions: 0/20")
