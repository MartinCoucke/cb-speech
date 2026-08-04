# Speech Freshness (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the digest emailing weeks-old speeches, and capture NY Fed / Boston Fed speeches on the day they are released instead of ~20 days later via BIS.

**Architecture:** Parse the true delivery date out of BIS descriptions and gate BIS on it, so stale backfill is ignored. Add a generic config-driven HTML scraper so new banks are config entries rather than new modules. Replace the single dedup key with a two-key any-match scheme so a source that stops emitting speakers can't produce duplicates. Add source-health tracking so a broken scraper is visible rather than looking like a quiet news day.

**Tech Stack:** Python 3.12, `httpx`, `beautifulsoup4`, `feedparser`, `pytest`. Existing modules: `config.py`, `fetcher.py`, `main.py`, `email_send.py`, `sources/`.

**Spec:** `docs/superpowers/specs/2026-08-04-speech-freshness-design.md`

---

## Scope note

The spec's Phase 1 listed five regional Feds. Live DOM inspection on 2026-08-04
confirmed only **New York** and **Boston** expose a parseable speech listing over
plain HTTP. Richmond's listing is speaker-indexed (links go to person pages, not
speeches), and Cleveland/Atlanta return no speech anchors without JavaScript.
Those three move to a follow-up phase, where adding them is a config entry once
their structure is known. Everything else in Phase 1 is unchanged.

---

## File structure

| File | Change | Responsibility |
|---|---|---|
| `config.py` | modify | Add `BIS_MAX_AGE_DAYS`, `SOURCE_HEALTH_ALERT_RUNS`, `HEALTH_FILE`, and two `html_list` feed entries |
| `sources/bis.py` | modify | Parse true delivery date from description |
| `sources/html_list.py` | create | Generic config-driven HTML listing scraper |
| `fetcher.py` | modify | `identity_keys`, multi-key dedup, BIS freshness gate, `html_list` dispatch, per-source counts |
| `main.py` | modify | Multi-key `seen` membership, source-health persistence |
| `email_send.py` | modify | Render source-health warnings |
| `tests/fixtures/*.html` | create | Saved listing HTML for NY and Boston |
| `tests/test_*.py` | modify/create | Tests per task |

---

## Task 1: Parse the true delivery date from BIS descriptions

**Files:**
- Modify: `sources/bis.py`
- Test: `tests/test_bis.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_bis.py`:

```python
from datetime import date


def test_parse_delivery_date_takes_trailing_date():
    desc = ("Speech by Ms Michelle W Bowman, Vice Chair for Supervision of the "
            "Board of Governors of the Federal Reserve System, at the third "
            "annual Financial Inclusion Conference, Washington DC, 14 July 2026.")
    assert bis.parse_delivery_date(desc) == date(2026, 7, 14)


def test_parse_delivery_date_picks_last_when_several():
    desc = "Speech given on 1 January 2020 anniversary, London, 14 July 2026."
    assert bis.parse_delivery_date(desc) == date(2026, 7, 14)


def test_parse_delivery_date_returns_none_when_absent():
    assert bis.parse_delivery_date("Speech by Mr X at a conference.") is None
    assert bis.parse_delivery_date("") is None


def test_parse_feed_uses_delivery_date_not_upload_date():
    xml = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <item>
        <title>John C Williams: Stability of Thy Times</title>
        <link>https://www.bis.org/review/r260803a.htm</link>
        <description>Remarks by Mr John C Williams, President of the Federal
        Reserve Bank of New York, New York City, 15 July 2026.</description>
      </item>
    </channel></rss>"""
    items = bis.parse_feed(xml)
    assert len(items) == 1
    assert items[0].published == date(2026, 7, 15)


def test_parse_feed_marks_unparseable_date_as_ancient():
    xml = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <item>
        <title>Someone: A speech</title>
        <link>https://www.bis.org/review/r260803b.htm</link>
        <description>Remarks by Mr Someone, Bank of England, with no date.</description>
      </item>
    </channel></rss>"""
    items = bis.parse_feed(xml)
    assert items[0].published == bis.UNKNOWN_DATE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_bis.py -q`
Expected: FAIL with `AttributeError: module 'sources.bis' has no attribute 'parse_delivery_date'`

- [ ] **Step 3: Write the implementation**

In `sources/bis.py`, add after the imports:

```python
import re
from datetime import date, datetime

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
    delivery by weeks, so they must not be used.
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
```

Then in `parse_feed`, replace the `published=_entry_date(e),` line with:

```python
                published=(parse_delivery_date(getattr(e, "summary", ""))
                           or UNKNOWN_DATE),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_bis.py -q`
Expected: PASS (all tests, including the two pre-existing ones)

- [ ] **Step 5: Commit**

```bash
git add sources/bis.py tests/test_bis.py
git commit -m "fix: use true speech delivery date for BIS items, not BIS upload date"
```

---

## Task 2: Gate BIS items on freshness

**Files:**
- Modify: `config.py`, `fetcher.py`
- Test: `tests/test_fetcher.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fetcher.py`:

```python
from datetime import timedelta


def test_bis_items_older_than_max_age_are_dropped(monkeypatch):
    monkeypatch.setattr(fetcher.config, "BIS_MAX_AGE_DAYS", 7)
    old = _item("https://bis/old", "bis", title="Old speech", speaker="A Old")
    old.published = date.today() - timedelta(days=20)
    fresh = _item("https://bis/new", "bis", title="Fresh speech", speaker="B New")
    fresh.published = date.today() - timedelta(days=1)
    kept = fetcher.apply_freshness_gate([old, fresh])
    assert [i.title for i in kept] == ["Fresh speech"]


def test_freshness_gate_drops_unknown_dates(monkeypatch):
    from sources import bis as bis_mod
    monkeypatch.setattr(fetcher.config, "BIS_MAX_AGE_DAYS", 7)
    unknown = _item("https://bis/x", "bis", title="Unknown", speaker="C X")
    unknown.published = bis_mod.UNKNOWN_DATE
    assert fetcher.apply_freshness_gate([unknown]) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fetcher.py -q`
Expected: FAIL with `AttributeError: module 'fetcher' has no attribute 'apply_freshness_gate'`

- [ ] **Step 3: Write the implementation**

In `config.py`, add under the "Dedup / freshness" section:

```python
# BIS publishes speeches 14-31 days after delivery (measured 2026-08-04), so a
# BIS item is only accepted if it was *delivered* within this window. Wider than
# LOOKBACK_HOURS so a genuinely prompt BIS post is still caught, narrow enough to
# exclude the observed backfill.
BIS_MAX_AGE_DAYS = 7
```

In `fetcher.py`, add after the imports:

```python
from datetime import date as _date, timedelta
```

and add this function:

```python
def apply_freshness_gate(items: list[SpeechItem]) -> list[SpeechItem]:
    """Drop BIS items whose delivery date is older than BIS_MAX_AGE_DAYS.

    BIS lags delivery by weeks; without this, a 3-week-old speech that BIS has
    only just published is emailed as though it were news.
    """
    cutoff = _date.today() - timedelta(days=config.BIS_MAX_AGE_DAYS)
    return [i for i in items if i.published >= cutoff]
```

In `fetch_all`, apply it to BIS results only — change the parse branch to:

```python
            if feed["kind"] == "playwright":
                parsed = _fetch_playwright(feed)
            else:
                parsed = _parse_feed(feed, _get(feed["url"]))
            if feed["kind"] == "bis":
                before = len(parsed)
                parsed = apply_freshness_gate(parsed)
                if before != len(parsed):
                    log.info("bis: dropped %d stale items (older than %dd)",
                             before - len(parsed), config.BIS_MAX_AGE_DAYS)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_fetcher.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config.py fetcher.py tests/test_fetcher.py
git commit -m "feat: gate BIS items on true delivery age to ignore backfill"
```

---

## Task 3: Two-key identity for duplicate-proof dedup

**Files:**
- Modify: `fetcher.py`
- Test: `tests/test_identity.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_identity.py`:

```python
from datetime import date
import fetcher
from models import SpeechItem


def _mk(title, speaker, source, region="US", published=date(2026, 7, 15)):
    return SpeechItem(id="https://x/" + title, title=title, url="https://x/",
                      published=published, speaker=speaker, bank="b",
                      region=region, source=source)


def test_speaker_key_matches_legacy_format():
    """Key 1 must keep the exact pre-existing format so entries already in
    state/seen.json continue to suppress their speeches."""
    item = _mk("Economic Outlook", "Lisa D Cook", "fed")
    assert "cook|economic outlook" in fetcher.identity_keys(item)


def test_bis_title_prefix_stripped_when_it_is_the_speaker():
    bis = _mk("John C Williams: Stability of Thy Times", "John C Williams", "bis")
    direct = _mk("Williams: Stability of Thy Times", "Williams", "nyfed")
    assert fetcher.identity_keys(bis) & fetcher.identity_keys(direct)


def test_colon_in_real_title_is_not_stripped():
    """Boston-style titles contain a colon that is NOT a speaker prefix."""
    item = _mk("The U.S. Economy: Resilience Amid Risks", "Susan M. Collins", "boston")
    assert "collins|the u s economy resilience amid risks" in fetcher.identity_keys(item)


def test_missing_speaker_still_matches_via_fallback_key():
    with_sp = _mk("Stability of Thy Times", "John C Williams", "bis")
    without = _mk("Stability of Thy Times", None, "nyfed")
    assert fetcher.identity_keys(with_sp) & fetcher.identity_keys(without)


def test_same_title_different_date_not_merged():
    a = _mk("Global imbalances growth and stability", None, "bis",
            published=date(2026, 7, 1))
    b = _mk("Global imbalances growth and stability", None, "bis",
            published=date(2026, 7, 20))
    assert not (fetcher.identity_keys(a) & fetcher.identity_keys(b))


def test_same_title_different_region_not_merged():
    a = _mk("Economic outlook", None, "bis", region="US")
    b = _mk("Economic outlook", None, "bis", region="Europe")
    assert not (fetcher.identity_keys(a) & fetcher.identity_keys(b))


def test_dedup_prefers_direct_source_over_bis():
    bis = _mk("Stability of Thy Times", "John C Williams", "bis")
    direct = _mk("Stability of Thy Times", "Williams", "nyfed")
    out = fetcher.dedup([bis, direct])
    assert len(out) == 1
    assert out[0].source == "nyfed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_identity.py -q`
Expected: FAIL with `AttributeError: module 'fetcher' has no attribute 'identity_keys'`

- [ ] **Step 3: Write the implementation**

In `fetcher.py`, replace `content_key` and `dedup` with:

```python
def _surname(speaker: str | None) -> str:
    return speaker.strip().split()[-1].lower() if speaker and speaker.strip() else ""


def _normalized_title(item: SpeechItem) -> str:
    """Lowercased, punctuation-stripped title with any speaker prefix removed.

    Both BIS ("John C Williams: Stability of Thy Times") and the NY Fed
    ("Williams: Stability of Thy Times") prefix the title with the speaker. The
    prefix is only stripped when it actually matches the item's speaker surname,
    so a genuine colon ("The U.S. Economy: Resilience...") is preserved.
    """
    title = item.title or ""
    if ":" in title:
        prefix, _, rest = title.partition(":")
        if _surname(prefix) and _surname(prefix) == _surname(item.speaker):
            title = rest
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def identity_keys(item: SpeechItem) -> set[str]:
    """Identity keys for a speech; two items are duplicates if these intersect.

    Key 1 (speaker) keeps the legacy `surname|title` format so entries already
    written to state/seen.json remain valid. Key 2 works even when a source
    stops emitting speakers, and is specific enough (title + date + region) not
    to merge genuinely distinct speeches. Region is used rather than bank
    because bank names differ across sources ("Federal Reserve" vs "Federal
    Reserve Bank of New York") while region always agrees.
    """
    title = _normalized_title(item)
    keys = {f"t|{title}|{item.published.isoformat()}|{item.region}"}
    surname = _surname(item.speaker)
    if surname:
        keys.add(f"{surname}|{title}")
    return keys


def dedup(items: list[SpeechItem]) -> list[SpeechItem]:
    """Collapse duplicates using any-key matching. A direct source beats BIS."""
    key_to_index: dict[str, int] = {}
    chosen: list[SpeechItem] = []
    for item in items:
        keys = identity_keys(item)
        hit = next((key_to_index[k] for k in keys if k in key_to_index), None)
        if hit is None:
            index = len(chosen)
            chosen.append(item)
            for k in keys:
                key_to_index[k] = index
        else:
            if chosen[hit].source == "bis" and item.source != "bis":
                log.info("dedup: preferring %s over bis for %r",
                         item.source, item.title[:60])
                chosen[hit] = item
            for k in keys:
                key_to_index.setdefault(k, hit)
    return chosen
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_identity.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Update the existing fetcher tests that referenced `content_key`**

`tests/test_fetcher.py` no longer needs its own dedup assertions for the old key
format — the dedup cases now live in `tests/test_identity.py`. Delete these three
tests from `tests/test_fetcher.py`:
`test_dedup_prefers_direct_feed_over_bis_same_key`,
`test_dedup_collapses_same_speech_across_different_urls`,
`test_distinct_speeches_are_kept`.

Run: `python -m pytest -q`
Expected: PASS (no failures)

- [ ] **Step 6: Commit**

```bash
git add fetcher.py tests/test_identity.py tests/test_fetcher.py
git commit -m "feat: two-key identity matching so a missing speaker cannot cause duplicates"
```

---

## Task 4: Multi-key `seen` membership

**Files:**
- Modify: `main.py`
- Test: `tests/test_main.py`

- [ ] **Step 1: Write the failing test**

Replace the contents of `tests/test_main.py` with:

```python
from datetime import date, timedelta
import fetcher
import main
from models import SpeechItem


def _item(title, days_ago, speaker=None, id_=None, region="US"):
    d = date.today() - timedelta(days=days_ago)
    id_ = id_ or ("https://x/" + title)
    return SpeechItem(id=id_, title=title, url=id_, published=d, speaker=speaker,
                      bank="b", region=region, source="fed")


def test_select_new_filters_seen_and_old():
    items = [_item("alpha", 0), _item("beta", 0), _item("gamma", 10)]
    seen = {k: "2026-06-01" for k in fetcher.identity_keys(_item("beta", 0))}
    new = main.select_new(items, seen, lookback_hours=48)
    assert {i.title for i in new} == {"alpha"}


def test_select_new_matches_on_any_key():
    """A speech first stored without a speaker is still recognised when it
    later arrives with one."""
    stored = _item("stability of thy times", 0, speaker=None)
    seen = {k: "2026-08-01" for k in fetcher.identity_keys(stored)}
    incoming = _item("stability of thy times", 0, speaker="John C Williams")
    assert main.select_new([incoming], seen, lookback_hours=48) == []


def test_legacy_single_key_still_suppresses():
    """Pre-existing seen.json entries use the bare `surname|title` format."""
    incoming = _item("economic outlook", 0, speaker="Lisa D Cook")
    seen = {"cook|economic outlook": "2026-07-16"}
    assert main.select_new([incoming], seen, lookback_hours=48) == []


def test_update_seen_writes_every_key():
    seen = {}
    item = _item("delta", 0, speaker="Jane Doe")
    main.update_seen(seen, [item], today="2026-08-04")
    assert fetcher.identity_keys(item) <= set(seen)
    assert all(v == "2026-08-04" for v in seen.values())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_main.py -q`
Expected: FAIL — `test_select_new_matches_on_any_key` fails, because the current
`select_new` compares a single `content_key`.

- [ ] **Step 3: Write the implementation**

In `main.py`, replace `select_new` and `update_seen` with:

```python
def select_new(items: list[SpeechItem], seen: dict[str, str],
               *, lookback_hours: int) -> list[SpeechItem]:
    """Items not already seen (by ANY identity key) and recent enough."""
    cutoff = date.today() - timedelta(hours=lookback_hours)
    return [i for i in items
            if not (fetcher.identity_keys(i) & seen.keys())
            and i.published >= cutoff]


def update_seen(seen: dict[str, str], items: list[SpeechItem],
                *, today: str) -> None:
    """Record every identity key so the speech is recognised from any source."""
    for i in items:
        for key in fetcher.identity_keys(i):
            seen[key] = today
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_main.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "feat: match seen speeches on any identity key"
```

---

## Task 5: Generic config-driven HTML listing scraper

**Files:**
- Create: `sources/html_list.py`
- Test: `tests/test_html_list.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_html_list.py`:

```python
from datetime import date
from sources import html_list

FEED = {
    "name": "demo", "kind": "html_list", "region": "US", "bank": "Demo Bank",
    "url": "https://demo.example/speeches", "base": "https://demo.example",
    "row_selector": "tr",
    "link_selector": "td.right a",
    "date_selector": "td.left",
    "date_formats": ["%b %d, %Y"],
}

HTML = """<table><tbody>
  <tr><td class="left"><div>Jul 15, 2026</div></td>
      <td class="right"><a href="/speeches/2026/a">Williams: Stability of Thy Times</a></td></tr>
  <tr><td class="left"><div>Jul 09, 2026</div></td>
      <td class="right"><a href="https://demo.example/speeches/2026/b">Perli: Repo Market Structure</a></td></tr>
  <tr><td class="left"><div>not a date</div></td>
      <td class="right"><a href="/speeches/2026/c">Bad: Row</a></td></tr>
  <tr><td class="left"><div>Jul 01, 2026</div></td><td class="right">no link</td></tr>
</tbody></table>"""


def test_parses_rows_into_items():
    items = html_list.parse_rows(HTML, FEED)
    assert [i.title for i in items] == ["Williams: Stability of Thy Times",
                                        "Perli: Repo Market Structure"]
    assert items[0].published == date(2026, 7, 15)
    assert items[0].bank == "Demo Bank"
    assert items[0].region == "US"
    assert items[0].source == "demo"


def test_relative_urls_resolve_against_base():
    items = html_list.parse_rows(HTML, FEED)
    assert items[0].url == "https://demo.example/speeches/2026/a"
    assert items[1].url == "https://demo.example/speeches/2026/b"


def test_rows_without_link_or_valid_date_are_skipped():
    assert len(html_list.parse_rows(HTML, FEED)) == 2


def test_speaker_derived_from_title_prefix():
    items = html_list.parse_rows(HTML, FEED)
    assert items[0].speaker == "Williams"


def test_speaker_selector_used_when_present():
    feed = dict(FEED, row_selector="div.row", link_selector="h1 a",
                date_selector="p.date", speaker_selector="ul.speaker a",
                date_formats=["%B %d, %Y"])
    html = """<div class="row">
      <h1><a href="/s/1">The U.S. Economy: Resilience Amid Risks</a></h1>
      <ul class="speaker"><li><a href="/p/1">Susan M. Collins, President &amp; CEO</a></li></ul>
      <p class="date">May 13, 2026    |Boston, Massachusetts</p>
    </div>"""
    items = html_list.parse_rows(html, feed)
    assert items[0].speaker == "Susan M. Collins"
    assert items[0].published == date(2026, 5, 13)


def test_duplicate_hrefs_collapse():
    """Nested row containers must not yield the same speech twice."""
    html = ('<div class="row"><div class="row">'
            '<h1><a href="/s/1">A Speech</a></h1><p class="date">May 13, 2026</p>'
            '</div></div>')
    feed = dict(FEED, row_selector="div.row", link_selector="h1 a",
                date_selector="p.date", date_formats=["%B %d, %Y"])
    assert len(html_list.parse_rows(html, feed)) == 1


def test_missing_speaker_is_reported_not_dropped():
    html = ('<table><tbody><tr><td class="left">Jul 15, 2026</td>'
            '<td class="right"><a href="/s/1">A speech with no speaker</a></td>'
            '</tr></tbody></table>')
    items = html_list.parse_rows(html, FEED)
    assert len(items) == 1                 # never dropped
    assert items[0].speaker is None
    assert html_list.count_missing_speakers(items) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_html_list.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'sources.html_list'`

- [ ] **Step 3: Write the implementation**

Create `sources/html_list.py`:

```python
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
from datetime import datetime

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
            return node.get_text(" ", strip=True).split(",")[0].strip() or None
    # Many listings use the "Speaker: Title" convention (NY Fed, BIS).
    if ":" in title:
        prefix = title.partition(":")[0].strip()
        if prefix and len(prefix.split()) <= 4:
            return prefix
    return None


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
        date_node = row.select_one(feed["date_selector"])
        if not date_node:
            continue
        published = _parse_date(date_node.get_text(" ", strip=True),
                                feed["date_formats"])
        if published is None:
            continue

        href = anchor["href"]
        url = href if href.startswith("http") else base + "/" + href.lstrip("/")
        if url in seen_urls:            # nested containers can repeat a row
            continue
        seen_urls.add(url)

        title = anchor.get_text(" ", strip=True)
        items.append(
            SpeechItem(
                id=url, title=title, url=url, published=published,
                speaker=_speaker_from_row(row, feed, title),
                bank=feed["bank"], region=feed["region"], source=feed["name"],
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
    r = httpx.get(feed["url"], headers=headers, timeout=config.HTTP_TIMEOUT_S,
                  follow_redirects=True)
    r.raise_for_status()
    items = parse_rows(r.text, feed)
    missing = count_missing_speakers(items)
    if missing:
        log.warning("%s: %d/%d items have no speaker — selector may have drifted",
                    feed["name"], missing, len(items))
    return items
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_html_list.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add sources/html_list.py tests/test_html_list.py
git commit -m "feat: generic config-driven HTML listing scraper"
```

---

## Task 6: Wire `html_list` into the fetcher and add NY + Boston

**Files:**
- Modify: `config.py`, `fetcher.py`
- Test: `tests/test_fetcher.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_fetcher.py`:

```python
def test_fetch_all_dispatches_html_list(monkeypatch):
    feeds = [{"name": "nyfed", "kind": "html_list", "region": "US",
              "bank": "Federal Reserve Bank of New York", "url": "u"}]
    monkeypatch.setattr(fetcher.config, "FEEDS", feeds)
    monkeypatch.setattr(fetcher.html_list, "fetch",
                        lambda feed: [_item("https://x/ny", "nyfed",
                                            title="Williams: Outlook",
                                            speaker="Williams")])
    items, counts = fetcher.fetch_all()
    assert [i.source for i in items] == ["nyfed"]
    assert counts["nyfed"]["items"] == 1


def test_fetch_all_reports_zero_for_failing_source(monkeypatch):
    feeds = [{"name": "nyfed", "kind": "html_list", "region": "US",
              "bank": "NY", "url": "u"}]
    monkeypatch.setattr(fetcher.config, "FEEDS", feeds)

    def boom(feed):
        raise RuntimeError("site down")

    monkeypatch.setattr(fetcher.html_list, "fetch", boom)
    items, counts = fetcher.fetch_all()
    assert items == []
    assert counts["nyfed"]["items"] == 0
```

Also update the three existing `fetch_all` tests in this file to unpack two
values — change each `out = fetcher.fetch_all()` to
`out, _counts = fetcher.fetch_all()`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fetcher.py -q`
Expected: FAIL with `AttributeError: module 'fetcher' has no attribute 'html_list'`

- [ ] **Step 3: Write the implementation**

In `fetcher.py`, change the sources import to:

```python
from sources import bis, html_list, rss
```

Replace `fetch_all` with:

```python
def fetch_all() -> tuple[list[SpeechItem], dict[str, dict[str, int]]]:
    """Fetch every configured source.

    Returns the deduped items plus a per-source report used by the health
    monitor: {name: {"items": n, "no_speaker": m}}. A source that raises is
    logged, reported as zero, and does not abort the run.
    """
    collected: list[SpeechItem] = []
    counts: dict[str, dict[str, int]] = {}
    for feed in config.FEEDS:
        name = feed["name"]
        try:
            if feed["kind"] == "playwright":
                parsed = _fetch_playwright(feed)
            elif feed["kind"] == "html_list":
                parsed = html_list.fetch(feed)
            else:
                parsed = _parse_feed(feed, _get(feed["url"]))
            if feed["kind"] == "bis":
                before = len(parsed)
                parsed = apply_freshness_gate(parsed)
                if before != len(parsed):
                    log.info("bis: dropped %d stale items (older than %dd)",
                             before - len(parsed), config.BIS_MAX_AGE_DAYS)
            counts[name] = {
                "items": len(parsed),
                "no_speaker": html_list.count_missing_speakers(parsed),
            }
            log.info("feed %s: %d items", name, len(parsed))
            collected.extend(parsed)
        except Exception as e:  # one source down must not abort the run
            log.warning("feed %s failed: %s: %s", name, type(e).__name__, e)
            counts[name] = {"items": 0, "no_speaker": 0}
    return dedup(collected), counts
```

In `config.py`, append these two entries to `FEEDS` (selectors verified against
the live pages on 2026-08-04):

```python
FEEDS += [
    {
        "name": "nyfed", "kind": "html_list", "region": "US",
        "bank": "Federal Reserve Bank of New York",
        "url": "https://www.newyorkfed.org/newsevents/speeches/index",
        "base": "https://www.newyorkfed.org",
        "row_selector": "tr",
        "link_selector": "td.dirColR a",
        "date_selector": "td.dirColL",
        "date_formats": ["%b %d, %Y"],
    },
    {
        "name": "bostonfed", "kind": "html_list", "region": "US",
        "bank": "Federal Reserve Bank of Boston",
        "url": "https://www.bostonfed.org/news-and-events/speeches.aspx",
        "base": "https://www.bostonfed.org",
        "row_selector": "div.row",
        "link_selector": "h1.card-title a",
        "date_selector": "p.date-and-location",
        "date_formats": ["%B %d, %Y"],
        "speaker_selector": "ul.speaker a",
    },
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest -q`
Expected: PASS (all tests)

- [ ] **Step 5: Verify against the live sites**

Run:
```bash
cd "C:\CB speech" && python -c "import logging; logging.basicConfig(level=logging.INFO); import fetcher; items, counts = fetcher.fetch_all(); print({k: v['items'] for k, v in counts.items()}); print('NY sample:', [(i.published.isoformat(), i.speaker, i.title[:40]) for i in items if i.source=='nyfed'][:3]); print('Boston sample:', [(i.published.isoformat(), i.speaker, i.title[:40]) for i in items if i.source=='bostonfed'][:3])"
```
Expected: `nyfed` and `bostonfed` both report a non-zero count; the samples show
a real date, a non-null speaker, and a plausible title for each. If either shows
zero, the site's markup has changed — re-inspect and update the selectors in
`config.py` before continuing.

- [ ] **Step 6: Commit**

```bash
git add config.py fetcher.py tests/test_fetcher.py
git commit -m "feat: add NY Fed and Boston Fed same-day speech sources"
```

---

## Task 7: Source-health tracking

**Files:**
- Modify: `config.py`, `main.py`
- Test: `tests/test_health.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_health.py`:

```python
import main


def test_zero_items_increments_and_nonzero_resets():
    health = {"nyfed": 2}
    counts = {"nyfed": {"items": 0, "no_speaker": 0},
              "fed": {"items": 5, "no_speaker": 0}}
    main.update_health(health, counts)
    assert health["nyfed"] == 3
    assert health["fed"] == 0


def test_alerts_only_at_threshold(monkeypatch):
    monkeypatch.setattr(main.config, "SOURCE_HEALTH_ALERT_RUNS", 3)
    assert main.health_alerts({"nyfed": 2}, {}) == []
    alerts = main.health_alerts({"nyfed": 3}, {})
    assert len(alerts) == 1
    assert "nyfed" in alerts[0]


def test_missing_speakers_produce_an_alert(monkeypatch):
    monkeypatch.setattr(main.config, "SOURCE_HEALTH_ALERT_RUNS", 3)
    counts = {"bostonfed": {"items": 10, "no_speaker": 4}}
    alerts = main.health_alerts({"bostonfed": 0}, counts)
    assert len(alerts) == 1
    assert "speaker" in alerts[0].lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_health.py -q`
Expected: FAIL with `AttributeError: module 'main' has no attribute 'update_health'`

- [ ] **Step 3: Write the implementation**

In `config.py`, add near `SEEN_FILE`:

```python
HEALTH_FILE = STATE_DIR / "source_health.json"
# Consecutive zero-item runs before a source is reported as probably broken.
SOURCE_HEALTH_ALERT_RUNS = 3
```

In `main.py`, add:

```python
def load_health() -> dict[str, int]:
    if not config.HEALTH_FILE.exists():
        return {}
    try:
        return json.loads(config.HEALTH_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("corrupt source_health.json — resetting")
        return {}


def update_health(health: dict[str, int],
                  counts: dict[str, dict[str, int]]) -> None:
    """Count consecutive zero-item runs per source."""
    for name, stats in counts.items():
        health[name] = health.get(name, 0) + 1 if stats["items"] == 0 else 0


def health_alerts(health: dict[str, int],
                  counts: dict[str, dict[str, int]]) -> list[str]:
    """Human-readable warnings for sources that look broken.

    A scraper that silently returns nothing is indistinguishable from a quiet
    news day, so it has to be surfaced explicitly.
    """
    alerts = []
    for name, runs in sorted(health.items()):
        if runs >= config.SOURCE_HEALTH_ALERT_RUNS:
            alerts.append(f"{name} has returned no items for {runs} consecutive "
                          f"runs — the source may be broken.")
    for name, stats in sorted(counts.items()):
        if stats.get("no_speaker"):
            alerts.append(f"{name}: {stats['no_speaker']} item(s) had no speaker "
                          f"— the byline selector may have drifted.")
    return alerts
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_health.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add config.py main.py tests/test_health.py
git commit -m "feat: track source health and alert on silently-broken sources"
```

---

## Task 8: Render health alerts in the digest

**Files:**
- Modify: `email_send.py`
- Test: `tests/test_email_send.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_email_send.py`:

```python
def test_health_alerts_render_when_present():
    rated = [_pair(2, "US", "Someone")]
    html = email_send.build_html(rated, alerts=["nyfed has returned no items."])
    assert "nyfed has returned no items." in html
    assert "Source health" in html


def test_no_alert_section_when_healthy():
    rated = [_pair(2, "US", "Someone")]
    html = email_send.build_html(rated, alerts=[])
    assert "Source health" not in html


def test_build_html_defaults_to_no_alerts():
    rated = [_pair(2, "US", "Someone")]
    assert "Source health" not in email_send.build_html(rated)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_email_send.py -q`
Expected: FAIL with `TypeError: build_html() got an unexpected keyword argument 'alerts'`

- [ ] **Step 3: Write the implementation**

In `email_send.py`, change the `build_html` signature and add the alert block.
Replace the `def build_html(rated: list[Rated]) -> str:` line with:

```python
def build_html(rated: list[Rated], alerts: list[str] | None = None) -> str:
```

Immediately after the `sections: list[str] = []` loop completes (i.e. just
before the final `return`), insert:

```python
    alert_html = ""
    if alerts:
        rows = "".join(f"<li>{_esc(a)}</li>" for a in alerts)
        alert_html = (
            "<div style='margin:16px 0; padding:10px 12px; border:1px solid #fcd34d; "
            "background:#fffbeb; border-radius:8px;'>"
            "<strong style='font-size:13px;'>⚠ Source health</strong>"
            f"<ul style='margin:6px 0 0; font-size:13px;'>{rows}</ul></div>"
        )
```

and insert `{alert_html}` into the returned HTML, directly after the date div:

```python
        f"<div style='color:#6b7280; font-size:12px;'>{today}</div>"
        f"{alert_html}"
        f"{''.join(sections)}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_email_send.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add email_send.py tests/test_email_send.py
git commit -m "feat: surface source-health warnings in the digest"
```

---

## Task 9: Wire health + counts through the orchestrator

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Update `run()` for the new fetch signature and health flow**

In `main.py`, inside `run()`:

Replace `items = fetcher.fetch_all()` with:

```python
    items, counts = fetcher.fetch_all()
    health = load_health()
    update_health(health, counts)
    alerts = health_alerts(health, counts)
    config.HEALTH_FILE.write_text(json.dumps(health, indent=2), encoding="utf-8")
    for a in alerts:
        log.warning("health: %s", a)
```

Replace `html = email_send.build_html(rated)` with:

```python
    html = email_send.build_html(rated, alerts=alerts)
```

- [ ] **Step 2: Run the full suite**

Run: `python -m pytest -q`
Expected: PASS (all tests)

- [ ] **Step 3: Commit**

```bash
git add main.py
git commit -m "feat: persist source health and include alerts in the digest"
```

---

## Task 10: End-to-end verification

**Files:** none (verification only)

- [ ] **Step 1: Confirm no stale BIS items survive the gate**

Run:
```bash
cd "C:\CB speech" && python -c "
import fetcher, datetime
items, counts = fetcher.fetch_all()
bis = [i for i in items if i.source == 'bis']
print('bis items kept:', len(bis))
oldest = min((i.published for i in bis), default=None)
print('oldest bis delivery date:', oldest)
print('counts:', {k: v['items'] for k, v in counts.items()})
"
```
Expected: `bis items kept` is small or zero, and any `oldest bis delivery date`
is within 7 days of today. Given the measured 14–31 day lag, zero is the normal
result and is correct.

- [ ] **Step 2: Confirm the NY Fed source would have caught the missed speech**

Run:
```bash
cd "C:\CB speech" && python -c "
from sources import html_list
import config
feed = next(f for f in config.FEEDS if f['name'] == 'nyfed')
items = html_list.fetch(feed)
print('nyfed items:', len(items))
for i in items[:6]:
    print(' ', i.published.isoformat(), '|', i.speaker, '|', i.title[:50])
"
```
Expected: a list of dated NY Fed speeches with non-null speakers, including
Williams entries. This is the source that would have delivered
"Williams: Stability of Thy Times" on 15 July rather than 3 August.

- [ ] **Step 3: Run the full test suite**

Run: `python -m pytest -q`
Expected: all tests pass, no failures.

- [ ] **Step 4: Commit any remaining changes and push**

```bash
git add -A
git commit -m "chore: phase 1 speech freshness verification"
git push
```

- [ ] **Step 5: Watch the next scheduled run**

After the next 06:00 UTC run, confirm in the repo that `runs.log` shows a normal
`ok` line, `state/source_health.json` exists with zeros for healthy sources, and
the digest email contains no speeches older than two days.

---

## Self-review notes

- **Spec coverage:** BIS true-date parsing (Task 1), freshness gate (Task 2),
  two-key identity + runtime speaker handling (Tasks 3, 5), multi-key `seen`
  (Task 4), generic `html_list` scraper (Task 5), direct sources (Task 6),
  source-health monitoring (Tasks 7–9), verification (Task 10). The spec's
  `js_list` generalization belongs to Phases 2–3 and is deliberately not built
  here — nothing in Phase 1 needs it, and the existing `ecb_playwright.py`
  continues to work untouched.
- **Deviation from spec:** Richmond, Cleveland and Atlanta are dropped from
  Phase 1 (see Scope note) because their listings are not parseable over plain
  HTTP; specifying them would have required guessed selectors.
- **Backward compatibility:** identity key 1 keeps the exact legacy
  `surname|title` format, so every entry already in `state/seen.json` still
  suppresses its speech and nothing previously emailed can resurface. Tested in
  `test_legacy_single_key_still_suppresses`.
- **Type consistency:** `fetch_all()` returns `(items, counts)` in Task 6 and is
  consumed that way in Tasks 6, 9 and 10; `identity_keys` is defined in Task 3
  and used in Tasks 3 and 4; `count_missing_speakers` is defined in Task 5 and
  used in Task 6; `build_html(rated, alerts=None)` is defined in Task 8 and
  called with `alerts=` in Task 9.
- **Failure direction:** unparseable BIS dates fail closed (dropped, never shown
  as fresh); missing speakers fail open (item kept, source flagged) so no speech
  is ever silently lost.
