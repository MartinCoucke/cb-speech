"""BIS as a fallback for banks with no direct source.

Banks whose sites are JavaScript-only or block scraping (Banque de France, DNB,
Banco de España, several regional Feds) would vanish entirely once BIS is gated
at 7 days. For those, BIS is the only channel, so a longer window applies and
the digest labels the item as delivered weeks earlier.
"""
from datetime import date, timedelta

import config
import email_send
import fetcher
from models import Rating, SpeechItem
from sources import bis


def _item(bank, days_ago, region="US"):
    return SpeechItem(id="https://bis/" + bank + str(days_ago), title="T",
                      url="https://bis/x",
                      published=date.today() - timedelta(days=days_ago),
                      speaker="A B", bank=bank, region=region, source="bis")


def test_bis_maps_regional_feds_individually():
    """Without this, every regional president collapses into the Board and the
    fallback cannot tell which banks lack a direct source."""
    assert bis.map_region("Federal Reserve Bank of Dallas") == (
        "Federal Reserve Bank of Dallas", "US")
    assert bis.map_region("Federal Reserve Bank of New York") == (
        "Federal Reserve Bank of New York", "US")
    # The Board still falls through to the generic entry.
    assert bis.map_region("Board of Governors of the Federal Reserve System") == (
        "Federal Reserve", "US")


def test_covered_banks_come_from_config():
    covered = fetcher.directly_covered_banks()
    assert "Federal Reserve Bank of New York" in covered   # scraped directly
    assert "Federal Reserve Bank of Dallas" not in covered  # no direct source


def test_covered_bank_is_gated_tightly(monkeypatch):
    monkeypatch.setattr(config, "BIS_MAX_AGE_DAYS", 7)
    monkeypatch.setattr(config, "BIS_FALLBACK_MAX_AGE_DAYS", 45)
    stale = _item("Federal Reserve Bank of New York", 20)
    assert fetcher.apply_freshness_gate([stale]) == []


def test_uncovered_bank_falls_back_to_bis(monkeypatch):
    monkeypatch.setattr(config, "BIS_MAX_AGE_DAYS", 7)
    monkeypatch.setattr(config, "BIS_FALLBACK_MAX_AGE_DAYS", 45)
    late = _item("Federal Reserve Bank of Dallas", 20)
    assert fetcher.apply_freshness_gate([late]) == [late]


def test_fallback_still_has_an_upper_bound(monkeypatch):
    monkeypatch.setattr(config, "BIS_FALLBACK_MAX_AGE_DAYS", 45)
    ancient = _item("Federal Reserve Bank of Dallas", 200)
    assert fetcher.apply_freshness_gate([ancient]) == []


def test_late_items_are_labelled_in_the_digest(monkeypatch):
    monkeypatch.setattr(email_send.config, "LATE_ITEM_DAYS", 3)
    old = _item("Federal Reserve Bank of Dallas", 20)
    rating = Rating(score=2, confidence="high", is_monetary_policy=True,
                    summary="s", stance_rationale="r", key_quotes=[])
    html = email_send.build_html([(old, rating)])
    assert "delivered" in html
    assert old.published.isoformat() in html


def test_fresh_items_are_not_labelled_late(monkeypatch):
    monkeypatch.setattr(email_send.config, "LATE_ITEM_DAYS", 3)
    fresh = _item("Federal Reserve", 0)
    rating = Rating(score=2, confidence="high", is_monetary_policy=True,
                    summary="s", stance_rationale="r", key_quotes=[])
    assert "delivered" not in email_send.build_html([(fresh, rating)])
