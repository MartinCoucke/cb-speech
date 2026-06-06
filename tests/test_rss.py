from datetime import date
from sources import rss

SAMPLE = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Inflation outlook</title>
    <link>https://www.federalreserve.gov/speech/a.htm/</link>
    <pubDate>Thu, 05 Jun 2026 10:00:00 GMT</pubDate>
    <author>Jane Doe</author>
  </item>
  <item>
    <title>Payments policy</title>
    <link>https://www.federalreserve.gov/speech/b.htm#top</link>
    <pubDate>Wed, 04 Jun 2026 09:00:00 GMT</pubDate>
  </item>
</channel></rss>"""


def test_normalize_url_strips_fragment_and_trailing_slash():
    assert rss.normalize_url("https://x/y/#z") == "https://x/y"
    assert rss.normalize_url("https://x/y/") == "https://x/y"


def test_parse_feed_returns_items():
    items = rss.parse_feed(SAMPLE, default_bank="Federal Reserve",
                           region="US", source="fed")
    assert len(items) == 2
    first = items[0]
    assert first.title == "Inflation outlook"
    assert first.id == "https://www.federalreserve.gov/speech/a.htm"
    assert first.published == date(2026, 6, 5)
    assert first.speaker == "Jane Doe"
    assert first.bank == "Federal Reserve"
    assert first.region == "US"
    # fragment normalized away
    assert items[1].id == "https://www.federalreserve.gov/speech/b.htm"
