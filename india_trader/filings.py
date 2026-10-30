"""Source-preserving filing imports and bounded Ind-AS XBRL extraction."""

import calendar
import hashlib
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date
from urllib.parse import urlparse

from .core import fingerprint, key, number, stamp

FIELDS = {
    "revenue": {"revenuefromoperations", "revenuefromoperationsnet"},
    "net_profit": {"profitlossforperiod", "profitlossfortheperiod"},
    "eps": {
        "basicearningslosspershare",
        "basicearningslosspersharefromcontinuinganddiscontinuedoperations",
        "basicearningslosspersharefromcontinuingoperations",
    },
}


def normalize_events(rows, now):
    if not isinstance(rows, list) or len(rows) > 5000:
        raise ValueError("Import an array with at most 5000 sourced events")
    result = []
    for row in rows:
        if not isinstance(row, dict) or not all(
            row.get(k) for k in ("title", "source", "url", "published_at")
        ):
            raise ValueError(
                "Every event needs title, source, original URL and publication timestamp"
            )
        if len(row["title"]) > 1000 or len(row.get("summary", "")) > 20000:
            raise ValueError("Event text exceeds supported size")
        if urlparse(row["url"]).scheme != "https":
            raise ValueError("Use HTTPS original-source URLs")
        if stamp(row["published_at"]) > now:
            raise ValueError("Future publication cannot be imported as known evidence")
        if row.get("instrument"):
            key(*row["instrument"].split(":"))
        if row.get("scheduled_at"):
            stamp(row["scheduled_at"])
        normalized = dict(row)
        normalized["published_at"] = stamp(row["published_at"]).isoformat()
        normalized["id"] = fingerprint(
            {
                "source": row["source"],
                "document_id": row.get("document_id"),
                "url": row["url"],
                "published": normalized["published_at"],
                "content": row.get("content_sha256", row.get("summary", "")),
                "revision": row.get("revision", 0),
            }
        )
        normalized["received_at"] = now.isoformat()
        normalized["evidence_status"] = "SOURCE_SUPPLIED_NOT_INDEPENDENTLY_VERIFIED"
        result.append(normalized)
    return result


def extract_xbrl(content, instrument, source_url, published_at, basis):
    key(*instrument.split(":"))
    if basis not in ("standalone", "consolidated") or urlparse(source_url).scheme != "https":
        raise ValueError("Specify reporting basis and an HTTPS original filing URL")
    publication = stamp(published_at)
    if (
        len(content) > 10_000_000
        or b"<!DOCTYPE" in content.upper()
        or b"<!ENTITY" in content.upper()
    ):
        raise ValueError("XBRL too large or contains unsupported XML declarations")
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        raise ValueError("Malformed XBRL XML") from None

    def local(element):
        return element.tag.split("}")[-1]

    contexts, units = {}, {}
    for element in root.iter():
        if local(element) == "context":
            values = {
                local(c): (c.text or "").strip()
                for c in element.iter()
                if local(c) in ("startDate", "endDate", "instant")
            }
            if not values.get("startDate") or not values.get("endDate"):
                continue
            start, end = (
                date.fromisoformat(values["startDate"]),
                date.fromisoformat(values["endDate"]),
            )
            if (
                (end.year - start.year) * 12 + end.month - start.month != 2
                or start.day != 1
                or end.day != calendar.monthrange(end.year, end.month)[1]
            ):
                continue
            members = " ".join(
                (c.text or "") for c in element.iter() if local(c) == "explicitMember"
            ).lower()
            if (
                basis == "standalone"
                and "consolidatedmember" in members
                or basis == "consolidated"
                and "standalonemember" in members
            ):
                continue
            contexts[element.get("id")] = {
                "end": str(end),
                "basis_evidence": "dimension" if members else "user-supplied basis",
            }
        elif local(element) == "unit":
            units[element.get("id")] = " ".join(
                (c.text or "") for c in element.iter() if local(c) == "measure"
            )
    facts, evidence = defaultdict(dict), defaultdict(dict)
    for element in root.iter():
        context_id = element.get("contextRef")
        if context_id not in contexts:
            continue
        name = local(element).lower()
        field = next((field for field, aliases in FIELDS.items() if name in aliases), None)
        if not field:
            continue
        unit = units.get(element.get("unitRef"), "").lower()
        if "inr" not in unit:
            raise ValueError(
                "Unsupported/unknown monetary unit; extraction will not guess lakh/crore scaling"
            )
        if field == "eps" and "shares" not in unit:
            raise ValueError("EPS needs an explicit INR-per-share unit")
        value = number((element.text or "").strip()) * (number(10) ** int(element.get("scale", 0)))
        end = contexts[context_id]["end"]
        if field in facts[end] and facts[end][field] != value:
            raise ValueError(
                "Conflicting same-quarter facts; select a supported sector/basis template before extraction"
            )
        facts[end][field] = value
        evidence[end][field] = {
            "element": local(element),
            "context_ref": context_id,
            "unit_ref": element.get("unitRef"),
            "basis_evidence": contexts[context_id]["basis_evidence"],
        }
    rows = []
    for end, values in sorted(facts.items()):
        if set(values) != set(FIELDS):
            continue
        if date.fromisoformat(end) > publication.date():
            raise ValueError("Filing publication precedes its quarter end")
        month = int(end[5:7])
        fiscal_year = int(end[:4]) + int(month > 3)
        rows.append(
            {
                "instrument": instrument,
                "period_end": end,
                "period_months": 3,
                "basis": basis,
                "unit": "INR",
                "eps_unit": "INR/share",
                "fiscal_year_end": fiscal_year,
                "fiscal_quarter": {6: 1, 9: 2, 12: 3, 3: 4}.get(month),
                **{k: str(v) for k, v in values.items()},
                "published_at": publication.isoformat(),
                "source_url": source_url,
                "content_sha256": hashlib.sha256(content).hexdigest(),
                "field_evidence": evidence[end],
                "extraction_status": "SUPPORTED_TAGS_REQUIRE_REVIEW",
            }
        )
    if not rows:
        raise ValueError(
            "No complete supported three-month revenue/profit/basic-EPS context; bank/NBFC, cumulative and unfamiliar taxonomies require explicit review"
        )
    return rows
