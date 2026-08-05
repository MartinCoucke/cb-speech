# CB speech daily digest

Daily email digest of new central bank speeches (US, Europe, UK, Australia,
Canada), each rated dovish↔hawkish with a confidence level by Claude Sonnet 4.6.

Runs free on GitHub Actions on a cron schedule. State (`state/seen.json`) is
committed back to the repo, which also gives a free history of every speech and
rating under `archive/<date>/`.

## How it works

1. **Fetch speeches** from direct, same-day sources: RSS for the Fed Board, BoE,
   RBA, BoC, Bundesbank and Central Bank of Ireland; a headless-Chromium scrape
   of the ECB key-speeches page; and plain-HTTP scrapes of the New York and
   Boston Fed listings (regional presidents are absent from the Board feed).
2. **Fetch policy decisions** — the post-meeting statement / press-conference
   opening statement for all five banks, filtered out of their press feeds.
3. **BIS as a backstop.** The BIS aggregator publishes 14–31 days after
   delivery (measured), so its items are dated by their *true* delivery date,
   parsed from the description. Banks with a direct source are held to
   `BIS_MAX_AGE_DAYS` (7) — anything genuinely new arrives via their own feed.
   Banks that cannot be scraped at all (Banque de France, DNB, Banco de España,
   and the regional Feds without a listing) have no other channel, so BIS is
   allowed up to `BIS_FALLBACK_MAX_AGE_DAYS` (45) for them and the digest labels
   those entries "⏳ delivered &lt;date&gt;". The covered set is derived from the
   feed list, so adding a direct source automatically tightens its gate.
4. **Dedup on two identity keys**, matching if either hits: `speaker surname +
   title`, and `title + delivery date + region`. The second works even if a
   source stops emitting speakers, so a drifted selector cannot cause duplicates.
   Combined with a 48h lookback and `state/seen.json`.
5. **Extract** each new item's full text (HTML or PDF).
6. **Rate** via Claude Sonnet 4.6 (structured output): score -5..+5, confidence,
   summary, rationale, key quotes.
7. **Email** one digest grouped by region — policy decisions first, then speeches
   by conviction — only when there is something new. Sources that go quiet for
   3 consecutive runs are flagged in the digest, so a broken scraper can't
   masquerade as a slow news day.

## Setup (GitHub Actions)

1. Create a repo and push this directory.
2. Settings → Secrets and variables → Actions → add two secrets:
   - `GMAIL_APP_PASSWORD` — the Gmail App Password (same as the ETF/daily_2y agents)
   - `ANTHROPIC_API_KEY` — Claude API key
3. Actions → **Daily CB speeches digest** → **Run workflow** for the first run.
   Subsequent runs fire daily at 06:00 UTC (07:00 London). Edit the `cron` line
   in `.github/workflows/cb_speeches.yml` to change the time.

The workflow installs Playwright's Chromium (cached across runs) for the ECB
scraper.

## Local run

1. `python -m pip install -r requirements.txt`
2. `python -m playwright install chromium`
3. Create `secrets.txt` in this folder:
   ```
   GMAIL_APP_PASSWORD=...
   ANTHROPIC_API_KEY=...
   ```
4. `python main.py`

## Files

| File | Purpose |
|---|---|
| `config.py` | `FEEDS` (speeches), `POLICY_FEEDS` (decisions), email, model, windows |
| `creds.py` | Loads secrets (env first, then `secrets.txt`) |
| `sources/rss.py` | Generic RSS/Atom parser, with title/URL filters |
| `sources/bis.py` | BIS parser: true delivery date + speaker→region mapping |
| `sources/html_list.py` | Config-driven HTML listing scraper (NY, Boston, RBA) |
| `sources/ecb_playwright.py` | Headless-Chromium scrape of the ECB speeches page |
| `fetcher.py` | Fetch all sources, dispatch, freshness gate, two-key dedup |
| `state/source_health.json` | Consecutive zero-item runs per source |
| `extract.py` | Speech page → clean text (HTML + PDF) |
| `rate.py` | Sonnet 4.6 dovish/hawkish rating |
| `email_send.py` | Build + send the HTML digest |
| `main.py` | Orchestrator |
| `state/seen.json` | Processed speech content keys (committed by CI) |
| `archive/<date>/` | Raw text + ratings + sent email per run |
| `runs.log` | One-line summary per run |

## Rating scale

`-5` very dovish … `0` neutral … `+5` very hawkish. Non-monetary or ambiguous
speeches are flagged `confidence: low` and shown but not given a misleading score.

## Common failures

| Symptom | Likely cause | Fix |
|---|---|---|
| `Missing secrets...` | Secrets not set | Add repo secrets (cloud) or `secrets.txt` (local) |
| A feed missing from `runs.log` | Bank changed its RSS URL / ECB DOM changed | Update the URL in `config.py:FEEDS`; for ECB check `sources/ecb_playwright.py` selectors |
| Email never arrives | Hotmail spam folder | Whitelist `martin.coucke68@gmail.com` |
| Same speech reappears | `seen.json` not committed | Check the workflow's "Commit updated state" step |
| ECB feed shows 0 items | Page slow to render / DOM changed | The scraper waits for the list selector; if the ECB redesigns, update the selectors |
