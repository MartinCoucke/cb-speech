# CB Speech daily digest agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A scheduled Python agent that emails a daily digest of new central bank speeches (US, Europe, UK, Australia, Canada), each rated dovish↔hawkish with a confidence level, hosted on GitHub Actions.

**Architecture:** Per-feed fetchers (direct RSS for the 5 majors + BIS aggregator) → dedup against a committed `state/seen.json` → extract full speech text → one Claude Sonnet 4.6 structured-output call per speech for the rating/summary → grouped HTML email via Gmail SMTP → commit state back to the repo. Mirrors the `Active ETF` project layout.

**Tech Stack:** Python 3.12, `feedparser` (RSS/Atom), `httpx` (HTTP), `beautifulsoup4` (HTML), `pypdf` (PDF), `anthropic` (Sonnet 4.6), `pytest` (tests). Gmail SMTP for email. GitHub Actions cron for scheduling.

---

## File structure

| File | Responsibility |
|---|---|
| `models.py` | `SpeechItem` and `Rating` dataclasses (shared data shapes) |
| `config.py` | Feeds, email config, model id, lookback window, paths, HTTP settings |
| `creds.py` | Load `GMAIL_APP_PASSWORD` + `ANTHROPIC_API_KEY` (env-first → `secrets.txt`) |
| `sources/__init__.py` | Marks `sources` as a package |
| `sources/rss.py` | Generic RSS/Atom feed → `list[SpeechItem]` + `normalize_url` |
| `sources/bis.py` | BIS feed → `list[SpeechItem]` with speaker→bank/region mapping |
| `fetcher.py` | Fetch every configured feed, dispatch to parser, dedup by id |
| `extract.py` | Fetch a speech page → clean text (HTML + PDF) |
| `rate.py` | Build prompt, call Sonnet 4.6 with structured output, parse `Rating` |
| `email_send.py` | Build grouped HTML digest + subject, send via Gmail SMTP |
| `main.py` | Orchestrator + `select_new` / `update_seen` helpers |
| `requirements.txt` | Python deps |
| `pytest.ini` | Test config (`pythonpath = .`) |
| `.gitignore` | Ignore secrets/caches |
| `.github/workflows/cb_speeches.yml` | Daily cron + commit-state workflow |
| `README.md` | Setup + operations docs |
| `tests/test_*.py` | Unit tests per module |

---

## Task 0: Project scaffolding

**Files:**
- Create: `C:\CB speech\requirements.txt`
- Create: `C:\CB speech\pytest.ini`
- Create: `C:\CB speech\.gitignore`

- [ ] **Step 1: Create `requirements.txt`**

```
anthropic>=0.45.0
feedparser>=6.0.11
httpx>=0.27.0
beautifulsoup4>=4.12.0
pypdf>=4.0.0
pytest>=8.0.0
```

- [ ] **Step 2: Create `pytest.ini`**

```ini
[pytest]
pythonpath = .
testpaths = tests
```

- [ ] **Step 3: Create `.gitignore`**

```
__pycache__/
*.pyc
.venv/
secrets.txt
.pytest_cache/
```

- [ ] **Step 4: Initialize git and install deps**

Run:
```bash
cd "C:\CB speech" && git init && python -m pip install -r requirements.txt
```
Expected: git repo initialized; pip installs all packages without error.

- [ ] **Step 5: Commit**

```bash
git add requirements.txt pytest.ini .gitignore
git commit -m "chore: project scaffolding"
```

---

## Task 1: Data models

**Files:**
- Create: `models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models.py
from datetime import date
from models import SpeechItem, Rating


def test_speechitem_holds_fields():
    item = SpeechItem(
        id="https://x/y",
        title="A speech",
        url="https://x/y",
        published=date(2026, 6, 5),
        speaker="Jane Doe",
        bank="Federal Reserve",
        region="US",
        source="fed",
    )
    assert item.region == "US"
    assert item.speaker == "Jane Doe"


def test_rating_defaults_for_optional_fields():
    r = Rating(
        score=-2,
        confidence="high",
        is_monetary_policy=True,
        summary="s",
        stance_rationale="r",
        key_quotes=["q"],
    )
    assert r.text_available is True
    assert r.error is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'models'`

- [ ] **Step 3: Write minimal implementation**

```python
# models.py
"""Shared data shapes for the CB speech agent."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class SpeechItem:
    id: str            # normalized URL — the dedup key
    title: str
    url: str
    published: date
    speaker: str | None
    bank: str
    region: str        # one of: US, Europe, UK, Australia, Canada
    source: str        # feed name that produced this item


@dataclass
class Rating:
    score: int                 # -5 (very dovish) .. +5 (very hawkish)
    confidence: str            # high | medium | low
    is_monetary_policy: bool
    summary: str
    stance_rationale: str
    key_quotes: list[str] = field(default_factory=list)
    text_available: bool = True
    error: str | None = None   # set when the rating could not be produced
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_models.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add models.py tests/test_models.py
git commit -m "feat: SpeechItem and Rating data models"
```

---

## Task 2: Configuration

**Files:**
- Create: `config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
import config


def test_feeds_have_required_keys():
    assert config.FEEDS, "FEEDS must not be empty"
    for f in config.FEEDS:
        assert {"name", "url", "kind", "region", "bank"} <= set(f.keys())
        assert f["kind"] in ("rss", "bis")


def test_five_regions_have_a_direct_feed():
    direct_regions = {f["region"] for f in config.FEEDS if f["kind"] == "rss"}
    assert {"US", "Europe", "UK", "Australia", "Canada"} <= direct_regions


def test_model_is_sonnet():
    assert config.MODEL == "claude-sonnet-4-6"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 3: Write minimal implementation**

```python
# config.py
"""CB speech agent configuration. All constants live here."""
from __future__ import annotations

from pathlib import Path

# --- Paths --------------------------------------------------------------
HERE = Path(__file__).parent
STATE_DIR = HERE / "state"
ARCHIVE_DIR = HERE / "archive"
SEEN_FILE = STATE_DIR / "seen.json"
RUNS_LOG = HERE / "runs.log"
_LOCAL_SECRETS = HERE / "secrets.txt"
SECRETS_FILE = _LOCAL_SECRETS

# --- Feeds --------------------------------------------------------------
# Direct RSS for the five majors (same-day fresh) + BIS catch-all for
# regional Fed presidents and eurozone national governors (1-3 day lag).
# NOTE: these URLs are verified live in Task 6; if a central bank changes
# its feed path, update it here — that is the only place feed URLs live.
FEEDS = [
    {"name": "fed", "kind": "rss", "region": "US", "bank": "Federal Reserve",
     "url": "https://www.federalreserve.gov/feeds/speeches.xml"},
    {"name": "ecb", "kind": "rss", "region": "Europe", "bank": "ECB",
     "url": "https://www.ecb.europa.eu/rss/speech.html"},
    {"name": "boe", "kind": "rss", "region": "UK", "bank": "Bank of England",
     "url": "https://www.bankofengland.co.uk/rss/speeches"},
    {"name": "rba", "kind": "rss", "region": "Australia", "bank": "Reserve Bank of Australia",
     "url": "https://www.rba.gov.au/rss/rss-cb-speeches.xml"},
    {"name": "boc", "kind": "rss", "region": "Canada", "bank": "Bank of Canada",
     "url": "https://www.bankofcanada.ca/content_type/speeches/feed/"},
    {"name": "bis", "kind": "bis", "region": "", "bank": "",
     "url": "https://www.bis.org/doclist/cbspeeches.rss"},
]

# --- Dedup / freshness --------------------------------------------------
LOOKBACK_HOURS = 48  # only treat items published within this window as "new"

# --- Model --------------------------------------------------------------
MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1024
# Cap text sent to the model so a huge PDF doesn't blow up cost/latency.
MAX_TEXT_CHARS = 40_000

# --- Email --------------------------------------------------------------
GMAIL_SMTP_HOST = "smtp.gmail.com"
GMAIL_SMTP_PORT = 587
SENDER_EMAIL = "martin.coucke68@gmail.com"
RECIPIENT_EMAILS = [
    "martin.coucke@hotmail.fr",
    "martin.coucke@schroders.com",
]
SUBJECT_TEMPLATE = "CB speeches — {summary} — {date}"
REGION_ORDER = ["US", "Europe", "UK", "Australia", "Canada"]

# --- HTTP ---------------------------------------------------------------
HTTP_TIMEOUT_S = 30
HTTP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat: agent configuration (feeds, email, model)"
```

---

## Task 3: Credentials loader

**Files:**
- Create: `creds.py`
- Test: `tests/test_creds.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_creds.py
import pytest
import creds


def test_load_prefers_env(monkeypatch):
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "pw")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
    out = creds.load()
    assert out == {"GMAIL_APP_PASSWORD": "pw", "ANTHROPIC_API_KEY": "key"}


def test_load_reads_secrets_file(monkeypatch, tmp_path):
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    f = tmp_path / "secrets.txt"
    f.write_text("GMAIL_APP_PASSWORD=pw\nANTHROPIC_API_KEY=key\n", encoding="utf-8")
    monkeypatch.setattr(creds.config, "SECRETS_FILE", f)
    assert creds.load()["ANTHROPIC_API_KEY"] == "key"


def test_load_raises_when_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(creds.config, "SECRETS_FILE", tmp_path / "nope.txt")
    with pytest.raises(FileNotFoundError):
        creds.load()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_creds.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'creds'`

- [ ] **Step 3: Write minimal implementation**

```python
# creds.py
"""Load secrets, env-first (GitHub Actions) then secrets.txt (local)."""
from __future__ import annotations

import os

import config

_REQUIRED = ("GMAIL_APP_PASSWORD", "ANTHROPIC_API_KEY")


def _parse(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def load() -> dict[str, str]:
    env = {k: os.environ.get(k) for k in _REQUIRED}
    if all(env.values()):
        return {k: v for k, v in env.items()}  # type: ignore[misc]

    if not config.SECRETS_FILE.exists():
        raise FileNotFoundError(
            f"Missing secrets. Set env vars {_REQUIRED} or create "
            f"{config.SECRETS_FILE} with one KEY=value per line."
        )
    data = _parse(config.SECRETS_FILE.read_text(encoding="utf-8-sig"))
    missing = [k for k in _REQUIRED if k not in data]
    if missing:
        raise KeyError(f"Missing {missing} in {config.SECRETS_FILE}")
    return {k: data[k] for k in _REQUIRED}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_creds.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add creds.py tests/test_creds.py
git commit -m "feat: credentials loader (env-first, secrets.txt fallback)"
```

---

## Task 4: Generic RSS source

**Files:**
- Create: `sources/__init__.py`
- Create: `sources/rss.py`
- Test: `tests/test_rss.py`

- [ ] **Step 1: Create the package marker**

Create `sources/__init__.py` with a single line:

```python
"""Feed source parsers."""
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_rss.py
from datetime import date
from sources import rss

SAMPLE = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Inflation outlook</title>
    <link>https://www.federalreserve.gov/speech/a.htm/</link>
    <pubDate>Thu, 05 Jun 2026 10:00:00 GMT</pubDate>
    <author>Jane Doe</author>
  </item>
  <item>
    <title>Payments policy</title>
    <link>https://www.federalreserve.gov/speech/b.htm#top</link>
    <pubDate>Wed, 04 Jun 2026 09:00:00 GMT</pubDate>
  </item>
</channel></rss>"""


def test_normalize_url_strips_fragment_and_trailing_slash():
    assert rss.normalize_url("https://x/y/#z") == "https://x/y"
    assert rss.normalize_url("https://x/y/") == "https://x/y"


def test_parse_feed_returns_items():
    items = rss.parse_feed(SAMPLE, default_bank="Federal Reserve",
                           region="US", source="fed")
    assert len(items) == 2
    first = items[0]
    assert first.title == "Inflation outlook"
    assert first.id == "https://www.federalreserve.gov/speech/a.htm"
    assert first.published == date(2026, 6, 5)
    assert first.speaker == "Jane Doe"
    assert first.bank == "Federal Reserve"
    assert first.region == "US"
    # fragment normalized away
    assert items[1].id == "https://www.federalreserve.gov/speech/b.htm"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_rss.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sources.rss'`

- [ ] **Step 4: Write minimal implementation**

```python
# sources/rss.py
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_rss.py -v`
Expected: PASS (3 passed)

- [ ] **Step 6: Commit**

```bash
git add sources/__init__.py sources/rss.py tests/test_rss.py
git commit -m "feat: generic RSS source parser"
```

---

## Task 5: BIS source with region mapping

**Files:**
- Create: `sources/bis.py`
- Test: `tests/test_bis.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bis.py
from sources import bis

SAMPLE = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Loretta Mester: Outlook for the US economy</title>
    <link>https://www.bis.org/review/r260605a.htm</link>
    <pubDate>Thu, 05 Jun 2026 10:00:00 GMT</pubDate>
    <description>Speech by Ms Loretta Mester, Federal Reserve Bank of Cleveland</description>
  </item>
  <item>
    <title>Joachim Nagel: German inflation</title>
    <link>https://www.bis.org/review/r260605b.htm</link>
    <pubDate>Thu, 05 Jun 2026 11:00:00 GMT</pubDate>
    <description>Speech by Mr Joachim Nagel, Deutsche Bundesbank</description>
  </item>
  <item>
    <title>Kazuo Ueda: Japan policy</title>
    <link>https://www.bis.org/review/r260605c.htm</link>
    <pubDate>Thu, 05 Jun 2026 12:00:00 GMT</pubDate>
    <description>Speech by Mr Kazuo Ueda, Bank of Japan</description>
  </item>
</channel></rss>"""


def test_map_text_to_region():
    assert bis.map_region("Federal Reserve Bank of Cleveland") == ("Federal Reserve", "US")
    assert bis.map_region("Deutsche Bundesbank") == ("Bundesbank", "Europe")
    assert bis.map_region("Bank of Japan") is None


def test_parse_feed_keeps_target_regions_only():
    items = bis.parse_feed(SAMPLE)
    # Japan dropped; US + Europe kept
    regions = sorted(i.region for i in items)
    assert regions == ["Europe", "US"]
    us = next(i for i in items if i.region == "US")
    assert us.bank == "Federal Reserve"
    assert us.source == "bis"
    assert us.id == "https://www.bis.org/review/r260605a.htm"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_bis.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'sources.bis'`

- [ ] **Step 3: Write minimal implementation**

```python
# sources/bis.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_bis.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add sources/bis.py tests/test_bis.py
git commit -m "feat: BIS source parser with speaker->region mapping"
```

---

## Task 6: Fetcher (dispatch + dedup) and live feed check

**Files:**
- Create: `fetcher.py`
- Test: `tests/test_fetcher.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fetcher.py
from datetime import date
import fetcher
from models import SpeechItem


def _item(id_, source):
    return SpeechItem(id=id_, title="t", url=id_, published=date(2026, 6, 5),
                      speaker=None, bank="b", region="US", source=source)


def test_dedup_prefers_direct_feed_over_bis():
    direct = _item("https://x/a", "fed")
    bis = _item("https://x/a", "bis")
    out = fetcher.dedup([bis, direct])  # bis first; direct should win
    assert len(out) == 1
    assert out[0].source == "fed"


def test_fetch_all_dispatches_and_concatenates(monkeypatch):
    feeds = [
        {"name": "fed", "kind": "rss", "region": "US", "bank": "Fed", "url": "u1"},
        {"name": "bis", "kind": "bis", "region": "", "bank": "", "url": "u2"},
    ]
    monkeypatch.setattr(fetcher.config, "FEEDS", feeds)
    monkeypatch.setattr(fetcher, "_get", lambda url: f"<xml for {url}>")
    monkeypatch.setattr(fetcher.rss, "parse_feed",
                        lambda text, **k: [_item("https://x/a", "fed")])
    monkeypatch.setattr(fetcher.bis, "parse_feed",
                        lambda text: [_item("https://x/b", "bis")])
    out = fetcher.fetch_all()
    assert {i.id for i in out} == {"https://x/a", "https://x/b"}


def test_fetch_all_skips_a_failing_feed(monkeypatch):
    feeds = [
        {"name": "fed", "kind": "rss", "region": "US", "bank": "Fed", "url": "u1"},
        {"name": "boe", "kind": "rss", "region": "UK", "bank": "BoE", "url": "u2"},
    ]
    monkeypatch.setattr(fetcher.config, "FEEDS", feeds)

    def boom(url):
        if url == "u1":
            raise RuntimeError("down")
        return "<xml>"

    monkeypatch.setattr(fetcher, "_get", boom)
    monkeypatch.setattr(fetcher.rss, "parse_feed",
                        lambda text, **k: [_item("https://x/b", "boe")])
    out = fetcher.fetch_all()
    assert {i.id for i in out} == {"https://x/b"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_fetcher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'fetcher'`

- [ ] **Step 3: Write minimal implementation**

```python
# fetcher.py
"""Fetch every configured feed, dispatch to the right parser, dedup by id."""
from __future__ import annotations

import logging

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


def _parse_feed(feed: dict, text: str) -> list[SpeechItem]:
    if feed["kind"] == "bis":
        return bis.parse_feed(text)
    return rss.parse_feed(text, default_bank=feed["bank"],
                          region=feed["region"], source=feed["name"])


def dedup(items: list[SpeechItem]) -> list[SpeechItem]:
    """Collapse duplicate ids. A non-bis (direct) source wins over bis."""
    best: dict[str, SpeechItem] = {}
    for it in items:
        cur = best.get(it.id)
        if cur is None:
            best[it.id] = it
        elif cur.source == "bis" and it.source != "bis":
            best[it.id] = it
    return list(best.values())


def fetch_all() -> list[SpeechItem]:
    collected: list[SpeechItem] = []
    for feed in config.FEEDS:
        try:
            text = _get(feed["url"])
            parsed = _parse_feed(feed, text)
            log.info("feed %s: %d items", feed["name"], len(parsed))
            collected.extend(parsed)
        except Exception as e:  # one feed down must not abort the run
            log.warning("feed %s failed: %s: %s", feed["name"], type(e).__name__, e)
    return dedup(collected)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_fetcher.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Verify the live feed URLs resolve and parse**

Run:
```bash
cd "C:\CB speech" && python -c "import fetcher; items = fetcher.fetch_all(); import collections; c = collections.Counter(i.source for i in items); print(dict(c)); print('total', len(items))"
```
Expected: a non-empty dict with most of `fed, ecb, boe, rba, boc, bis` present and `total` > 0. **If a feed name is missing or `total` is 0**, that feed's URL in `config.FEEDS` is wrong — open the central bank's site, find its current RSS URL, update `config.py`, and re-run. Do not proceed until at least the five direct feeds plus BIS return items (BIS may legitimately contribute 0 on a quiet day, but should not error).

- [ ] **Step 6: Commit**

```bash
git add fetcher.py tests/test_fetcher.py config.py
git commit -m "feat: feed fetcher with dispatch, dedup, and resilient per-feed errors"
```

---

## Task 7: Speech text extraction

**Files:**
- Create: `extract.py`
- Test: `tests/test_extract.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_extract.py
import extract


def test_extract_from_html_strips_boilerplate():
    html = """<html><head><title>x</title></head><body>
      <nav>menu menu menu</nav>
      <main><p>The committee will keep rates restrictive.</p>
      <p>Inflation remains elevated.</p></main>
      <script>var x=1;</script>
      <footer>copyright</footer></body></html>"""
    text = extract.extract_from_html(html)
    assert "rates restrictive" in text
    assert "Inflation remains elevated" in text
    assert "var x=1" not in text
    assert "menu menu menu" not in text


def test_extract_text_routes_pdf_vs_html(monkeypatch):
    class FakeResp:
        def __init__(self, ctype, body):
            self.headers = {"content-type": ctype}
            self.content = body
            self.text = body.decode() if isinstance(body, bytes) else body

        def raise_for_status(self):
            pass

    monkeypatch.setattr(extract, "extract_from_html", lambda h: "HTML")
    monkeypatch.setattr(extract, "extract_from_pdf", lambda b: "PDF")

    monkeypatch.setattr(extract.httpx, "get",
                        lambda *a, **k: FakeResp("text/html; charset=utf-8", "<p>hi</p>"))
    assert extract.extract_text("https://x/a.htm") == "HTML"

    monkeypatch.setattr(extract.httpx, "get",
                        lambda *a, **k: FakeResp("application/pdf", b"%PDF-1.4"))
    assert extract.extract_text("https://x/a.pdf") == "PDF"


def test_extract_text_returns_none_on_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network")
    monkeypatch.setattr(extract.httpx, "get", boom)
    assert extract.extract_text("https://x/a") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_extract.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'extract'`

- [ ] **Step 3: Write minimal implementation**

```python
# extract.py
"""Fetch a speech page and return clean plain text (HTML or PDF)."""
from __future__ import annotations

import io
import logging

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

import config

log = logging.getLogger(__name__)


def extract_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = main.get_text(separator="\n")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)


def extract_from_pdf(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    parts = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(p.strip() for p in parts if p.strip())


def extract_text(url: str) -> str | None:
    """Return clean text, or None if the page can't be fetched/parsed."""
    try:
        headers = {"User-Agent": config.HTTP_USER_AGENT}
        r = httpx.get(url, headers=headers, timeout=config.HTTP_TIMEOUT_S,
                      follow_redirects=True)
        r.raise_for_status()
        ctype = r.headers.get("content-type", "").lower()
        if "pdf" in ctype or url.lower().endswith(".pdf"):
            text = extract_from_pdf(r.content)
        else:
            text = extract_from_html(r.text)
        return text or None
    except Exception as e:
        log.warning("extract failed for %s: %s: %s", url, type(e).__name__, e)
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_extract.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add extract.py tests/test_extract.py
git commit -m "feat: speech text extraction (HTML + PDF)"
```

---

## Task 8: Rating via Claude Sonnet 4.6

**Files:**
- Create: `rate.py`
- Test: `tests/test_rate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rate.py
import json
from datetime import date
import types

import rate
from models import SpeechItem


def _item():
    return SpeechItem(id="https://x/a", title="Outlook", url="https://x/a",
                      published=date(2026, 6, 5), speaker="Jane Doe",
                      bank="Federal Reserve", region="US", source="fed")


def test_build_prompt_includes_title_and_text():
    p = rate.build_prompt(_item(), "rates will stay restrictive")
    assert "Outlook" in p
    assert "rates will stay restrictive" in p


def test_parse_rating_from_payload():
    payload = {
        "score": 3, "confidence": "high", "is_monetary_policy": True,
        "summary": "s", "stance_rationale": "r", "key_quotes": ["q1"],
    }
    r = rate.parse_rating(payload, text_available=True)
    assert r.score == 3
    assert r.confidence == "high"
    assert r.text_available is True
    assert r.error is None


class _FakeClient:
    def __init__(self, payload):
        block = types.SimpleNamespace(type="text", text=json.dumps(payload))
        msg = types.SimpleNamespace(content=[block])
        self.messages = types.SimpleNamespace(create=lambda **k: msg)


def test_rate_uses_client_and_returns_rating():
    payload = {
        "score": -2, "confidence": "medium", "is_monetary_policy": True,
        "summary": "dovish tone", "stance_rationale": "rate cuts hinted",
        "key_quotes": ["we may ease"],
    }
    r = rate.rate(_item(), "some speech text", client=_FakeClient(payload))
    assert r.score == -2
    assert r.summary == "dovish tone"


def test_rate_without_text_forces_low_confidence():
    payload = {
        "score": 1, "confidence": "high", "is_monetary_policy": True,
        "summary": "s", "stance_rationale": "r", "key_quotes": [],
    }
    r = rate.rate(_item(), None, client=_FakeClient(payload))
    assert r.text_available is False
    assert r.confidence == "low"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_rate.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'rate'`

- [ ] **Step 3: Write minimal implementation**

```python
# rate.py
"""Rate a speech dovish<->hawkish via Claude Sonnet 4.6 structured output."""
from __future__ import annotations

import json
import logging

import anthropic

import config
import creds as creds_mod
from models import Rating, SpeechItem

log = logging.getLogger(__name__)

RATING_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer",
                  "enum": [-5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "is_monetary_policy": {"type": "boolean"},
        "summary": {"type": "string"},
        "stance_rationale": {"type": "string"},
        "key_quotes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["score", "confidence", "is_monetary_policy", "summary",
                 "stance_rationale", "key_quotes"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You are a monetary-policy analyst. Rate a central bank speech on a "
    "dovish-to-hawkish scale from a markets perspective.\n"
    "Scale: -5 = very dovish (strong easing bias), 0 = neutral/balanced, "
    "+5 = very hawkish (strong tightening bias).\n"
    "If the speech is not about monetary policy (e.g. payments, supervision, "
    "ceremonial), set is_monetary_policy=false, confidence=low, and score=0.\n"
    "Set confidence=low when the stance is genuinely ambiguous. "
    "Write a neutral 2-3 sentence summary, a 1-2 sentence rationale for the "
    "score, and up to two short telling quotes (verbatim if available)."
)


def build_prompt(item: SpeechItem, text: str | None) -> str:
    body = (text or "(full text unavailable — rate from the title only)")
    body = body[: config.MAX_TEXT_CHARS]
    return (
        f"Speaker: {item.speaker or 'unknown'}\n"
        f"Central bank: {item.bank}\n"
        f"Title: {item.title}\n"
        f"Date: {item.published.isoformat()}\n\n"
        f"Speech text:\n{body}"
    )


def parse_rating(payload: dict, *, text_available: bool) -> Rating:
    return Rating(
        score=int(payload["score"]),
        confidence=payload["confidence"],
        is_monetary_policy=bool(payload["is_monetary_policy"]),
        summary=payload["summary"],
        stance_rationale=payload["stance_rationale"],
        key_quotes=list(payload.get("key_quotes", [])),
        text_available=text_available,
    )


def _client() -> anthropic.Anthropic:
    key = creds_mod.load()["ANTHROPIC_API_KEY"]
    return anthropic.Anthropic(api_key=key)


def rate(item: SpeechItem, text: str | None, *, client=None) -> Rating:
    text_available = text is not None
    client = client or _client()
    try:
        resp = client.messages.create(
            model=config.MODEL,
            max_tokens=config.MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_prompt(item, text)}],
            output_config={"format": {"type": "json_schema",
                                      "schema": RATING_SCHEMA}},
        )
        body = next(b.text for b in resp.content if b.type == "text")
        rating = parse_rating(json.loads(body), text_available=text_available)
        if not text_available:
            rating.confidence = "low"
        return rating
    except Exception as e:
        log.warning("rate failed for %s: %s: %s", item.url, type(e).__name__, e)
        return Rating(
            score=0, confidence="low", is_monetary_policy=False,
            summary="(rating unavailable — model call failed)",
            stance_rationale="", key_quotes=[],
            text_available=text_available, error=f"{type(e).__name__}: {e}",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_rate.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add rate.py tests/test_rate.py
git commit -m "feat: Sonnet 4.6 dovish/hawkish rating with structured output"
```

---

## Task 9: Email digest

**Files:**
- Create: `email_send.py`
- Test: `tests/test_email_send.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_email_send.py
from datetime import date
import email_send
from models import SpeechItem, Rating


def _pair(score, region, speaker, mp=True, conf="high"):
    item = SpeechItem(id="https://x/" + speaker, title="t", url="https://x/" + speaker,
                      published=date(2026, 6, 5), speaker=speaker,
                      bank="Bank", region=region, source="fed")
    rating = Rating(score=score, confidence=conf, is_monetary_policy=mp,
                    summary="sum", stance_rationale="why", key_quotes=["q"])
    return item, rating


def test_subject_counts_stances():
    rated = [_pair(3, "US", "A"), _pair(-2, "Europe", "B"), _pair(0, "UK", "C")]
    subj = email_send.build_subject(rated)
    assert "3 new" in subj
    assert "1 hawkish" in subj
    assert "1 dovish" in subj
    assert "1 neutral" in subj


def test_html_groups_by_region_and_shows_speaker():
    rated = [_pair(4, "US", "Hawk"), _pair(-4, "Europe", "Dove")]
    html = email_send.build_html(rated)
    assert "Hawk" in html and "Dove" in html
    assert "US" in html and "Europe" in html
    assert html.index("US") < html.index("Europe")  # region order


def test_html_sorts_by_absolute_score_within_region():
    rated = [_pair(1, "US", "Mild"), _pair(5, "US", "Strong")]
    html = email_send.build_html(rated)
    assert html.index("Strong") < html.index("Mild")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_email_send.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'email_send'`

- [ ] **Step 3: Write minimal implementation**

```python
# email_send.py
"""Build the grouped HTML digest and send it via Gmail SMTP."""
from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import date
from email.message import EmailMessage

import config
import creds as creds_mod
from models import Rating, SpeechItem

log = logging.getLogger(__name__)

Rated = tuple[SpeechItem, Rating]


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


def _badge(score: int) -> str:
    if score > 0:
        color, label = "#991b1b", f"+{score} hawkish"
    elif score < 0:
        color, label = "#1e40af", f"{score} dovish"
    else:
        color, label = "#6b7280", "0 neutral"
    return (f"<span style='background:{color}; color:#fff; padding:2px 8px; "
            f"border-radius:10px; font-size:12px; font-weight:600;'>{label}</span>")


def build_subject(rated: list[Rated]) -> str:
    hawk = sum(1 for _, r in rated if r.score > 0)
    dove = sum(1 for _, r in rated if r.score < 0)
    neutral = sum(1 for _, r in rated if r.score == 0)
    summary = (f"{len(rated)} new ({hawk} hawkish, {dove} dovish, "
               f"{neutral} neutral)")
    return config.SUBJECT_TEMPLATE.format(summary=summary,
                                          date=date.today().isoformat())


def _entry(item: SpeechItem, r: Rating) -> str:
    quotes = "".join(
        f"<li style='color:#374151;'>“{_esc(q)}”</li>" for q in r.key_quotes
    )
    quote_block = f"<ul style='margin:6px 0;'>{quotes}</ul>" if quotes else ""
    flags = []
    if not r.is_monetary_policy:
        flags.append("non-monetary")
    if not r.text_available:
        flags.append("rated from title only")
    if r.error:
        flags.append("rating error")
    flag_str = (f" <span style='color:#b45309; font-size:12px;'>"
                f"[{_esc(', '.join(flags))}]</span>") if flags else ""
    return (
        "<div style='margin:0 0 16px; padding:12px; border:1px solid #eee; "
        "border-radius:8px;'>"
        f"<div>{_badge(r.score)} "
        f"<span style='color:#6b7280; font-size:12px;'>confidence: "
        f"{_esc(r.confidence)}</span>{flag_str}</div>"
        f"<div style='font-weight:600; margin:6px 0 2px;'>"
        f"{_esc(item.speaker or 'Unknown speaker')} — {_esc(item.bank)}</div>"
        f"<div style='font-size:13px; margin-bottom:6px;'>"
        f"<a href='{_esc(item.url)}'>{_esc(item.title)}</a> "
        f"<span style='color:#9ca3af;'>({item.published.isoformat()})</span></div>"
        f"<div style='margin:4px 0;'>{_esc(r.summary)}</div>"
        f"<div style='color:#4b5563; font-size:13px;'><em>{_esc(r.stance_rationale)}</em></div>"
        f"{quote_block}"
        "</div>"
    )


def build_html(rated: list[Rated]) -> str:
    today = date.today().isoformat()
    sections: list[str] = []
    for region in config.REGION_ORDER:
        group = [(i, r) for i, r in rated if i.region == region]
        if not group:
            continue
        group.sort(key=lambda pr: abs(pr[1].score), reverse=True)
        entries = "".join(_entry(i, r) for i, r in group)
        sections.append(
            f"<h2 style='font-size:18px; margin:20px 0 8px;'>{region}</h2>{entries}"
        )
    return (
        "<!DOCTYPE html><html><body style='font-family:-apple-system,Segoe UI,"
        "Helvetica,sans-serif; color:#111827; max-width:780px; margin:0 auto; "
        "padding:16px;'>"
        "<h1 style='font-size:20px; margin:0 0 4px;'>Central bank speeches — "
        "daily digest</h1>"
        f"<div style='color:#6b7280; font-size:12px;'>{today}</div>"
        f"{''.join(sections)}"
        "<hr style='margin:24px 0 8px; border:none; border-top:1px solid #e5e5e5;'>"
        "<div style='color:#9ca3af; font-size:11px;'>Sources: bank RSS feeds + "
        "BIS central bankers' speeches. Scores rated by Claude Sonnet 4.6 "
        "(-5 dovish … +5 hawkish).</div>"
        "</body></html>"
    )


def send(html: str, subject: str) -> None:
    secrets = creds_mod.load()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config.SENDER_EMAIL
    msg["To"] = ", ".join(config.RECIPIENT_EMAILS)
    msg.set_content("This email requires an HTML-capable client.")
    msg.add_alternative(html, subtype="html")

    last_err = None
    for attempt in range(3):
        try:
            with smtplib.SMTP(config.GMAIL_SMTP_HOST, config.GMAIL_SMTP_PORT,
                              timeout=30) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(config.SENDER_EMAIL, secrets["GMAIL_APP_PASSWORD"])
                smtp.send_message(msg)
                log.info("email sent: %s", subject)
                return
        except Exception as e:
            last_err = e
            log.warning("SMTP attempt %d failed: %s", attempt + 1, e)
    raise RuntimeError(f"SMTP send failed after retries: {last_err}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_email_send.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add email_send.py tests/test_email_send.py
git commit -m "feat: grouped HTML digest email via Gmail SMTP"
```

---

## Task 10: Orchestrator

**Files:**
- Create: `main.py`
- Test: `tests/test_main.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_main.py
from datetime import date, timedelta
import main
from models import SpeechItem


def _item(id_, days_ago):
    d = date.today() - timedelta(days=days_ago)
    return SpeechItem(id=id_, title="t", url=id_, published=d, speaker=None,
                      bank="b", region="US", source="fed")


def test_select_new_filters_seen_and_old():
    items = [_item("a", 0), _item("b", 0), _item("c", 10)]
    seen = {"b": "2026-06-01"}
    new = main.select_new(items, seen, lookback_hours=48)
    ids = {i.id for i in new}
    assert ids == {"a"}  # b seen, c too old


def test_update_seen_adds_ids():
    seen = {"x": "2026-06-01"}
    main.update_seen(seen, [_item("y", 0)], today="2026-06-06")
    assert seen["y"] == "2026-06-06"
    assert seen["x"] == "2026-06-01"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'main'`

- [ ] **Step 3: Write minimal implementation**

```python
# main.py
"""Orchestrator: fetch feeds, dedup, extract, rate, email, persist state.

Exit codes:
  0  = success (email sent if there were new speeches; silent if none)
  2  = all feeds failed (no items at all)
  3  = email send failed (state NOT updated; speeches retry next run)
  99 = unhandled exception
"""
from __future__ import annotations

import json
import logging
import sys
import traceback
from datetime import date, datetime, timedelta, timezone

import config
import email_send
import extract
import fetcher
import rate as rate_mod
from models import SpeechItem

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("main")


def _today_str() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def load_seen() -> dict[str, str]:
    if not config.SEEN_FILE.exists():
        return {}
    try:
        return json.loads(config.SEEN_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        log.warning("corrupt seen.json — treating as empty: %s", e)
        return {}


def select_new(items: list[SpeechItem], seen: dict[str, str],
               *, lookback_hours: int) -> list[SpeechItem]:
    cutoff = date.today() - timedelta(hours=lookback_hours)
    return [i for i in items if i.id not in seen and i.published >= cutoff]


def update_seen(seen: dict[str, str], items: list[SpeechItem],
                *, today: str) -> None:
    for i in items:
        seen[i.id] = today


def _append_log(line: str) -> None:
    with config.RUNS_LOG.open("a", encoding="utf-8") as fp:
        fp.write(line + "\n")


def run() -> int:
    started = datetime.now(timezone.utc)
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    archive_dir = config.ARCHIVE_DIR / _today_str()
    archive_dir.mkdir(parents=True, exist_ok=True)

    items = fetcher.fetch_all()
    if not items:
        log.error("no items from any feed")
        _append_log(f"{started.isoformat()} | fail | no_feed_data")
        return 2

    seen = load_seen()
    new = select_new(items, seen, lookback_hours=config.LOOKBACK_HOURS)
    if not new:
        log.info("no new speeches")
        _append_log(f"{started.isoformat()} | ok | no_new_speeches "
                    f"({len(items)} seen)")
        return 0

    rated = []
    for item in new:
        text = extract.extract_text(item.url)
        rating = rate_mod.rate(item, text)
        rated.append((item, rating))
        (archive_dir / f"{item.source}-{abs(hash(item.id))}.json").write_text(
            json.dumps({"item": item.__dict__ | {"published": item.published.isoformat()},
                        "rating": rating.__dict__}, indent=2, default=str),
            encoding="utf-8",
        )
        log.info("rated %s: score=%s conf=%s", item.url, rating.score,
                 rating.confidence)

    html = email_send.build_html(rated)
    subject = email_send.build_subject(rated)
    (archive_dir / "view.html").write_text(html, encoding="utf-8")

    try:
        email_send.send(html, subject)
    except Exception as e:
        log.error("email send failed: %s", e)
        _append_log(f"{started.isoformat()} | fail | send_failed: {e}")
        return 3  # state NOT updated — speeches retry next run

    update_seen(seen, new, today=_today_str())
    config.SEEN_FILE.write_text(json.dumps(seen, indent=2), encoding="utf-8")
    _append_log(f"{started.isoformat()} | ok | sent {len(new)} new speeches")
    return 0


def main() -> int:
    try:
        return run()
    except Exception:
        log.error("unhandled exception:\n%s", traceback.format_exc())
        return 99


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_main.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Run the full test suite**

Run: `python -m pytest -q`
Expected: all tests pass (no failures).

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "feat: orchestrator wiring fetch->rate->email->persist"
```

---

## Task 11: GitHub Actions workflow + README

**Files:**
- Create: `.github/workflows/cb_speeches.yml`
- Create: `README.md`

- [ ] **Step 1: Create the workflow**

```yaml
# .github/workflows/cb_speeches.yml
name: Daily CB speeches digest

on:
  schedule:
    - cron: "0 6 * * *"   # 06:00 UTC = 07:00 London (BST)
  workflow_dispatch:

permissions:
  contents: write

concurrency:
  group: cb-speeches
  cancel-in-progress: false

jobs:
  run:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - run: pip install -r requirements.txt

      - name: Run digest
        env:
          GMAIL_APP_PASSWORD: ${{ secrets.GMAIL_APP_PASSWORD }}
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
        run: python main.py

      - name: Commit updated state
        if: always()
        run: |
          git config user.name  "github-actions[bot]"
          git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
          git add state/ archive/ runs.log
          if git diff --staged --quiet; then
            echo "No state changes to commit."
          else
            git commit -m "state: $(date -u +%Y-%m-%dT%H:%MZ) speeches digest"
            git push
          fi
```

- [ ] **Step 2: Create the README**

```markdown
# CB speech daily digest

Daily email digest of new central bank speeches (US, Europe, UK, Australia,
Canada), each rated dovish↔hawkish with a confidence level by Claude Sonnet 4.6.

Runs free on GitHub Actions on a cron schedule. State (`state/seen.json`) is
committed back to the repo, which also gives a free history of every speech and
rating under `archive/<date>/`.

## How it works

1. Fetch six feeds: direct RSS for the Fed, ECB, BoE, RBA, BoC, plus the BIS
   central bankers' speeches aggregator (catches regional Fed presidents and
   eurozone national governors).
2. Dedup against `state/seen.json` and a 48h lookback window.
3. Extract each new speech's full text (HTML or PDF).
4. Rate each via Claude Sonnet 4.6 (structured output): score -5..+5,
   confidence, summary, rationale, key quotes.
5. Email one digest grouped by region — only when there are new speeches.

## Setup (GitHub Actions)

1. Create a repo and push this directory.
2. Settings → Secrets and variables → Actions → add two secrets:
   - `GMAIL_APP_PASSWORD` — the Gmail App Password (same as the ETF/daily_2y agents)
   - `ANTHROPIC_API_KEY` — Claude API key
3. Actions → **Daily CB speeches digest** → **Run workflow** for the first run.
   Subsequent runs fire daily at 06:00 UTC (07:00 London). Edit the `cron` line
   in `.github/workflows/cb_speeches.yml` to change the time.

## Local run

1. `python -m pip install -r requirements.txt`
2. Create `secrets.txt` in this folder:
   ```
   GMAIL_APP_PASSWORD=...
   ANTHROPIC_API_KEY=...
   ```
3. `python main.py`

## Files

| File | Purpose |
|---|---|
| `config.py` | Feeds, email config, model, lookback window |
| `creds.py` | Loads secrets (env first, then `secrets.txt`) |
| `sources/rss.py` | Generic RSS/Atom parser |
| `sources/bis.py` | BIS feed parser + speaker→region mapping |
| `fetcher.py` | Fetch all feeds, dispatch, dedup |
| `extract.py` | Speech page → clean text (HTML + PDF) |
| `rate.py` | Sonnet 4.6 dovish/hawkish rating |
| `email_send.py` | Build + send the HTML digest |
| `main.py` | Orchestrator |
| `state/seen.json` | Processed speech ids (committed by CI) |
| `archive/<date>/` | Raw text + ratings + sent email per run |
| `runs.log` | One-line summary per run |

## Rating scale

`-5` very dovish … `0` neutral … `+5` very hawkish. Non-monetary or ambiguous
speeches are flagged `confidence: low` and shown but not given a misleading score.

## Common failures

| Symptom | Likely cause | Fix |
|---|---|---|
| `Missing secrets...` | Secrets not set | Add repo secrets (cloud) or `secrets.txt` (local) |
| A feed missing from `runs.log` | Bank changed its RSS URL | Update the URL in `config.py:FEEDS` |
| Email never arrives | Hotmail spam folder | Whitelist `martin.coucke68@gmail.com` |
| Same speech reappears | `seen.json` not committed | Check the workflow's "Commit updated state" step |
```

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/cb_speeches.yml README.md
git commit -m "feat: GitHub Actions workflow and README"
```

---

## Task 12: End-to-end smoke test (manual)

**Files:** none (verification only)

- [ ] **Step 1: Create a local `secrets.txt`**

Create `C:\CB speech\secrets.txt` (already git-ignored) with:
```
GMAIL_APP_PASSWORD=<the app password>
ANTHROPIC_API_KEY=<the api key>
```

- [ ] **Step 2: Run the agent end-to-end**

Run:
```bash
cd "C:\CB speech" && python main.py
```
Expected one of:
- New speeches today → a digest email arrives at both recipients; `state/seen.json`
  is created/updated; `archive/<today>/view.html` exists; `runs.log` shows
  `ok | sent N new speeches`.
- No new speeches today → no email; `runs.log` shows `ok | no_new_speeches`.

- [ ] **Step 3: Verify idempotency**

Run `python main.py` again immediately.
Expected: `runs.log` shows `ok | no_new_speeches` (everything already in `seen.json`),
no duplicate email.

- [ ] **Step 4: Inspect a rating**

Open `archive/<today>/view.html` in a browser (if a digest was produced) and
confirm: speeches grouped by region, score badges colored correctly, summaries
and rationales present, links work. Spot-check that an obviously hawkish or
dovish speech got a sensible score.

- [ ] **Step 5: Commit any state produced by the smoke run**

```bash
git add state/ archive/ runs.log
git commit -m "chore: initial state from smoke run"
```

---

## Self-review notes

- **Spec coverage:** hybrid sourcing (Tasks 4–6), dedup/state seen.json (Tasks 6, 10), extraction HTML+PDF (Task 7), numeric+confidence rating with `is_monetary_policy` flag (Task 8), region-grouped email sorted by |score|, silent on no-news (Tasks 9–10), 06:00 UTC cron + commit-state (Task 11), two secrets via env→file (Task 3), exit-code discipline (Task 10). All spec sections map to a task.
- **State-after-send invariant:** `main.run()` writes `seen.json` only after `email_send.send` succeeds; on send failure it returns `3` without updating state — matches the spec.
- **Type consistency:** `SpeechItem`/`Rating` fields are used identically across `rate.py`, `email_send.py`, and `main.py`; `parse_feed` signatures match their call sites in `fetcher.py`; `rate(item, text, client=...)` matches its test and orchestrator call.
- **Live-data caveat:** feed URLs in `config.py` are verified in Task 6 Step 5 and the Sonnet call is exercised in Task 12 — both require network/secrets and are explicit manual steps.
