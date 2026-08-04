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
    out = fetcher.fetch_all()
    assert {i.id for i in out} == {"https://x/a", "https://x/b"}


def test_fetch_all_handles_playwright(monkeypatch):
    feeds = [{"name": "ecb", "kind": "playwright", "region": "Europe",
              "bank": "ECB", "url": "u"}]
    monkeypatch.setattr(fetcher.config, "FEEDS", feeds)
    monkeypatch.setattr(fetcher, "_fetch_playwright",
                        lambda feed: [_item("https://x/e", "ecb", title="E")])
    out = fetcher.fetch_all()
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
    out = fetcher.fetch_all()
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
