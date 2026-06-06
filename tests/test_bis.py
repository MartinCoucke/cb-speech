from sources import bis

SAMPLE = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Loretta Mester: Outlook for the US economy</title>
    <link>https://www.bis.org/review/r260605a.htm</link>
    <pubDate>Thu, 05 Jun 2026 10:00:00 GMT</pubDate>
    <description>Speech by Ms Loretta Mester, Federal Reserve Bank of Cleveland</description>
  </item>
  <item>
    <title>Joachim Nagel: German inflation</title>
    <link>https://www.bis.org/review/r260605b.htm</link>
    <pubDate>Thu, 05 Jun 2026 11:00:00 GMT</pubDate>
    <description>Speech by Mr Joachim Nagel, Deutsche Bundesbank</description>
  </item>
  <item>
    <title>Kazuo Ueda: Japan policy</title>
    <link>https://www.bis.org/review/r260605c.htm</link>
    <pubDate>Thu, 05 Jun 2026 12:00:00 GMT</pubDate>
    <description>Speech by Mr Kazuo Ueda, Bank of Japan</description>
  </item>
</channel></rss>"""


def test_map_text_to_region():
    assert bis.map_region("Federal Reserve Bank of Cleveland") == ("Federal Reserve", "US")
    assert bis.map_region("Deutsche Bundesbank") == ("Bundesbank", "Europe")
    assert bis.map_region("Bank of Japan") is None


def test_parse_feed_keeps_target_regions_only():
    items = bis.parse_feed(SAMPLE)
    # Japan dropped; US + Europe kept
    regions = sorted(i.region for i in items)
    assert regions == ["Europe", "US"]
    us = next(i for i in items if i.region == "US")
    assert us.bank == "Federal Reserve"
    assert us.source == "bis"
    assert us.id == "https://www.bis.org/review/r260605a.htm"
