"""Config-driven scraper for JavaScript-rendered speech listings.

Identical in configuration to `sources.html_list` — it renders the page with
headless Chromium and then hands the resulting HTML to `html_list.parse_rows`,
so there is a single parsing code path and a single set of selector semantics.
Use this only when a site genuinely needs a browser; each entry adds ~10s to the
run and a Chromium dependency.

Extra config keys beyond html_list's:

    wait_for  - CSS selector to wait for before reading (the listing itself)
    scrolls   - how many wheel steps to trigger lazy loading (default 2)
"""
from __future__ import annotations

import logging

from models import SpeechItem
from sources import html_list

log = logging.getLogger(__name__)


def render(feed: dict) -> str:
    """Return the fully-rendered HTML of the listing page."""
    from playwright.sync_api import sync_playwright

    url = html_list.resolve_url(feed["url"])
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            if feed.get("wait_for"):
                # networkidle resolves too early on these sites; wait for the
                # listing itself to exist rather than for the network to settle.
                page.wait_for_selector(feed["wait_for"], timeout=30_000)
            else:
                page.wait_for_timeout(3_000)
            for _ in range(feed.get("scrolls", 2)):
                page.mouse.wheel(0, 4000)
                page.wait_for_timeout(700)
            return page.content()
        finally:
            browser.close()


def fetch(feed: dict) -> list[SpeechItem]:
    items = html_list.parse_rows(render(feed), feed)
    missing = html_list.count_missing_speakers(items)
    if missing and not feed.get("speaker_optional"):
        log.warning("%s: %d/%d items have no speaker — selector may have drifted",
                    feed["name"], missing, len(items))
    return items
