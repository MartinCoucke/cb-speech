from datetime import date
from sources import ecb_playwright as ecb

ROWS = [
    {"category": "Speech", "title": "Women and leadership",
     "href": "/press/key/date/2026/html/ecb.sp260604~x.en.html",
     "date": "4 June 2026", "speaker": "Christine Lagarde"},
    {"category": "Press conference", "title": "Monetary policy statement",
     "href": "/press/key/date/2026/html/ecb.is260604~y.en.html",
     "date": "4 June 2026", "speaker": "Christine Lagarde"},
    {"category": "Speech", "title": "No link", "href": "",
     "date": "3 June 2026", "speaker": "X"},
    {"category": "Speech", "title": "Bad date",
     "href": "/press/key/date/2026/html/ecb.sp260601~z.en.html",
     "date": "not a date", "speaker": "Y"},
]


def test_parse_date():
    assert ecb._parse_date("4 June 2026") == date(2026, 6, 4)
    assert ecb._parse_date("garbage") is None


def test_parse_entries_keeps_only_linked_dated_speeches():
    items = ecb.parse_entries(ROWS, bank="ECB", region="Europe")
    assert len(items) == 1
    it = items[0]
    assert it.bank == "ECB"
    assert it.region == "Europe"
    assert it.source == "ecb"
    assert it.speaker == "Christine Lagarde"
    assert it.url == "https://www.ecb.europa.eu/press/key/date/2026/html/ecb.sp260604~x.en.html"
    assert it.id == it.url
    assert it.published == date(2026, 6, 4)
