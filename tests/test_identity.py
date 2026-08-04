from datetime import date
import fetcher
from models import SpeechItem


def _mk(title, speaker, source, region="US", published=date(2026, 7, 15)):
    return SpeechItem(id="https://x/" + title, title=title, url="https://x/",
                      published=published, speaker=speaker, bank="b",
                      region=region, source=source)


def test_speaker_key_matches_legacy_format():
    """Key 1 must keep the exact pre-existing format so entries already in
    state/seen.json continue to suppress their speeches."""
    item = _mk("Economic Outlook", "Lisa D Cook", "fed")
    assert "cook|economic outlook" in fetcher.identity_keys(item)


def test_bis_title_prefix_stripped_when_it_is_the_speaker():
    bis = _mk("John C Williams: Stability of Thy Times", "John C Williams", "bis")
    direct = _mk("Williams: Stability of Thy Times", "Williams", "nyfed")
    assert fetcher.identity_keys(bis) & fetcher.identity_keys(direct)


def test_colon_in_real_title_is_not_stripped():
    """Boston-style titles contain a colon that is NOT a speaker prefix."""
    item = _mk("The U.S. Economy: Resilience Amid Risks", "Susan M. Collins", "boston")
    assert "collins|the u s economy resilience amid risks" in fetcher.identity_keys(item)


def test_missing_speaker_still_matches_via_fallback_key():
    with_sp = _mk("Stability of Thy Times", "John C Williams", "bis")
    without = _mk("Stability of Thy Times", None, "nyfed")
    assert fetcher.identity_keys(with_sp) & fetcher.identity_keys(without)


def test_same_title_different_date_not_merged():
    a = _mk("Global imbalances growth and stability", None, "bis",
            published=date(2026, 7, 1))
    b = _mk("Global imbalances growth and stability", None, "bis",
            published=date(2026, 7, 20))
    assert not (fetcher.identity_keys(a) & fetcher.identity_keys(b))


def test_same_title_different_region_not_merged():
    a = _mk("Economic outlook", None, "bis", region="US")
    b = _mk("Economic outlook", None, "bis", region="Europe")
    assert not (fetcher.identity_keys(a) & fetcher.identity_keys(b))


def test_dedup_prefers_direct_source_over_bis():
    bis = _mk("Stability of Thy Times", "John C Williams", "bis")
    direct = _mk("Stability of Thy Times", "Williams", "nyfed")
    out = fetcher.dedup([bis, direct])
    assert len(out) == 1
    assert out[0].source == "nyfed"
