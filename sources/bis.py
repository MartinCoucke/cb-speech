"""Parse the BIS central bankers' speeches feed, mapping each item to a
target central bank + region. Items outside the five target jurisdictions
are dropped (rather than misfiled)."""
from __future__ import annotations

import feedparser

from models import SpeechItem
from sources.rss import _entry_date, normalize_url

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
    """Return (bank, region) for a target institution, else None."""
    low = (text or "").lower()
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
                published=_entry_date(e),
                speaker=speaker,
                bank=bank,
                region=region,
                source="bis",
            )
        )
    return items
