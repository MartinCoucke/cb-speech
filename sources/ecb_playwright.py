"""Scrape the ECB key-speeches index with headless Chromium.

The ECB no longer publishes a speeches RSS feed and its index page is
JavaScript-rendered (a "foedb" definition-list), so static fetching returns
nothing. We drive a real browser, scroll to populate the lazy-loaded list,
and read the dt(date)/dd(entry) pairs. Only entries categorised "Speech"
with a /press/key/date/ link are kept.

`parse_entries` is the pure, browser-free core (unit-tested); `fetch_speeches`
does the Playwright extraction and delegates to it.
"""
from __future__ import annotations

import logging
from datetime import date, datetime

from models import SpeechItem
from sources.rss import normalize_url

log = logging.getLogger(__name__)

_BASE = "https://www.ecb.europa.eu"

# JS run in the page: collect entry dd blocks (category + title link), each
# paired with its preceding dt (the date).
_EXTRACT_JS = """
() => {
  const out = [];
  document.querySelectorAll('dd').forEach(dd => {
    const cat = dd.querySelector('.category');
    const a = dd.querySelector(".title a[href*='/press/key/date/']");
    if (!cat || !a) return;
    const dt = dd.previousElementSibling;
    const authors = Array.from(dd.querySelectorAll('.authors li'))
        .map(li => li.textContent.trim());
    out.push({
      category: cat.textContent.trim(),
      title: a.textContent.trim(),
      href: a.getAttribute('href'),
      date: dt ? dt.textContent.trim() : '',
      speaker: authors.join(', '),
    });
  });
  return out;
}
"""


def _parse_date(s: str) -> date | None:
    try:
        return datetime.strptime(s.strip(), "%d %B %Y").date()
    except ValueError:
        return None


def parse_entries(rows: list[dict], *, bank: str, region: str,
                  source: str = "ecb") -> list[SpeechItem]:
    items: list[SpeechItem] = []
    for r in rows:
        if (r.get("category") or "").strip().lower() != "speech":
            continue
        href = (r.get("href") or "").strip()
        published = _parse_date(r.get("date") or "")
        if not href or published is None:
            continue
        url = href if href.startswith("http") else _BASE + href
        speaker = (r.get("speaker") or "").strip() or None
        items.append(
            SpeechItem(
                id=normalize_url(url),
                title=(r.get("title") or "").strip(),
                url=url,
                published=published,
                speaker=speaker,
                bank=bank,
                region=region,
                source=source,
            )
        )
    return items


def fetch_speeches(feed: dict) -> list[SpeechItem]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(feed["url"], wait_until="domcontentloaded", timeout=60_000)
            # The foedb list is JS-rendered; wait for it to populate before
            # reading. networkidle resolves too early here.
            page.wait_for_selector(
                "dd .title a[href*='/press/key/date/']", timeout=30_000)
            # A few scroll wheels pull in more recent entries (we only need
            # the last ~48h, but the initial batch can be short).
            for _ in range(3):
                page.mouse.wheel(0, 5000)
                page.wait_for_timeout(600)
            rows = page.evaluate(_EXTRACT_JS)
        finally:
            browser.close()

    return parse_entries(rows, bank=feed["bank"], region=feed["region"],
                         source=feed["name"])
