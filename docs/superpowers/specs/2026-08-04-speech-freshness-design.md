# Speech freshness — true dates, BIS gating, and direct sources

**Date:** 2026-08-04
**Status:** Approved (pending spec review)
**Extends:** the CB speech daily digest agent (2026-06-06 design).

## Problem

The digest emails speeches 2–3 weeks after they were delivered, presented as if
they were new.

## Root cause (measured, not assumed)

The 2026-06-06 design assumed the BIS aggregator lagged "1–3 days". That
assumption was wrong. Measured across all 25 entries in the live BIS feed on
2026-08-04:

| BIS publication lag vs. actual delivery |
|---|
| min **14 days**, median **20 days**, max **31 days** — 25/25 entries >3 days |

Two independent defects follow:

1. **Wrong date stamp.** The BIS feed's `pubDate` element is empty, so
   `sources/rss.py:_entry_date` falls back through `updated_parsed` to BIS's own
   *upload* timestamp. A speech delivered 14 July that BIS uploaded 3 August is
   stamped 3 August, passes the 48-hour lookback, and is emailed as new. The true
   delivery date is present in the description tail (BIS Review convention:
   "…, Washington DC, 14 July 2026.") and parses reliably — **25/25 entries**.

2. **Timeliness depends on having a direct source.** Confirmed by cross-check:
   Bowman's "Responsible innovation and financial inclusion" was delivered
   14 July, emailed by this agent on **15 July** (via the direct Fed Board RSS
   feed), and only published by BIS on **3 August**. Speakers *with* a direct
   feed are timely, and the late BIS copy is silently discarded by the existing
   content-key dedup. Speakers *without* one — regional Fed presidents such as
   John Williams (NY), and eurozone national governors such as Nagel, Panetta,
   Villeroy — are first seen via BIS, so there is nothing to dedup against and
   they arrive ~3 weeks late.

## Decisions (locked)

- **Keep BIS.** It is a free backstop; when it is prompt we benefit, when it is
  slow we ignore it. Do not remove it from the source list.
- **Gate BIS on true delivery date**, so weeks-old backfill is ignored.
- **Add direct sources** for the speakers that currently depend on BIS, so they
  are captured when released.
- Accepted consequence: after the date fix, a speaker with no direct source is
  **absent** rather than late. This is intended.

## Changes

### 1. BIS true-date parsing (`sources/bis.py`)

Add `parse_delivery_date(description) -> date | None`: strip HTML tags, find all
`D Month YYYY` occurrences, return the **last** one (the BIS convention places
the event location and date at the end of the description). Use it for
`SpeechItem.published`. If parsing fails, fall back to the feed's upload date and
mark the item so the freshness gate treats it as stale (fail closed — never
present an unknown-age item as fresh).

### 2. BIS freshness gate (`config.py`, `fetcher.py`)

New `BIS_MAX_AGE_DAYS = 7`. A BIS item is kept only if its delivery date is
within that many days of today. Direct feeds continue to use the existing
48-hour lookback in `main.select_new`. Seven days is deliberately wider than the
48-hour window so a genuinely prompt BIS post is still caught, while the observed
14–31 day backfill is excluded.

### 3. Generic config-driven scrapers

Rather than one module per bank (~20 modules), two reusable parsers driven by
config entries:

- **`sources/html_list.py`** — plain HTTP + BeautifulSoup. Config shape:

  ```python
  {
    "name": "nyfed", "kind": "html_list",
    "region": "US", "bank": "Federal Reserve Bank of New York",
    "url": "https://www.newyorkfed.org/newsevents/speeches/index",
    "base": "https://www.newyorkfed.org",
    "row_selector": "...",       # CSS selecting each listing row
    "link_selector": "a",        # anchor within the row
    "date_selector": "...",      # element within the row holding the date
    "date_formats": ["%B %d, %Y", "%Y-%m-%d"],
    "speaker_selector": "...",   # optional; see Speaker extraction below
  }
  ```

  Exposes a pure `parse_rows(html, feed) -> list[SpeechItem]` (unit-testable on
  fixture HTML) plus a thin `fetch(feed)` that performs the HTTP GET.

- **`sources/js_list.py`** — the existing `sources/ecb_playwright.py`
  generalized to the same config shape, for JS-rendered sites (Phase 3 and any
  Phase 2 bank that needs it). `ecb_playwright.py` is refactored to use it so
  there is a single Playwright code path.

`fetcher._parse_feed` gains `html_list` and `js_list` dispatch branches
alongside the existing `rss`, `bis`, and `playwright` kinds.

### 4. Speaker extraction (required for dedup)

`fetcher.content_key` is `speaker-surname | normalized-title`. If a direct source
yields `speaker=None` while the BIS copy has a speaker, the two keys differ and a
prompt BIS copy could be emailed as a duplicate. Each `html_list` config
therefore must yield a speaker: via `speaker_selector`, or — when the listing
embeds it in the title as "Speaker: Title" — by the same prefix split
`sources/bis.py` already performs. Configs are validated in tests to produce a
non-null speaker on their fixture.

### 5. Source-health monitoring (`main.py`, `email_send.py`)

New `state/source_health.json`: `{source_name: consecutive_zero_runs}`. After
each fetch, a source returning zero items increments its counter; any non-zero
result resets it. When a counter reaches `SOURCE_HEALTH_ALERT_RUNS = 3`, the
digest renders a warning line ("⚠ nyfed has returned no items for 3 runs — the
scraper may be broken") and the condition is written to `runs.log`.

Rationale: with ~20 scrapers, a silently-broken source is indistinguishable from
a quiet news day. Without this, a speaker can be lost for weeks unnoticed —
which is the same class of failure this whole spec exists to fix.

## Phase 1 scope (this implementation)

1. BIS true-date parsing + freshness gate.
2. `sources/html_list.py` + `fetcher` dispatch.
3. Five regional Fed sources, all confirmed plain-HTTP scrapeable on 2026-08-04:
   New York, Boston, Richmond, Cleveland, Atlanta.
4. Source-health monitoring.

Later phases, out of scope here:
- **Phase 2** — eurozone NCBs: Bundesbank, Banque de France, Banca d'Italia,
  DNB, Banco de España. No working RSS found (all 403/404 or declare no feed);
  each needs individual investigation and likely `js_list`.
- **Phase 3** — the seven hard regional Feds: SF, Dallas, Minneapolis,
  Philadelphia (JS-rendered), Chicago (404), St. Louis and Kansas City
  (blocking/timeouts), via `js_list`.

## Data flow

Unchanged. New sources produce `SpeechItem`s that join the existing
dedup → lookback → extract → rate → email → persist pipeline. The only new
decision point is the BIS freshness gate, applied in `fetcher` at parse time.

## Error handling

Inherits existing behaviour: a source that fails or changes layout is logged and
skipped without aborting the run; extraction failure falls back to title-only
rating at low confidence; rating failure shows the item unrated and does not mark
it seen. New: a failing source now also trips the health counter.

## Testing

- `bis.parse_delivery_date`: extracts the trailing date from real description
  strings; returns `None` on malformed input; picks the **last** date when the
  description contains several.
- `bis.parse_feed`: `published` is the delivery date, not the upload date.
- Freshness gate: an item delivered 20 days ago is dropped; one delivered
  yesterday is kept; an unparseable date is dropped (fail closed).
- `html_list.parse_rows`: extracts title/url/date/speaker from a saved fixture
  for each of the five banks; relative URLs resolve against `base`; rows missing
  a link or date are skipped.
- Speaker present: each of the five configs yields a non-null speaker on its
  fixture (guards the dedup contract).
- `fetcher`: dispatches `html_list`; a failing html source is skipped without
  aborting; existing rss/bis/playwright behaviour unchanged.
- Source health: counter increments on zero, resets on non-zero, and the digest
  renders the warning at the threshold.
- Regression: existing 32 tests continue to pass.
- Live check (manual): `fetch_all()` returns items from all five new sources and
  no BIS item older than `BIS_MAX_AGE_DAYS`.

## Risks

- **Scraper fragility.** Five HTML scrapers will break when sites redesign.
  Mitigated by source-health alerting (§5) and by config-driven selectors that
  are a one-line fix rather than a code change.
- **Coverage gap between phases.** Eurozone national governors have no coverage
  from the moment the freshness gate lands until Phase 2 completes. The ECB
  itself remains same-day via the existing scraper. Accepted explicitly.
- **BIS description convention drift.** If BIS stops appending the delivery date,
  parsing fails and — by the fail-closed rule — BIS items are all treated as
  stale, silently reducing BIS to nothing. The health monitor catches this as a
  zero-item source.
