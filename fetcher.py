"""Fetch every configured feed, dispatch to the right parser, dedup by content.

Dedup is by a content key (speaker surname + normalized title), NOT by URL: the
same speech appears on a bank's own site and on BIS under different URLs, so a
URL key would let the same speech through twice (often 1-3 days apart). The
content key collapses those, preferring the direct (non-BIS) source.
"""
from __future__ import annotations

import logging
import re

import httpx

import config
from models import SpeechItem
from sources import bis, rss

log = logging.getLogger(__name__)


def _get(url: str) -> str:
    headers = {"User-Agent": config.HTTP_USER_AGENT}
    r = httpx.get(url, headers=headers, timeout=config.HTTP_TIMEOUT_S,
                  follow_redirects=True)
    r.raise_for_status()
    return r.text


def _fetch_playwright(feed: dict) -> list[SpeechItem]:
    from sources import ecb_playwright
    return ecb_playwright.fetch_speeches(feed)


def _parse_feed(feed: dict, text: str) -> list[SpeechItem]:
    if feed["kind"] == "bis":
        return bis.parse_feed(text)
    return rss.parse_feed(text, default_bank=feed["bank"],
                          region=feed["region"], source=feed["name"])


def content_key(item: SpeechItem) -> str:
    """Source-independent identity for a speech: speaker surname + title.

    BIS titles are "Speaker: Title" — strip the speaker prefix so they match
    the direct feed's bare title.
    """
    title = item.title or ""
    if item.source == "bis" and ":" in title:
        title = title.split(":", 1)[1]
    norm_title = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
    surname = item.speaker.strip().split()[-1].lower() if item.speaker else ""
    return f"{surname}|{norm_title}"


def dedup(items: list[SpeechItem]) -> list[SpeechItem]:
    """Collapse items with the same content key. A direct source beats BIS."""
    best: dict[str, SpeechItem] = {}
    for it in items:
        key = content_key(it)
        cur = best.get(key)
        if cur is None:
            best[key] = it
        elif cur.source == "bis" and it.source != "bis":
            best[key] = it
    return list(best.values())


def fetch_all() -> list[SpeechItem]:
    collected: list[SpeechItem] = []
    for feed in config.FEEDS:
        try:
            if feed["kind"] == "playwright":
                parsed = _fetch_playwright(feed)
            else:
                parsed = _parse_feed(feed, _get(feed["url"]))
            log.info("feed %s: %d items", feed["name"], len(parsed))
            collected.extend(parsed)
        except Exception as e:  # one feed down must not abort the run
            log.warning("feed %s failed: %s: %s", feed["name"], type(e).__name__, e)
    return dedup(collected)
