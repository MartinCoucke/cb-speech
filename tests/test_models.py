from datetime import date
from models import SpeechItem, Rating


def test_speechitem_holds_fields():
    item = SpeechItem(
        id="https://x/y",
        title="A speech",
        url="https://x/y",
        published=date(2026, 6, 5),
        speaker="Jane Doe",
        bank="Federal Reserve",
        region="US",
        source="fed",
    )
    assert item.region == "US"
    assert item.speaker == "Jane Doe"


def test_rating_defaults_for_optional_fields():
    r = Rating(
        score=-2,
        confidence="high",
        is_monetary_policy=True,
        summary="s",
        stance_rationale="r",
        key_quotes=["q"],
    )
    assert r.text_available is True
    assert r.error is None
