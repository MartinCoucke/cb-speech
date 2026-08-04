from datetime import date
import fetcher
from models import SpeechItem


def _item(id_, source, title="t", speaker=None, published=None):
    # Default to today so BIS items are not rejected by the freshness gate;
    # tests that care about age set `published` explicitly.
    return SpeechItem(id=id_, title=title, url=id_,
                      published=published or date.today(),
                      speaker=speaker, bank="b", region="US", source=source)


def test_fetch_all_dispatches_and_concatenates(monkeypatch):
    feeds = [
        {"name": "fed", "kind": "rss", "region": "US", "bank": "Fed", "url": "u1"},
        {"name": "bis", "kind": "bis", "region": "", "bank": "", "url": "u2"},
    ]
    monkeypatch.setattr(fetcher.config, "FEEDS", feeds)
    monkeypatch.setattr(fetcher, "_get", lambda url: f"<xml for {url}>")
    monkeypatch.setattr(fetcher.rss, "parse_feed",
                        lambda text, **k: [_item("https://x/a", "fed", title="A")])
    monkeypatch.setattr(fetcher.bis, "parse_feed",
                        lambda text: [_item("https://x/b", "bis", title="B")])
    out, _counts = fetcher.fetch_all()
    assert {i.id for i in out} == {"https://x/a", "https://x/b"}


def test_fetch_all_handles_playwright(monkeypatch):
    feeds = [{"name": "ecb", "kind": "playwright", "region": "Europe",
              "bank": "ECB", "url": "u"}]
    monkeypatch.setattr(fetcher.config, "FEEDS", feeds)
    monkeypatch.setattr(fetcher, "_fetch_playwright",
                        lambda feed: [_item("https://x/e", "ecb", title="E")])
    out, _counts = fetcher.fetch_all()
    assert {i.id for i in out} == {"https://x/e"}


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
                        lambda text, **k: [_item("https://x/b", "boe", title="B")])
    out, _counts = fetcher.fetch_all()
    assert {i.id for i in out} == {"https://x/b"}


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


def test_no_speaker_only_counted_for_scraped_sources(monkeypatch):
    """RSS feeds legitimately lack an author; only scraped listings should
    report missing speakers, or the health alert becomes noise."""
    feeds = [
        {"name": "fed", "kind": "rss", "region": "US", "bank": "Fed", "url": "u1"},
        {"name": "nyfed", "kind": "html_list", "region": "US", "bank": "NY", "url": "u2"},
    ]
    monkeypatch.setattr(fetcher.config, "FEEDS", feeds)
    monkeypatch.setattr(fetcher, "_get", lambda url: "<xml>")
    monkeypatch.setattr(fetcher.rss, "parse_feed",
                        lambda text, **k: [_item("https://x/a", "fed", title="A")])
    monkeypatch.setattr(fetcher.html_list, "fetch",
                        lambda feed: [_item("https://x/b", "nyfed", title="B")])
    _items, counts = fetcher.fetch_all()
    assert counts["fed"]["no_speaker"] == 0      # speakerless RSS is normal
    assert counts["nyfed"]["no_speaker"] == 1    # speakerless scrape is not
