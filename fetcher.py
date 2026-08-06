"""Fetch every configured feed, dispatch to the right parser, dedup by content.

Dedup is by a content key (speaker surname + normalized title), NOT by URL: the
same speech appears on a bank's own site and on BIS under different URLs, so a
URL key would let the same speech through twice (often 1-3 days apart). The
content key collapses those, preferring the direct (non-BIS) source.
"""
from __future__ import annotations

import logging
import re
from datetime import date as _date, timedelta

import httpx

import config
from models import SpeechItem
from sources import bis, html_list, js_list, rss

log = logging.getLogger(__name__)


def _get(url: str) -> str:
    headers = {"User-Agent": config.HTTP_USER_AGENT}
    r = httpx.get(url, headers=headers, timeout=config.HTTP_TIMEOUT_S,
                  follow_redirects=True)
    r.raise_for_status()
    return r.text


def _fetch_playwright(feed: dict) -> list[SpeechItem]:
    from sources import ecb_playwright
    return ecb_playwright.fetch_speeches(feed)


def _parse_feed(feed: dict, text: str) -> list[SpeechItem]:
    if feed["kind"] == "bis":
        return bis.parse_feed(text)
    return rss.parse_feed(text, default_bank=feed["bank"],
                          region=feed["region"], source=feed["name"],
                          include=feed.get("include"),
                          url_include=feed.get("url_include"),
                          category=feed.get("category", "speech"))


def directly_covered_banks() -> set[str]:
    """Banks that have a same-day source of their own.

    Derived from the configured feeds rather than hardcoded, so adding a direct
    source automatically tightens that bank's BIS gate with no other change.
    """
    return {f["bank"] for f in list(config.FEEDS) + list(config.POLICY_FEEDS)
            if f["kind"] != "bis" and f.get("bank")}


def apply_freshness_gate(items: list[SpeechItem]) -> list[SpeechItem]:
    """Drop stale BIS items.

    BIS lags delivery by 14-31 days; without a gate, a 3-week-old speech BIS has
    only just published is emailed as though it were news. Banks we cover
    directly are held to BIS_MAX_AGE_DAYS, since anything genuinely new arrives
    via their own source. Banks we cannot scrape have no other channel, so they
    are allowed the much longer BIS_FALLBACK_MAX_AGE_DAYS — late coverage beats
    none, and the digest marks those items as published late.
    """
    covered = directly_covered_banks()
    today = _date.today()
    kept = []
    for i in items:
        max_age = (config.BIS_MAX_AGE_DAYS if i.bank in covered
                   else config.BIS_FALLBACK_MAX_AGE_DAYS)
        if (today - i.published).days <= max_age:
            kept.append(i)
    return kept


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


def fetch_all() -> tuple[list[SpeechItem], dict[str, dict[str, int]]]:
    """Fetch every configured source.

    Returns the deduped items plus a per-source report used by the health
    monitor: {name: {"items": n, "no_speaker": m}}. A source that raises is
    logged, reported as zero, and does not abort the run.
    """
    collected: list[SpeechItem] = []
    counts: dict[str, dict[str, int]] = {}
    for feed in list(config.FEEDS) + list(config.POLICY_FEEDS):
        name = feed["name"]
        try:
            if feed["kind"] == "playwright":
                parsed = _fetch_playwright(feed)
            elif feed["kind"] == "html_list":
                parsed = html_list.fetch(feed)
            elif feed["kind"] == "js_list":
                parsed = js_list.fetch(feed)
            else:
                parsed = _parse_feed(feed, _get(feed["url"]))
            if feed["kind"] == "bis":
                before = len(parsed)
                parsed = apply_freshness_gate(parsed)
                if before != len(parsed):
                    log.info("bis: dropped %d stale items (older than %dd)",
                             before - len(parsed), config.BIS_MAX_AGE_DAYS)
            # Missing speakers are only meaningful for scraped *speech*
            # listings, where they signal a drifted byline selector. Several
            # RSS feeds (Fed Board, BoE, RBA, BoC) never populate an author,
            # and a policy statement is institutional rather than delivered by
            # a named person — counting either would fire the health alert on
            # every run and turn it into noise.
            # `speaker_optional` marks listings that genuinely carry no byline
            # (the Kansas City Fed's), where a missing speaker is not drift.
            speaker_check = (feed["kind"] in ("html_list", "js_list")
                             and feed.get("category", "speech") == "speech"
                             and not feed.get("speaker_optional"))
            counts[name] = {
                "items": len(parsed),
                "no_speaker": (html_list.count_missing_speakers(parsed)
                               if speaker_check else 0),
            }
            log.info("feed %s: %d items", name, len(parsed))
            collected.extend(parsed)
        except Exception as e:  # one source down must not abort the run
            log.warning("feed %s failed: %s: %s", name, type(e).__name__, e)
            counts[name] = {"items": 0, "no_speaker": 0}
    return dedup(collected), counts
