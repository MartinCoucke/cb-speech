import json
from datetime import date
import types

import rate
from models import SpeechItem


def _item():
    return SpeechItem(id="https://x/a", title="Outlook", url="https://x/a",
                      published=date(2026, 6, 5), speaker="Jane Doe",
                      bank="Federal Reserve", region="US", source="fed")


def test_build_prompt_includes_title_and_text():
    p = rate.build_prompt(_item(), "rates will stay restrictive")
    assert "Outlook" in p
    assert "rates will stay restrictive" in p


def test_parse_rating_from_payload():
    payload = {
        "score": 3, "confidence": "high", "is_monetary_policy": True,
        "summary": "s", "stance_rationale": "r", "key_quotes": ["q1"],
    }
    r = rate.parse_rating(payload, text_available=True)
    assert r.score == 3
    assert r.confidence == "high"
    assert r.text_available is True
    assert r.error is None


class _FakeClient:
    def __init__(self, payload):
        block = types.SimpleNamespace(type="text", text=json.dumps(payload))
        msg = types.SimpleNamespace(content=[block])
        self.messages = types.SimpleNamespace(create=lambda **k: msg)


def test_rate_uses_client_and_returns_rating():
    payload = {
        "score": -2, "confidence": "medium", "is_monetary_policy": True,
        "summary": "dovish tone", "stance_rationale": "rate cuts hinted",
        "key_quotes": ["we may ease"],
    }
    r = rate.rate(_item(), "some speech text", client=_FakeClient(payload))
    assert r.score == -2
    assert r.summary == "dovish tone"


def test_rate_without_text_forces_low_confidence():
    payload = {
        "score": 1, "confidence": "high", "is_monetary_policy": True,
        "summary": "s", "stance_rationale": "r", "key_quotes": [],
    }
    r = rate.rate(_item(), None, client=_FakeClient(payload))
    assert r.text_available is False
    assert r.confidence == "low"
