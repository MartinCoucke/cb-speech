from datetime import date
import fetcher
from models import SpeechItem


def _item(id_, source, title="t", speaker=None):
    return SpeechItem(id=id_, title=title, url=id_, published=date(2026, 6, 5),
                      speaker=speaker, bank="b", region="US", source=source)


def test_dedup_prefers_direct_feed_over_bis_same_key():
    direct = _item("https://x/a", "fed", title="Outlook")
    bis = _item("https://y/a", "bis", title="Outlook")
    out = fetcher.dedup([bis, direct])  # bis first; direct should win
    assert len(out) == 1
    assert out[0].source == "fed"


def test_dedup_collapses_same_speech_across_different_urls():
    fed = _item("https://federalreserve.gov/x", "fed",
                title="Economic Outlook", speaker="Jerome Powell")
    bis = _item("https://bis.org/y", "bis",
                title="Jerome Powell: Economic Outlook", speaker="Jerome Powell")
    out = fetcher.dedup([bis, fed])
    assert len(out) == 1
    assert out[0].source == "fed"


def test_distinct_speeches_are_kept():
    a = _item("https://x/a", "fed", title="Inflation", speaker="A B")
    b = _item("https://x/b", "fed", title="Employment", speaker="C D")
    assert len(fetcher.dedup([a, b])) == 2


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
