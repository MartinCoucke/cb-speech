"""Post-meeting policy decisions / press-conference opening statements.

Spec: docs/superpowers/specs/2026-06-19-press-conference-coverage-design.md
"""
from datetime import date

import config
import email_send
import fetcher
from models import Rating, SpeechItem
from sources import html_list, rss


def _item(title, category="speech", score=0, region="US", speaker="A B",
          published=None):
    return SpeechItem(id="https://x/" + title, title=title, url="https://x/",
                      published=published or date(2026, 7, 29), speaker=speaker,
                      bank="b", region=region, source="s", category=category)


def _rating(score):
    return Rating(score=score, confidence="high", is_monetary_policy=True,
                  summary="s", stance_rationale="r", key_quotes=[])


# --- model -------------------------------------------------------------

def test_speechitem_defaults_to_speech_category():
    assert _item("x").category == "speech"


# --- sources stamp the category ---------------------------------------

RSS_XML = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item><title>Federal Reserve issues FOMC statement</title>
    <link>https://fed/a</link><pubDate>Wed, 29 Jul 2026 18:00:00 GMT</pubDate></item>
  <item><title>Minutes of the Federal Open Market Committee</title>
    <link>https://fed/b</link><pubDate>Wed, 29 Jul 2026 18:00:00 GMT</pubDate></item>
</channel></rss>"""


def test_rss_stamps_category_and_filters_to_the_decision():
    items = rss.parse_feed(RSS_XML, default_bank="Fed", region="US",
                           source="fed_policy", include=["fomc statement"],
                           category="press_conference")
    assert [i.title for i in items] == ["Federal Reserve issues FOMC statement"]
    assert items[0].category == "press_conference"


RBA_HTML = """<div class="list">
  <article class="item rss-mr-item"><div class="title">
      <a href="/media-releases/2026/mr-26-15.html">Statement by the Monetary Policy Board: Monetary Policy Decision</a></div>
    <div class="info"><span class="date"><time datetime="2026-07-08">8 July 2026</time></span></div></article>
  <article class="item rss-mr-item"><div class="title">
      <a href="/media-releases/2026/mr-26-18.html">A2A Payments Roundtable</a></div>
    <div class="info"><span class="date"><time datetime="2026-07-08">8 July 2026</time></span></div></article>
</div>"""

RBA_FEED = {
    "name": "rba_policy", "kind": "html_list", "region": "Australia",
    "bank": "Reserve Bank of Australia", "base": "https://www.rba.gov.au",
    "url": "https://www.rba.gov.au/media-releases/{year}/",
    "row_selector": "article.item", "link_selector": "div.title a",
    "date_selector": "span.date", "date_formats": ["%d %B %Y"],
    "include": ["statement by the monetary policy board"],
    "category": "press_conference",
}


def test_html_list_filters_by_title_and_stamps_category():
    items = html_list.parse_rows(RBA_HTML, RBA_FEED)
    assert len(items) == 1
    assert items[0].title.startswith("Statement by the Monetary Policy Board")
    assert items[0].category == "press_conference"
    assert items[0].published == date(2026, 7, 8)


def test_year_placeholder_is_resolved():
    """The RBA lists releases per year, so the URL must not hardcode one."""
    url = html_list.resolve_url(RBA_FEED["url"])
    assert "{year}" not in url
    assert str(date.today().year) in url


# --- config ------------------------------------------------------------

def test_every_region_has_a_policy_feed():
    regions = {f["region"] for f in config.POLICY_FEEDS}
    assert {"US", "Europe", "UK", "Australia", "Canada"} <= regions


def test_policy_feeds_are_filtered_and_categorised():
    assert config.POLICY_FEEDS, "expected policy feeds"
    for f in config.POLICY_FEEDS:
        assert f.get("include"), f"{f['name']} must filter out non-decisions"
        assert f["category"] == "press_conference"


def test_fetcher_includes_policy_feeds(monkeypatch):
    monkeypatch.setattr(fetcher.config, "FEEDS", [])
    monkeypatch.setattr(fetcher.config, "POLICY_FEEDS", [
        {"name": "fed_policy", "kind": "rss", "region": "US", "bank": "Fed",
         "url": "u", "include": ["fomc statement"], "category": "press_conference"}])
    monkeypatch.setattr(fetcher, "_get", lambda url: RSS_XML)
    items, counts = fetcher.fetch_all()
    assert [i.category for i in items] == ["press_conference"]
    assert counts["fed_policy"]["items"] == 1


# --- email -------------------------------------------------------------

def test_policy_decisions_sort_above_speeches_in_their_region():
    """A decision outranks a speech even with a lower absolute score."""
    rated = [(_item("A big speech", score=5), _rating(5)),
             (_item("FOMC statement", category="press_conference"), _rating(1))]
    html = email_send.build_html(rated)
    assert html.index("FOMC statement") < html.index("A big speech")


def test_policy_decision_is_visually_flagged():
    rated = [(_item("FOMC statement", category="press_conference"), _rating(1))]
    html = email_send.build_html(rated)
    assert "Policy decision" in html


def test_plain_speech_has_no_policy_flag():
    rated = [(_item("Just a speech"), _rating(1))]
    assert "Policy decision" not in email_send.build_html(rated)


def test_policy_sources_do_not_trigger_speaker_alerts(monkeypatch):
    """A policy statement is institutional, not delivered by a named person,
    so a missing speaker there is normal and must not raise an alert."""
    monkeypatch.setattr(fetcher.config, "FEEDS", [])
    monkeypatch.setattr(fetcher.config, "POLICY_FEEDS", [dict(RBA_FEED)])
    monkeypatch.setattr(fetcher.html_list, "fetch",
                        lambda feed: html_list.parse_rows(RBA_HTML, feed))
    _items, counts = fetcher.fetch_all()
    assert counts["rba_policy"]["items"] == 1
    assert counts["rba_policy"]["no_speaker"] == 0
