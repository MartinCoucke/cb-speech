"""Generic RSS/Atom feed parsing into SpeechItem objects."""
from __future__ import annotations

from datetime import date, datetime, timezone

import feedparser

from models import SpeechItem


def normalize_url(url: str) -> str:
    """Strip fragment and trailing slash so the same speech maps to one id."""
    u = (url or "").split("#")[0].strip()
    return u[:-1] if u.endswith("/") else u


def _entry_date(entry) -> date:
    parsed = getattr(entry, "published_parsed", None) or getattr(
        entry, "updated_parsed", None
    )
    if parsed:
        return date(parsed.tm_year, parsed.tm_mon, parsed.tm_mday)
    return datetime.now(timezone.utc).date()


def _matches(value: str, needles: list[str] | None) -> bool:
    """True when no filter is configured, or any needle appears in `value`."""
    if not needles:
        return True
    low = (value or "").lower()
    return any(n.lower() in low for n in needles)


def parse_feed(text: str, *, default_bank: str, region: str, source: str,
               include: list[str] | None = None,
               url_include: list[str] | None = None) -> list[SpeechItem]:
    """Parse an RSS/Atom feed into SpeechItems.

    `include` / `url_include` keep only entries whose title / link contains one
    of the given substrings. Several banks publish speeches in a mixed feed —
    the Bundesbank's "Reden" feed carries each speech in both German and
    English plus interviews, and Ireland's news feed mixes speeches with press
    releases — so a filter is needed to avoid ingesting near-duplicates and
    non-speech items.
    """
    feed = feedparser.parse(text)
    items: list[SpeechItem] = []
    for e in feed.entries:
        link = getattr(e, "link", "")
        if not link:
            continue
        if not _matches(getattr(e, "title", ""), include):
            continue
        if not _matches(link, url_include):
            continue
        items.append(
            SpeechItem(
                id=normalize_url(link),
                title=getattr(e, "title", "").strip(),
                url=link,
                published=_entry_date(e),
                speaker=(getattr(e, "author", "") or "").strip() or None,
                bank=default_bank,
                region=region,
                source=source,
            )
        )
    return items
