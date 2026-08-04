"""Parse the BIS central bankers' speeches feed, mapping each item to a
target central bank + region. Items outside the five target jurisdictions
are dropped (rather than misfiled)."""
from __future__ import annotations

import re
from datetime import date, datetime

import feedparser

from models import SpeechItem
from sources.rss import normalize_url

# Sentinel for items whose delivery date could not be determined. Far in the
# past so the freshness gate always rejects them (fail closed — never present
# an item of unknown age as fresh).
UNKNOWN_DATE = date(1900, 1, 1)

_MONTHS = ("January|February|March|April|May|June|July|August|September|"
           "October|November|December")
_DATE_RE = re.compile(rf"(\d{{1,2}}\s+(?:{_MONTHS})\s+\d{{4}})")
_TAG_RE = re.compile(r"<[^>]+>")


def parse_delivery_date(description: str) -> date | None:
    """Extract the speech's actual delivery date from a BIS description.

    BIS Review descriptions end with the event location and date, e.g.
    "..., Washington DC, 14 July 2026." — the last date in the text is the
    delivery date. BIS's own feed dates are its upload time, which can lag
    delivery by weeks (measured 14-31 days), so they must not be used.
    """
    if not description:
        return None
    text = _TAG_RE.sub(" ", description)
    matches = _DATE_RE.findall(text)
    if not matches:
        return None
    try:
        return datetime.strptime(matches[-1], "%d %B %Y").date()
    except ValueError:
        return None

# First matching keyword wins. Order matters: specific before generic.
_MAPPING: list[tuple[str, str, str]] = [
    # US
    ("federal reserve", "Federal Reserve", "US"),
    ("board of governors", "Federal Reserve", "US"),
    # UK (before generic "bank of ..." Europe entries)
    ("bank of england", "Bank of England", "UK"),
    # Australia
    ("reserve bank of australia", "Reserve Bank of Australia", "Australia"),
    # Canada
    ("bank of canada", "Bank of Canada", "Canada"),
    # Europe — ECB + eurozone national central banks
    ("european central bank", "ECB", "Europe"),
    ("deutsche bundesbank", "Bundesbank", "Europe"),
    ("bundesbank", "Bundesbank", "Europe"),
    ("banque de france", "Banque de France", "Europe"),
    ("banca d'italia", "Banca d'Italia", "Europe"),
    ("bank of italy", "Banca d'Italia", "Europe"),
    ("banco de espana", "Banco de España", "Europe"),
    ("banco de españa", "Banco de España", "Europe"),
    ("nederlandsche bank", "De Nederlandsche Bank", "Europe"),
    ("national bank of belgium", "National Bank of Belgium", "Europe"),
    ("bank of greece", "Bank of Greece", "Europe"),
    ("central bank of ireland", "Central Bank of Ireland", "Europe"),
    ("banco de portugal", "Banco de Portugal", "Europe"),
    ("oesterreichische nationalbank", "Oesterreichische Nationalbank", "Europe"),
    ("bank of finland", "Bank of Finland", "Europe"),
]


def map_region(text: str) -> tuple[str, str] | None:
    """Return (bank, region) for a target institution, else None.

    Whitespace is collapsed first: descriptions wrap across lines, so an
    institution name can arrive as "Federal\\n    Reserve" and would otherwise
    fail a plain substring match, silently dropping the speech.
    """
    low = re.sub(r"\s+", " ", (text or "")).lower()
    for keyword, bank, region in _MAPPING:
        if keyword in low:
            return bank, region
    return None


def parse_feed(text: str) -> list[SpeechItem]:
    feed = feedparser.parse(text)
    items: list[SpeechItem] = []
    for e in feed.entries:
        link = getattr(e, "link", "")
        if not link:
            continue
        blob = " ".join(
            getattr(e, attr, "") or "" for attr in ("title", "summary", "author")
        )
        mapped = map_region(blob)
        if mapped is None:
            continue
        bank, region = mapped
        title = getattr(e, "title", "").strip()
        speaker = title.split(":", 1)[0].strip() if ":" in title else None
        items.append(
            SpeechItem(
                id=normalize_url(link),
                title=title,
                url=link,
                published=(parse_delivery_date(getattr(e, "summary", ""))
                           or UNKNOWN_DATE),
                speaker=speaker,
                bank=bank,
                region=region,
                source="bis",
            )
        )
    return items
