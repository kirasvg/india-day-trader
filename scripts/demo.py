"""Exercise all eleven workflows offline in an isolated temporary workspace."""

import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(workspace):
    commands = [
        ["init", "--demo"],
        ["scan"],
        ["entry", "NSE:RELIANCE"],
        ["exit", "NSE:RELIANCE"],
        ["simulate", "--replays", "1000"],
        ["budget"],
        ["risk"],
        ["broker", "ticket", "--broker", "zerodha"],
        ["broker", "ticket", "--broker", "groww"],
        ["news", "--file", str(workspace / "news-input.json"), "--new-only"],
        ["disclosures", "--file", str(workspace / "news-input.json"), "--new-only"],
        ["analyst", "--file", str(workspace / "financials.json")],
        ["alerts"],
        ["broker", "paper-fill"],
        ["broker", "paper-close", "--instrument", "NSE:RELIANCE"],
        ["broker", "journal"],
    ]
    for command in commands:
        args = [
            sys.executable,
            str(ROOT / "scripts" / "trader.py"),
            "--workspace",
            str(workspace),
            "--now",
            "2026-10-19T09:35:00+05:30",
        ] + command
        result = subprocess.run(args, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError("%s: %s" % (command, result.stderr or result.stdout))
        print("PASS", " ".join(command[:2]))
    print("All eleven workflows passed on SYNTHETIC fixtures. No network calls or live orders.")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="india-trader-demo-") as directory:
        run(Path(directory))
