"""RSS monitoring and sourced, structured earnings comparisons."""

import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib.error import URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .core import IST, fingerprint, number, stamp

CATEGORIES = {
    "results": ("financial result", "quarterly result", "earnings"),
    "corporate-action": ("dividend", "bonus", "stock split", "buyback", "buy-back"),
    "insider-disclosure": ("insider trading", "regulation 7(2)", "regulation 7 (2)"),
    "pledge": ("encumbrance", "pledge"),
    "ownership": ("shareholding", "acquisition", "disposal", "promoter"),
    "regulatory": ("sebi", "penalty", "litigation", "order of", "suspension"),
    "board-meeting": ("board meeting",),
}


def clean(value):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", html.unescape(value or ""))).strip()


def parse_feed(content, source):
    if (
        len(content) > 5_000_000
        or b"<!DOCTYPE" in content.upper()
        or b"<!ENTITY" in content.upper()
    ):
        raise ValueError("Feed too large or contains unsupported XML declarations")
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        raise ValueError("Malformed RSS/Atom XML") from None
    if root.tag.split("}")[-1] not in ("rss", "feed", "RDF"):
        raise ValueError("Response is not an RSS/Atom feed")
    rows = []
    for item in root.iter():
        if item.tag.split("}")[-1] not in ("item", "entry"):
            continue
        fields = {c.tag.split("}")[-1]: c for c in item}

        def value(*names):
            for name in names:
                if name in fields:
                    return "".join(fields[name].itertext()).strip()
            return ""

        link = value("link")
        if not link and "link" in fields:
            link = fields["link"].get("href", "")
        raw_date = value("pubDate", "published", "updated")
        date_basis = "EXPLICIT_OFFSET"
        try:
            try:
                published = stamp(raw_date)
            except ValueError:
                published = parsedate_to_datetime(raw_date)
                if published.tzinfo is None:
                    raise ValueError("Undated feed item")
                published = published.astimezone(IST)
        except (ValueError, TypeError, IndexError):
            published = None
            date_basis = "UNVERIFIED"
            parsed_source = urlparse(source)
            if parsed_source.hostname in (
                "nsearchives.nseindia.com",
                "archives.nseindia.com",
            ) and parsed_source.path.startswith("/content/RSS/"):
                # NSE RSS exposes exchange-local dates without an offset. Keep this policy explicit.
                try:
                    published = datetime.strptime(raw_date, "%d-%b-%Y %H:%M:%S").replace(tzinfo=IST)
                    date_basis = "NSE_LOCAL_IST_NORMALIZATION"
                except ValueError:
                    pass
        rows.append(
            {
                "title": clean(value("title")),
                "summary": clean(value("description", "summary", "content")),
                "url": link if urlparse(link).scheme in ("http", "https") else "",
                "source": source,
                "published_at": published.isoformat() if published else None,
                "raw_published_at": raw_date,
                "publication_time_basis": date_basis,
            }
        )
    return rows


def fetch_feed(url):
    if urlparse(url).scheme != "https":
        raise ValueError("Use an HTTPS RSS/Atom feed")
    try:
        request = Request(url, headers={"User-Agent": "india-day-trader/0.3 RSS reader"})
        with urlopen(request, timeout=25) as response:
            content = response.read(5_000_001)
        return parse_feed(content, url)
    except (URLError, TimeoutError):
        raise ValueError(
            "Feed unavailable; use a saved RSS file or a sourced JSON export"
        ) from None


def monitor(rows, now, hours, aliases=None, disclosures=False, seen=None):
    if hours <= 0:
        raise ValueError("Hours must be positive")
    result, skipped = [], 0
    seen = set(seen or [])
    for row in rows:
        if not row.get("published_at"):
            skipped += 1
            continue
        published = stamp(row["published_at"])
        if not now - timedelta(hours=hours) <= published <= now:
            continue
        text = clean(row.get("title", "") + " " + row.get("summary", ""))
        tags = [tag for tag, words in CATEGORIES.items() if any(w in text.lower() for w in words)]
        if disclosures and not any(
            t in tags for t in ("insider-disclosure", "pledge", "ownership")
        ):
            continue
        matches = []
        for instrument, names in (aliases or {}).items():
            if any(
                re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text, re.IGNORECASE)
                for name in names
            ):
                matches.append(instrument)
        if aliases and not matches:
            continue
        identity = fingerprint({k: row.get(k) for k in ("title", "url", "published_at")})
        if identity in seen:
            continue
        seen.add(identity)
        result.append(
            dict(
                row,
                id=identity,
                tags=tags,
                instruments=matches,
                matching="text alias match; verify company identity in original filing",
            )
        )
    return {
        "items": sorted(result, key=lambda r: stamp(r["published_at"]), reverse=True),
        "input_items": len(rows),
        "skipped_undated": skipped,
        "warning": "Feed coverage may be incomplete or delayed. No matching items is not proof of no material news.",
    }


def earnings(rows):
    if not rows:
        raise ValueError("Need at least one sourced quarter")
    rows = sorted(rows, key=lambda r: r["period_end"])
    dates = set()
    for row in rows:
        for field in ("instrument", "basis", "unit", "source_url", "period_end", "published_at"):
            if not row.get(field):
                raise ValueError("Missing earnings field: " + field)
        if row.get("period_months") != 3 or row["basis"] not in ("consolidated", "standalone"):
            raise ValueError("Supply three-month standalone or consolidated quarters")
        if any(row[k] != rows[-1][k] for k in ("instrument", "basis", "unit")):
            raise ValueError("Do not mix instruments, reporting basis or monetary units")
        if row["period_end"] in dates:
            raise ValueError("Duplicate quarter")
        dates.add(row["period_end"])
        if stamp(row["published_at"]) < stamp(row["period_end"] + "T00:00:00+05:30"):
            raise ValueError("Quarter published before its period ended")
        for field in ("revenue", "net_profit", "eps"):
            number(row[field])
    current = rows[-1]
    date = stamp(current["period_end"] + "T00:00:00+05:30")
    comparisons = {}
    for label, months in (("qoq", 3), ("yoy", 12)):
        other = next(
            (
                r
                for r in rows[:-1]
                if (date.year - int(r["period_end"][:4])) * 12
                + date.month
                - int(r["period_end"][5:7])
                == months
            ),
            None,
        )
        comparisons[label] = (
            None
            if other is None
            else {
                field: {
                    "change_pct": str((number(current[field]) / number(other[field]) - 1) * 100)
                    if number(other[field]) > 0
                    else None,
                    "absolute_change": str(number(current[field]) - number(other[field])),
                    "prior": other[field],
                    "note": "Percentage undefined for zero/negative prior base"
                    if number(other[field]) <= 0
                    else "",
                }
                for field in ("revenue", "net_profit", "eps")
            }
        )
    revenue = number(current["revenue"])
    return {
        "current": current,
        "comparisons": comparisons,
        "net_margin_pct": str(number(current["net_profit"]) / revenue * 100)
        if revenue > 0
        else None,
        "warning": "Arithmetic on supplied sourced quarters; no PDF extraction or forward earnings forecast.",
    }
