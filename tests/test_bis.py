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


from datetime import date


def test_parse_delivery_date_takes_trailing_date():
    desc = ("Speech by Ms Michelle W Bowman, Vice Chair for Supervision of the "
            "Board of Governors of the Federal Reserve System, at the third "
            "annual Financial Inclusion Conference, Washington DC, 14 July 2026.")
    assert bis.parse_delivery_date(desc) == date(2026, 7, 14)


def test_parse_delivery_date_picks_last_when_several():
    desc = "Speech given on 1 January 2020 anniversary, London, 14 July 2026."
    assert bis.parse_delivery_date(desc) == date(2026, 7, 14)


def test_parse_delivery_date_returns_none_when_absent():
    assert bis.parse_delivery_date("Speech by Mr X at a conference.") is None
    assert bis.parse_delivery_date("") is None


def test_parse_feed_uses_delivery_date_not_upload_date():
    xml = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <item>
        <title>John C Williams: Stability of Thy Times</title>
        <link>https://www.bis.org/review/r260803a.htm</link>
        <description>Remarks by Mr John C Williams, President of the Federal
        Reserve Bank of New York, New York City, 15 July 2026.</description>
      </item>
    </channel></rss>"""
    items = bis.parse_feed(xml)
    assert len(items) == 1
    assert items[0].published == date(2026, 7, 15)


def test_parse_feed_marks_unparseable_date_as_ancient():
    xml = """<?xml version="1.0"?>
    <rss version="2.0"><channel>
      <item>
        <title>Someone: A speech</title>
        <link>https://www.bis.org/review/r260803b.htm</link>
        <description>Remarks by Mr Someone, Bank of England, with no date.</description>
      </item>
    </channel></rss>"""
    items = bis.parse_feed(xml)
    assert items[0].published == bis.UNKNOWN_DATE
