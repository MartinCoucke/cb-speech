# CB Speech daily digest agent — design

**Date:** 2026-06-06
**Status:** Approved (pending spec review)

## Purpose

A scheduled agent that emails a daily digest of new central bank speeches from
the US, Europe, UK, Australia, and Canada. Each speech is rated on a
dovish↔hawkish scale with a confidence level, summarized, and linked. Hosted on
GitHub Actions, mirroring the setup used in the `Active ETF` project (per-source
fetchers → `state/` snapshots committed back to the repo → Gmail SMTP HTML email
→ cron workflow). The one addition over that project is a per-speech Claude API
call for scoring and summarization.

## Decisions (locked)

- **Rating format:** numeric `-5` (very dovish) … `+5` (very hawkish), plus a
  confidence level (`high`/`medium`/`low`). Low confidence is set automatically
  for non-monetary or ambiguous speeches.
- **Speaker scope:** core policy boards **plus** regional/voting members — the 12
  regional Fed presidents and eurozone national central bank governors
  (Bundesbank, Banque de France, etc.), not only the ECB Executive Board.
- **No-news behavior:** stay silent — only email when there are new speeches
  (same as the ETF agent skipping email on no-change days).
- **Sourcing:** hybrid (Approach A) — direct RSS for the five majors plus the
  BIS aggregator as a catch-all for the long tail.
- **Model:** Claude Sonnet 4.6 (`claude-sonnet-4-6`). Classification +
  summarization task; ~$0.026/speech, a few dollars/month at expected volume.

## Architecture

```
CB speech/
  config.py        # feeds, email config, model, lookback window, thresholds
  creds.py         # env-first -> secrets.txt (GMAIL_APP_PASSWORD + ANTHROPIC_API_KEY)
  fetcher.py       # pull each feed, parse entries, normalize to a common shape
  sources/
    rss.py         # generic RSS parser (Fed, ECB, BoE, RBA, BoC)
    bis.py         # BIS "central bankers' speeches" parser + speaker->bank/region mapping
  extract.py       # fetch full speech text from the item link (HTML + PDF -> clean text)
  rate.py          # Claude Sonnet 4.6 call -> structured rating JSON
  email_send.py    # build grouped HTML digest, send via Gmail SMTP
  main.py          # orchestrator
  state/
    seen.json      # {speech_id: first_seen_date} - processed speeches, committed back
  archive/<date>/  # raw text + ratings + sent email HTML per run
  runs.log         # one-line summary per run
  .github/workflows/cb_speeches.yml
  requirements.txt
  README.md
```

### Components

Each module has one responsibility and a small interface:

- **`config.py`** — all constants: the feed list (each entry: `name`, `url`,
  `kind` = `rss`|`bis`, `region`, default `bank`), email sender/recipients,
  subject template, model id, lookback window (48h), HTTP timeout/user-agent,
  and paths. No other module hardcodes constants.

- **`creds.py`** — `load()` returns `{GMAIL_APP_PASSWORD, ANTHROPIC_API_KEY}`,
  preferring environment variables (GitHub Actions) then `secrets.txt` (local).
  Mirrors the ETF/daily_2y contract. Raises clearly if a key is missing.

- **`sources/rss.py`** — `parse(feed_url) -> list[SpeechItem]`. Generic RSS/Atom
  parsing. Returns items with `id` (normalized URL), `title`, `url`, `published`
  (date), `speaker` (if present in the feed), and the feed's default
  `bank`/`region`.

- **`sources/bis.py`** — `parse(feed_url) -> list[SpeechItem]`. Parses the BIS
  central bankers' speeches feed and maps each item to a `bank`/`region` from the
  speaker/institution text. Items whose institution is outside the five target
  jurisdictions are dropped.

- **`fetcher.py`** — `fetch_all() -> list[SpeechItem]`. Dispatches each
  configured feed to the right parser, concatenates results, and deduplicates by
  `id` (a speech appearing in both a direct feed and BIS collapses to one,
  preferring the direct-feed copy for freshness/metadata). Logs each feed's
  status so `runs.log` shows what each source delivered. A single feed failing
  does not abort the run — it's logged and skipped.

- **`extract.py`** — `extract_text(item) -> str | None`. Fetches the speech page
  and returns clean text. HTML via BeautifulSoup (strip nav/boilerplate); PDF via
  `pypdf`. Returns `None` on failure (caller still emails the item with a
  "full text unavailable" note rather than dropping it).

- **`rate.py`** — `rate(item, text) -> Rating`. One Claude Sonnet 4.6 call using
  structured outputs (`output_config.format` with the JSON schema below) so the
  result is guaranteed parseable. If `text` is `None`, rates from title alone and
  forces `confidence = "low"`.

- **`email_send.py`** — `build_html(rated)`, `build_subject(rated)`, `send(...)`.
  Gmail SMTP + STARTTLS with the App Password, 3 retries (same as ETF). Digest
  grouped by region, sorted within group by `abs(score)` descending.

- **`main.py`** — orchestrator (see Data flow). Same exit-code discipline as the
  ETF `main.py`: `0` ok, `2` all feeds failed, `3` email send failed, `99`
  unhandled.

### Rating schema (structured output)

```json
{
  "score": -3,
  "confidence": "high",
  "is_monetary_policy": true,
  "summary": "2-3 sentence neutral summary of the speech.",
  "stance_rationale": "1-2 sentences on what drove the dovish/hawkish score.",
  "key_quotes": ["up to two short telling lines from the speech"]
}
```

Scoring guidance given in the prompt: `-5` very dovish (strong easing bias) …
`0` neutral/balanced … `+5` very hawkish (strong tightening bias). The model sets
`is_monetary_policy = false` and `confidence = "low"` for speeches that aren't
about monetary policy (payments, supervision, ceremonial), so they're visibly
flagged in the digest rather than given a misleading score.

## Data flow (`main.py`)

1. Ensure `state/` and `archive/<today>/` exist.
2. `items = fetcher.fetch_all()`.
3. Load `state/seen.json`. `new = [i for i in items if i.id not in seen and
   i.published >= today - lookback]`.
4. If `new` is empty: append a `no_new_speeches` line to `runs.log` and exit `0`
   (no email).
5. For each new item: `text = extract.extract_text(i)`;
   `rating = rate.rate(i, text)`. Archive the raw text + rating JSON.
6. `html = email_send.build_html(rated)`; write to `archive/<today>/view.html`.
7. `email_send.send(html, subject)`.
8. Add each new item's `id` to `seen` with today's date; write `seen.json`.
9. Append a summary line to `runs.log`.

State is only updated after a successful run path, so a failed extract/rate/send
doesn't permanently mark a speech as seen and silently lose it. (Specifically:
`seen.json` is written after the email is sent; if send fails we exit `3` without
updating `seen`, so the next run retries the same speeches.)

## Error handling

- **One feed down:** logged, skipped; other feeds still produce a digest.
- **All feeds down:** no email, `runs.log` records the failure, exit `2`.
- **Extraction failure for a speech:** speech still appears in the digest with a
  "full text unavailable — rated from title" note and forced low confidence.
- **Claude API error for a speech:** retried via SDK defaults; on persistent
  failure the speech appears in the digest unrated with an error note, and is
  **not** added to `seen` so it retries next run.
- **Email send failure:** exit `3`, `seen.json` not updated (speeches retry).
- **Corrupt `seen.json`:** treated as empty (first-run behavior), logged.

## Scheduling

GitHub Actions cron at `0 6 * * *` (06:00 UTC = 07:00 London BST), catching the
prior US afternoon and overnight APAC sessions. Also `workflow_dispatch` for
manual runs. The 48-hour lookback + `seen` set makes the agent robust to cron
delay and missed runs. The workflow commits updated `state/`, `archive/`, and
`runs.log` back to `main` (same as the ETF workflow), with `permissions:
contents: write`.

## Secrets

Two repo secrets (Settings → Secrets and variables → Actions):

- `GMAIL_APP_PASSWORD` — same App Password as `daily_2y`/`Active ETF`.
- `ANTHROPIC_API_KEY` — for the Sonnet 4.6 rating calls.

For local runs, a `secrets.txt` in the project root with both keys
(`KEY=value` per line) is the fallback.

## Cost

~$0.026 per speech with Sonnet 4.6 (typical ~6K input / ~500 output tokens);
~$0.05 for a long speech. At ~100–150 speeches/month, ~$3–8/month. GitHub Actions
compute is free at this volume.

## Out of scope (YAGNI)

- Non-target central banks (Japan, Switzerland, etc.).
- Policy statements, minutes, interviews, press conferences — speeches only.
- Historical backfill / trend charts of scores over time (the committed
  `archive/` gives a raw record if this is wanted later).
- A web dashboard — email only.
- Translation of non-English national-governor speeches (the model handles
  common languages directly; explicit translation is not a separate step).

## Open risks

- **Feed format drift:** any central bank changing its RSS layout breaks one
  source; the per-feed isolation + `runs.log` status lines make this diagnosable,
  and BIS provides partial backup for the majors.
- **BIS speaker→region mapping:** the long-tail mapping in `sources/bis.py` is
  best-effort; unmapped institutions are dropped rather than misfiled.
- **Same-day completeness:** direct feeds are same-day; regional/national
  speeches via BIS lag 1–3 days. Acceptable per the agreed scope.
