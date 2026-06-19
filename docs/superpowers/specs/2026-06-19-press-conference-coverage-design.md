# Post-meeting press conference / policy-decision coverage — design

**Date:** 2026-06-19
**Status:** Approved (pending spec review)
**Extends:** the CB speech daily digest agent (2026-06-06 design).

## Purpose

Add each central bank's **post-meeting monetary policy decision and press-
conference opening statement** to the daily digest, alongside speeches. This
closes the gap that prompted the request: the agent covered speeches but not the
FOMC (and equivalent) post-meeting communication, which is the most market-
relevant output a central bank produces. Each captured decision is rated on the
same dovish↔hawkish scale and shown in the same email, flagged distinctly.

Scope of "press conference" (locked decision): the **monetary policy decision /
statement plus the opening statement** — the same-day, reliably-published core —
not the full Q&A transcript (which lags 1-3 days for BoE/RBA/BoC).

## Approach

Reuse the existing pipeline. Each bank already publishes its decision in an RSS
feed, so no bespoke scrapers are needed (unlike the ECB speeches case). Add one
"policy feed" per bank plus a per-feed **title classifier** that keeps only the
decision/press-conference items and drops the noise the same feeds also carry
(minutes, data releases, appointments, regulatory notices). Classified items
flow through the existing dedup → extract → rate → email path.

## Sources

One policy feed per bank, each with an `include` list of lowercased title
substrings. An item is kept iff its title contains any substring in the list.

| Bank | Region | Feed URL | `include` substrings |
|---|---|---|---|
| Fed | US | `https://www.federalreserve.gov/feeds/press_monetary.xml` | `fomc statement` |
| ECB | Europe | `https://www.ecb.europa.eu/rss/press.html` | `monetary policy statement`, `monetary policy decisions`, `press conference`, `combined monetary policy` |
| BoE | UK | `https://www.bankofengland.co.uk/rss/news` | `monetary policy summary`, `bank rate` |
| RBA | Australia | `https://www.rba.gov.au/rss/rss-cb-media-releases.xml` | `monetary policy decision`, `statement by the monetary policy board` |
| BoC | Canada | `https://www.bankofcanada.ca/content_type/press-releases/feed/` | `policy rate`, `opening statement` |

Verified live (2026-06-19): the Fed feed carries "Federal Reserve issues FOMC
statement"; BoE carries "Bank Rate maintained at 3.75% — … Monetary Policy
Summary and Minutes"; BoC carries "Bank of Canada maintains the policy rate at
2¾%". ECB decision items appear on Governing-Council days. RBA's media-releases
feed is low-volume (the decision is the newest item on decision day).

## Components / changes

- **`models.py`** — add `category: str = "speech"` to `SpeechItem`. Policy-feed
  items get `category="press_conference"`. Default preserves all existing
  behaviour and tests.

- **`config.py`** — add `POLICY_FEEDS` (a list mirroring `FEEDS` entry shape,
  each with extra `include: list[str]` and `category: "press_conference"`). The
  fetcher iterates `FEEDS + POLICY_FEEDS`. Keeping them in a separate list keeps
  the speech vs decision config visually distinct and avoids touching existing
  `FEEDS` entries.

- **`sources/rss.py`** — `parse_feed` gains two optional params:
  `category="speech"` (stamped onto each item) and `include=None` (when given, a
  case-insensitive title-substring filter; items not matching are dropped). The
  generic parser stays generic; BIS/ECB-playwright paths are untouched.

- **`fetcher.py`** — iterate `config.FEEDS + config.POLICY_FEEDS`. For an rss
  feed, pass `category=feed.get("category", "speech")` and
  `include=feed.get("include")` through to `rss.parse_feed`. Dedup and dispatch
  are otherwise unchanged. (BIS and playwright feeds never carry `include`.)

- **`rate.py`** — lightly generalize the prompt wording from "speech" to "speech
  or monetary policy statement" so a terse FOMC statement is rated naturally. The
  schema and scoring scale are unchanged.

- **`email_send.py`** — within each region, sort `press_conference` items to the
  top (before speeches), then by `abs(score)`. Render a distinct pill
  (e.g. "🏛 Policy decision") on press-conference entries so they're visually
  separated from speeches. Speech rendering is unchanged.

## Data flow

Unchanged from the base agent. `fetcher.fetch_all()` now also yields
`press_conference` items; they share the content-key dedup, the 48h lookback,
the `seen` set, extraction, rating, archiving, and the single daily email. A
decision published same-day is caught by the next 06:00 UTC run.

## Dedup / state

No change. Press-conference items have distinct content keys from speeches
(different titles), so they never collide with a speech. The content-key `seen`
set still prevents a decision from being emailed twice (including if it also
surfaces via BIS or a bank's speeches feed under a different URL).

## Error handling

Inherits the base agent's behaviour: a policy feed that fails or changes layout
is logged and skipped (other feeds still produce a digest); extraction failure
falls back to title-only rating with forced low confidence; rating failure shows
the item unrated with a note and does not mark it seen.

## Testing

- `models`: `SpeechItem` default `category == "speech"`.
- `rss.parse_feed`: `include` filter keeps only matching titles; `category` is
  stamped onto returned items; omitting `include` keeps all items (existing
  behaviour) and defaults category to `"speech"`.
- `fetcher`: items from `POLICY_FEEDS` are fetched, classified, and concatenated;
  a non-matching title is dropped; existing speech-feed behaviour is unchanged.
- `email_send`: a `press_conference` item renders the pill and sorts above a
  speech in the same region regardless of score.
- `config`: every region has a policy feed; each policy feed has a non-empty
  `include` list and `category == "press_conference"`.
- Live check (manual, like the base agent's feed check): `fetch_all()` returns
  press-conference items for the banks that have a recent decision, and no
  obvious noise (no minutes/appointments).

## Out of scope (YAGNI)

- Full press-conference Q&A transcripts (lag for BoE/RBA/BoC; bespoke per bank).
- Meeting-calendar awareness — we rely on the feeds publishing the decision, not
  on knowing meeting dates in advance.
- FOMC minutes, Summary of Economic Projections, and other secondary releases.
- Non-target central banks.

## Open risks

- **RBA feed sparsity:** the media-releases feed is low-volume; if a later
  release pushes the decision out of the feed before our run, we miss it.
  Mitigation: daily run + 48h lookback catches it the morning after; flagged as
  the one fragile source in the live feed check.
- **Title-classifier drift:** if a bank rewords its decision headline, the
  `include` filter could miss it. Mitigation: substrings are broad (e.g. "bank
  rate", "policy rate"); `runs.log` per-feed counts make a sudden drop to zero
  diagnosable, and BIS/speeches feeds provide partial backup.
