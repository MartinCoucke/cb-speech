from datetime import date
from sources import html_list

FEED = {
    "name": "demo", "kind": "html_list", "region": "US", "bank": "Demo Bank",
    "url": "https://demo.example/speeches", "base": "https://demo.example",
    "row_selector": "tr",
    "link_selector": "td.right a",
    "date_selector": "td.left",
    "date_formats": ["%b %d, %Y"],
}

HTML = """<table><tbody>
  <tr><td class="left"><div>Jul 15, 2026</div></td>
      <td class="right"><a href="/speeches/2026/a">Williams: Stability of Thy Times</a></td></tr>
  <tr><td class="left"><div>Jul 09, 2026</div></td>
      <td class="right"><a href="https://demo.example/speeches/2026/b">Perli: Repo Market Structure</a></td></tr>
  <tr><td class="left"><div>not a date</div></td>
      <td class="right"><a href="/speeches/2026/c">Bad: Row</a></td></tr>
  <tr><td class="left"><div>Jul 01, 2026</div></td><td class="right">no link</td></tr>
</tbody></table>"""


def test_parses_rows_into_items():
    items = html_list.parse_rows(HTML, FEED)
    assert [i.title for i in items] == ["Williams: Stability of Thy Times",
                                        "Perli: Repo Market Structure"]
    assert items[0].published == date(2026, 7, 15)
    assert items[0].bank == "Demo Bank"
    assert items[0].region == "US"
    assert items[0].source == "demo"


def test_relative_urls_resolve_against_base():
    items = html_list.parse_rows(HTML, FEED)
    assert items[0].url == "https://demo.example/speeches/2026/a"
    assert items[1].url == "https://demo.example/speeches/2026/b"


def test_rows_without_link_or_valid_date_are_skipped():
    assert len(html_list.parse_rows(HTML, FEED)) == 2


def test_speaker_derived_from_title_prefix():
    items = html_list.parse_rows(HTML, FEED)
    assert items[0].speaker == "Williams"


def test_speaker_selector_used_when_present():
    feed = dict(FEED, row_selector="div.row", link_selector="h1 a",
                date_selector="p.date", speaker_selector="ul.speaker a",
                date_formats=["%B %d, %Y"])
    html = """<div class="row">
      <h1><a href="/s/1">The U.S. Economy: Resilience Amid Risks</a></h1>
      <ul class="speaker"><li><a href="/p/1">Susan M. Collins, President &amp; CEO</a></li></ul>
      <p class="date">May 13, 2026    |Boston, Massachusetts</p>
    </div>"""
    items = html_list.parse_rows(html, feed)
    assert items[0].speaker == "Susan M. Collins"
    assert items[0].published == date(2026, 5, 13)


def test_duplicate_hrefs_collapse():
    """Nested row containers must not yield the same speech twice."""
    html = ('<div class="row"><div class="row">'
            '<h1><a href="/s/1">A Speech</a></h1><p class="date">May 13, 2026</p>'
            '</div></div>')
    feed = dict(FEED, row_selector="div.row", link_selector="h1 a",
                date_selector="p.date", date_formats=["%B %d, %Y"])
    assert len(html_list.parse_rows(html, feed)) == 1


def test_missing_speaker_is_reported_not_dropped():
    html = ('<table><tbody><tr><td class="left">Jul 15, 2026</td>'
            '<td class="right"><a href="/s/1">A speech with no speaker</a></td>'
            '</tr></tbody></table>')
    items = html_list.parse_rows(html, FEED)
    assert len(items) == 1                 # never dropped
    assert items[0].speaker is None
    assert html_list.count_missing_speakers(items) == 1


def test_possessive_collection_label_is_stripped_from_speaker():
    """The SF Fed labels rows "Mary C. Daly's Speeches"; left as-is the dedup
    key's surname would become "speeches"."""
    feed = dict(FEED, row_selector="div.row", link_selector="h1 a",
                date_selector="p.date", speaker_selector="span.term",
                date_formats=["%B %d, %Y"])
    html = ('<div class="row"><span class="term">Mary C. Daly’s Speeches</span>'
            '<h1><a href="/s/1">Regionalism at the Federal Reserve</a></h1>'
            '<p class="date">April 8, 2026</p></div>')
    items = html_list.parse_rows(html, feed)
    assert items[0].speaker == "Mary C. Daly"
