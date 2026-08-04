"""CB speech agent configuration. All constants live here."""
from __future__ import annotations

from pathlib import Path

# --- Paths --------------------------------------------------------------
HERE = Path(__file__).parent
STATE_DIR = HERE / "state"
ARCHIVE_DIR = HERE / "archive"
SEEN_FILE = STATE_DIR / "seen.json"
HEALTH_FILE = STATE_DIR / "source_health.json"
# Consecutive zero-item runs before a source is reported as probably broken.
SOURCE_HEALTH_ALERT_RUNS = 3
# Fraction of a scraped source's items that may lack a speaker before it is
# reported. A drifted byline selector affects nearly every row, whereas a few
# pre-2015 archive entries legitimately predate the "Surname: Title" convention
# — alerting on those would fire every run and train the reader to ignore it.
SPEAKER_MISSING_ALERT_RATIO = 0.2
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
    # ECB has no usable speeches RSS feed and its index is JS-rendered, so we
    # scrape it with headless Chromium (kind="playwright") for same-day items.
    {"name": "ecb", "kind": "playwright", "region": "Europe", "bank": "ECB",
     "url": "https://www.ecb.europa.eu/press/key/html/index.en.html"},
    {"name": "boe", "kind": "rss", "region": "UK", "bank": "Bank of England",
     "url": "https://www.bankofengland.co.uk/rss/speeches"},
    {"name": "rba", "kind": "rss", "region": "Australia", "bank": "Reserve Bank of Australia",
     "url": "https://www.rba.gov.au/rss/rss-cb-speeches.xml"},
    {"name": "boc", "kind": "rss", "region": "Canada", "bank": "Bank of Canada",
     "url": "https://www.bankofcanada.ca/content_type/speeches/feed/"},
    {"name": "bis", "kind": "bis", "region": "", "bank": "",
     "url": "https://www.bis.org/doclist/cbspeeches.rss"},
]

# Regional Fed presidents are not on the Board's RSS feed and reach BIS only
# after ~20 days, so they are scraped directly. Selectors verified against the
# live pages on 2026-08-04; if a source reports zero items the markup has
# changed and the selectors below are the only thing that needs updating.
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

# Eurozone national central banks. Their governors sit on the ECB Governing
# Council but are absent from the ECB's own site, and BIS carries them ~20 days
# late, so they need direct sources.
FEEDS += [
    {
        # The "Reden" feed carries each speech twice (German + English) and
        # also interviews; keep only the English speech URLs.
        "name": "bundesbank", "kind": "rss", "region": "Europe",
        "bank": "Bundesbank",
        "url": "https://www.bundesbank.de/service/rss/en/633296/feed.rss",
        "url_include": ["/en/press/speeches/"],
    },
    {
        # A general news feed; speech articles are prefixed "speech-".
        "name": "cbireland", "kind": "rss", "region": "Europe",
        "bank": "Central Bank of Ireland",
        "url": "https://www.centralbank.ie/feeds/news-media-feed",
        "url_include": ["/news/article/speech-"],
    },
]

# --- Dedup / freshness --------------------------------------------------
LOOKBACK_HOURS = 48  # only treat items published within this window as "new"

# BIS publishes speeches 14-31 days after delivery (measured 2026-08-04), so a
# BIS item is only accepted if it was *delivered* within this window. Wider than
# LOOKBACK_HOURS so a genuinely prompt BIS post is still caught, narrow enough to
# exclude the observed backfill.
BIS_MAX_AGE_DAYS = 7

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
