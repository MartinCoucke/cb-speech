"""Generic, config-driven scraper for HTML speech listings.

Each bank is a config entry rather than a module, so adding a source is a few
lines of selectors. Config keys:

    name, region, bank   - stamped onto every SpeechItem
    url                  - listing page to fetch
    base                 - origin used to resolve relative hrefs
    row_selector         - CSS selecting each listing row
    link_selector        - CSS for the anchor within a row
    date_selector        - CSS for the element holding the date
    date_formats         - list of strptime formats to try, in order
    speaker_selector     - optional CSS for a byline element
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime

import httpx
from bs4 import BeautifulSoup

import config
from models import SpeechItem

log = logging.getLogger(__name__)


def _clean_date_text(text: str) -> str:
    # Listings often append a location: "May 13, 2026    |Boston, Massachusetts"
    return text.split("|")[0].strip()


def _parse_date(text: str, formats: list[str]):
    cleaned = _clean_date_text(text)
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def _speaker_from_row(row, feed, title: str) -> str | None:
    sel = feed.get("speaker_selector")
    if sel:
        node = row.select_one(sel)
        if node:
            # Bylines often read "Susan M. Collins, President & CEO"
            name = node.get_text(" ", strip=True).split(",")[0].strip()
            # ...or name a collection: "Mary C. Daly's Speeches". Left as-is the
            # surname would extract as "speeches" and break the dedup key.
            name = re.sub(r"[’']s\s+speeches$", "", name, flags=re.I).strip()
            return name or None
    # Many listings use the "Speaker: Title" convention (NY Fed, BIS).
    if ":" in title:
        prefix = title.partition(":")[0].strip()
        if prefix and len(prefix.split()) <= 4:
            return prefix
    return None


def resolve_url(url: str) -> str:
    """Fill a `{year}` placeholder with the current year.

    Some listings are paginated by year (the RBA's media releases live at
    /media-releases/<year>/), so hardcoding one would silently stop working
    every January.
    """
    return url.replace("{year}", str(date.today().year))


def _title_matches(title: str, include: list[str] | None) -> bool:
    if not include:
        return True
    low = (title or "").lower()
    return any(s.lower() in low for s in include)


def parse_rows(html: str, feed: dict) -> list[SpeechItem]:
    """Parse a listing page into SpeechItems. Pure — no I/O, so it is testable
    against a saved fixture."""
    soup = BeautifulSoup(html, "html.parser")
    base = feed.get("base", "").rstrip("/")
    items: list[SpeechItem] = []
    seen_urls: set[str] = set()

    for row in soup.select(feed["row_selector"]):
        anchor = row.select_one(feed["link_selector"])
        if not anchor or not anchor.get("href"):
            continue
        # Prefer an explicit date element; fall back to a regex over the row's
        # text for listings whose date sits in a generated class name that
        # cannot be selected reliably (e.g. the SF Fed's "el-julyf").
        date_text = None
        if feed.get("date_selector"):
            node = row.select_one(feed["date_selector"])
            date_text = node.get_text(" ", strip=True) if node else None
        if date_text is None and feed.get("date_regex"):
            m = re.search(feed["date_regex"], row.get_text(" ", strip=True))
            date_text = m.group(0) if m else None
        if date_text is None:
            continue
        published = _parse_date(date_text, feed["date_formats"])
        if published is None:
            continue

        href = anchor["href"]
        url = href if href.startswith("http") else base + "/" + href.lstrip("/")
        if url in seen_urls:            # nested containers can repeat a row
            continue
        seen_urls.add(url)

        title = anchor.get_text(" ", strip=True)
        if not _title_matches(title, feed.get("include")):
            continue
        items.append(
            SpeechItem(
                id=url, title=title, url=url, published=published,
                speaker=_speaker_from_row(row, feed, title),
                bank=feed["bank"], region=feed["region"], source=feed["name"],
                category=feed.get("category", "speech"),
            )
        )
    return items


def count_missing_speakers(items: list[SpeechItem]) -> int:
    """Items with no speaker. A non-zero count means a selector has drifted;
    the item is still returned (never silently dropped) but the source is
    flagged to the health monitor."""
    return sum(1 for i in items if not i.speaker)


def fetch(feed: dict) -> list[SpeechItem]:
    headers = {"User-Agent": config.HTTP_USER_AGENT}
    r = httpx.get(resolve_url(feed["url"]), headers=headers,
                  timeout=config.HTTP_TIMEOUT_S,
                  follow_redirects=True)
    r.raise_for_status()
    items = parse_rows(r.text, feed)
    missing = count_missing_speakers(items)
    if missing:
        log.warning("%s: %d/%d items have no speaker — selector may have drifted",
                    feed["name"], missing, len(items))
    return items
