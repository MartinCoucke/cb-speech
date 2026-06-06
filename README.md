# CB speech daily digest

Daily email digest of new central bank speeches (US, Europe, UK, Australia,
Canada), each rated dovish↔hawkish with a confidence level by Claude Sonnet 4.6.

Runs free on GitHub Actions on a cron schedule. State (`state/seen.json`) is
committed back to the repo, which also gives a free history of every speech and
rating under `archive/<date>/`.

## How it works

1. Fetch six sources: direct RSS for the Fed, BoE, RBA, BoC; a headless-Chromium
   scrape of the ECB key-speeches page (the ECB has no usable RSS feed); and the
   BIS central bankers' speeches aggregator (catches regional Fed presidents and
   eurozone national governors).
2. Dedup by a **content key** (speaker surname + normalized title), not URL — the
   same speech appears on a bank's site and on BIS under different URLs, so a URL
   key would email it twice. Direct sources win over BIS on collision. Combined
   with a 48h lookback window and `state/seen.json`.
3. Extract each new speech's full text (HTML or PDF).
4. Rate each via Claude Sonnet 4.6 (structured output): score -5..+5,
   confidence, summary, rationale, key quotes.
5. Email one digest grouped by region, sorted by |score| — only when there are
   new speeches.

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
| `config.py` | Feeds, email config, model, lookback window |
| `creds.py` | Loads secrets (env first, then `secrets.txt`) |
| `sources/rss.py` | Generic RSS/Atom parser |
| `sources/bis.py` | BIS feed parser + speaker→region mapping |
| `sources/ecb_playwright.py` | Headless-Chromium scrape of the ECB speeches page |
| `fetcher.py` | Fetch all sources, dispatch, content-key dedup |
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
