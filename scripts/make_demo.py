"""Regenerate reproducible SYNTHETIC fixtures. None are real market records."""

import csv
import json
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from india_trader.core import IST, write


def make(destination):
    destination.mkdir(parents=True, exist_ok=True)
    config = json.loads((ROOT / "examples" / "config.json").read_text())
    config["data_label"] = (
        "SYNTHETIC DEMO: invented prices, statements, sessions and disclosures; not market evidence"
    )
    write(destination / "config.json", config)
    write(
        destination / "account.json",
        {"cash_inr": "100000", "positions": {}, "trades": [], "mode": "LOCAL_PAPER"},
    )
    write(
        destination / "instruments.json",
        {
            "NSE:RELIANCE": {
                "asset": "EQUITY",
                "lot_size": 1,
                "tick_size": "0.05",
                "instrument_token": "738561",
                "groww_symbol": "NSE-RELIANCE",
                "source": "SYNTHETIC FIXTURE; refresh master before real data use",
            }
        },
    )
    write(
        destination / "quotes.json",
        {
            "NSE:RELIANCE": {
                "price": "1008",
                "timestamp": "2026-10-19T09:35:00+05:30",
                "source": "SYNTHETIC",
            }
        },
    )
    today, days = date(2026, 10, 19), []
    day = today - timedelta(days=1)
    while len(days) < 25:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    days = sorted(days) + [today]
    sessions, rows, rng = {}, [], random.Random(812)
    for day in days:
        sessions["NSE:" + str(day)] = {
            "open": "09:15:00",
            "close": "15:30:00",
            "entry_after": "09:30:00",
            "entry_before": "14:45:00",
            "flat_by": "15:10:00",
        }
        start = datetime.combine(day, datetime.min.time(), IST) + timedelta(hours=9, minutes=15)
        previous = 1002.0
        for i in range(75 if day != today else 4):
            if i == 0:
                o, h, low, c = 1000, 1003, 995, 1001
            elif i == 1:
                o, h, low, c = 1001, 1005, 998, 1002
            elif i == 2:
                o, h, low, c = 1002, 1004, 999, 1002
            elif i == 3:
                o, h, low, c = 1002, 1010, 1001, 1008
            else:
                o = previous
                c = round((o + rng.uniform(-3.5, 3.5)) * 20) / 20
                h = max(o, c) + 1
                low = min(o, c) - 1
            previous = c
            row = {
                "exchange": "NSE",
                "symbol": "RELIANCE",
                "timestamp": (start + timedelta(minutes=i * 5)).isoformat(),
                "open": o,
                "high": h,
                "low": low,
                "close": c,
                "volume": 100000 + i * 100,
            }
            rows.append(row)
    write(
        destination / "calendar.json",
        {
            "source": "SYNTHETIC: weekdays selected for testing, not the exchange holiday calendar",
            "sessions": sessions,
        },
    )
    with open(destination / "bars.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    write(
        destination / "news-input.json",
        [
            {
                "title": "SYNTHETIC: Reliance Industries quarterly financial results",
                "summary": "Invented demonstration announcement.",
                "url": "https://example.com/synthetic-results",
                "source": "SYNTHETIC",
                "published_at": "2026-10-19T09:00:00+05:30",
            },
            {
                "title": "SYNTHETIC: Reliance Industries insider trading disclosure",
                "summary": "Invented promoter acquisition disclosure. No actual transaction.",
                "url": "https://example.com/synthetic-disclosure",
                "source": "SYNTHETIC",
                "published_at": "2026-10-19T09:05:00+05:30",
            },
        ],
    )
    write(
        destination / "context.json",
        {
            "origin": "SYNTHETIC",
            "status": "SYNTHETIC",
            "at": "2026-10-19T09:35:00+05:30",
            "max_proxy_age_seconds": 60,
            "sources": [
                {
                    "id": "synthetic-results",
                    "category": "results",
                    "url": "https://example.com/synthetic-results",
                    "status": "SYNTHETIC",
                    "checked_at": "2026-10-19T09:35:00+05:30",
                    "input_items": 1,
                    "matched_items": 1,
                }
            ],
            "proxies": [
                {
                    "instrument": instrument,
                    "label": label + " · synthetic",
                    "role": role,
                    "kind": "ETF_PROXY_NOT_INDEX",
                    "status": "SYNTHETIC",
                    "price_inr": price,
                    "change_pct": change,
                    "timestamp": "2026-10-19T09:35:00+05:30",
                }
                for instrument, label, role, price, change in (
                    ("NSE:NIFTYBEES", "Broad market ETF proxy", "MARKET", "100", "0.50"),
                    ("NSE:BANKBEES", "Banking ETF proxy", "SECTOR", "200", "-0.20"),
                    ("NSE:ITBEES", "IT ETF proxy", "SECTOR", "50", "0.80"),
                )
            ],
            "note": "All proxy prices, changes and source counts are INVENTED; no source/provider was contacted. Never count this as observed market context.",
        },
    )
    financials = []
    for period, published, revenue, profit, eps in (
        ("2025-09-30", "2025-10-19", "1000", "100", "10"),
        ("2026-06-30", "2026-07-19", "1100", "110", "11"),
        ("2026-09-30", "2026-10-18", "1200", "125", "12.5"),
    ):
        financials.append(
            {
                "instrument": "NSE:RELIANCE",
                "period_end": period,
                "period_months": 3,
                "basis": "consolidated",
                "unit": "INR crore",
                "revenue": revenue,
                "net_profit": profit,
                "eps": eps,
                "published_at": published + "T18:00:00+05:30",
                "source_url": "https://example.com/synthetic-financials",
                "source_note": "SYNTHETIC amounts; EPS in INR per share",
            }
        )
    write(destination / "financials.json", financials)
    (destination / "sample.xml").write_text(
        """<?xml version="1.0"?><rss version="2.0"><channel><title>Synthetic feed</title>
<item><title>SYNTHETIC: Reliance Industries financial results</title><description>Quarterly result illustration</description><link>https://example.com/synthetic</link><pubDate>Mon, 19 Oct 2026 09:00:00 +0530</pubDate></item>
</channel></rss>""",
        encoding="utf-8",
    )


if __name__ == "__main__":
    make(ROOT / "india_trader" / "templates" / "demo")
