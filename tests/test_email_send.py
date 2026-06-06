from datetime import date
import email_send
from models import SpeechItem, Rating


def _pair(score, region, speaker, mp=True, conf="high"):
    item = SpeechItem(id="https://x/" + speaker, title="t", url="https://x/" + speaker,
                      published=date(2026, 6, 5), speaker=speaker,
                      bank="Bank", region=region, source="fed")
    rating = Rating(score=score, confidence=conf, is_monetary_policy=mp,
                    summary="sum", stance_rationale="why", key_quotes=["q"])
    return item, rating


def test_subject_counts_stances():
    rated = [_pair(3, "US", "A"), _pair(-2, "Europe", "B"), _pair(0, "UK", "C")]
    subj = email_send.build_subject(rated)
    assert "3 new" in subj
    assert "1 hawkish" in subj
    assert "1 dovish" in subj
    assert "1 neutral" in subj


def test_html_groups_by_region_and_shows_speaker():
    rated = [_pair(4, "US", "Hawk"), _pair(-4, "Europe", "Dove")]
    html = email_send.build_html(rated)
    assert "Hawk" in html and "Dove" in html
    assert "US" in html and "Europe" in html
    assert html.index("US") < html.index("Europe")  # region order


def test_html_sorts_by_absolute_score_within_region():
    rated = [_pair(1, "US", "Mild"), _pair(5, "US", "Strong")]
    html = email_send.build_html(rated)
    assert html.index("Strong") < html.index("Mild")
