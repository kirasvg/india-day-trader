import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from india_trader.cli import locked
from india_trader.core import read, write

ROOT = Path(__file__).resolve().parents[1]


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name) / "state"

    def call(self, *args):
        return subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "trader.py"),
                "--workspace",
                str(self.workspace),
                "--now",
                "2026-10-19T09:35:00+05:30",
            ]
            + list(args),
            capture_output=True,
            text=True,
        )

    def prepare(self):
        for args in (("init", "--demo"), ("exit", "NSE:RELIANCE"), ("budget",)):
            result = self.call(*args)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_init_refuses_overwrite(self):
        self.assertEqual(self.call("init", "--demo").returncode, 0)
        self.assertEqual(self.call("init", "--demo").returncode, 1)

    def test_risk_block_exit_code(self):
        self.prepare()
        write(self.workspace / "quotes.json", {})
        result = self.call("risk")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["status"], "BLOCK")

    def test_ticket_rechecks_edited_order(self):
        self.prepare()
        self.assertEqual(self.call("risk").returncode, 0)
        order = read(self.workspace / "order.json")
        order["quantity"] = 999999
        write(self.workspace / "order.json", order)
        self.assertEqual(self.call("broker", "ticket").returncode, 1)
        self.assertFalse((self.workspace / "zerodha-ticket.json").exists())

    def test_alert_deduplication(self):
        self.prepare()
        quote = read(self.workspace / "quotes.json")
        quote["NSE:RELIANCE"]["price"] = "999"
        write(self.workspace / "quotes.json", quote)
        first, second = self.call("alerts"), self.call("alerts")
        self.assertEqual(json.loads(first.stdout)["new_events"][0]["event"], "STOP")
        self.assertFalse(json.loads(second.stdout)["new_events"])

    def test_workspace_lock_blocks_concurrent_write(self):
        with locked(self.workspace):
            self.assertEqual(self.call("init").returncode, 1)
        self.assertFalse((self.workspace / ".lock").exists())

    def test_watch_refuses_frozen_research_clock(self):
        result = self.call("watch", "alerts", "--polls", "1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("current clock", result.stderr)

    def test_one_poll_news_watch_offline(self):
        self.prepare()
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "trader.py"),
                "--workspace",
                str(self.workspace),
                "watch",
                "news",
                "--file",
                str(self.workspace / "news-input.json"),
                "--polls",
                "1",
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["poll"], 1)

    def test_future_plan_not_simulated(self):
        self.prepare()
        p = read(self.workspace / "plan.json")
        p["entry_time"] = "2026-10-20T09:35:00+05:30"
        write(self.workspace / "plan.json", p)
        self.assertEqual(self.call("simulate", "--replays", "1").returncode, 1)

    def test_installed_skill_is_self_contained(self):
        destination = Path(self.temp.name) / "skills"
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "install_skills.py"),
                "--destination",
                str(destination),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(list(destination.glob("india-trader-*/SKILL.md"))), 11)
        runner = destination / "india-trader-scanner" / "runner.py"
        result = subprocess.run(
            [sys.executable, str(runner), "--workspace", str(self.workspace), "init", "--demo"],
            cwd=self.temp.name,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        collision = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "install_skills.py"),
                "--destination",
                str(destination),
            ],
            capture_output=True,
            text=True,
        )
        self.assertEqual(collision.returncode, 1)
