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


def parse_feed(text: str, *, default_bank: str, region: str, source: str
               ) -> list[SpeechItem]:
    feed = feedparser.parse(text)
    items: list[SpeechItem] = []
    for e in feed.entries:
        link = getattr(e, "link", "")
        if not link:
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
