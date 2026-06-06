"""Rate a speech dovish<->hawkish via Claude Sonnet 4.6 structured output."""
from __future__ import annotations

import json
import logging

import anthropic

import config
import creds as creds_mod
from models import Rating, SpeechItem

log = logging.getLogger(__name__)

RATING_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer",
                  "enum": [-5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "is_monetary_policy": {"type": "boolean"},
        "summary": {"type": "string"},
        "stance_rationale": {"type": "string"},
        "key_quotes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["score", "confidence", "is_monetary_policy", "summary",
                 "stance_rationale", "key_quotes"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You are a monetary-policy analyst. Rate a central bank speech on a "
    "dovish-to-hawkish scale from a markets perspective.\n"
    "Scale: -5 = very dovish (strong easing bias), 0 = neutral/balanced, "
    "+5 = very hawkish (strong tightening bias).\n"
    "If the speech is not about monetary policy (e.g. payments, supervision, "
    "ceremonial), set is_monetary_policy=false, confidence=low, and score=0.\n"
    "Set confidence=low when the stance is genuinely ambiguous. "
    "Write a neutral 2-3 sentence summary, a 1-2 sentence rationale for the "
    "score, and up to two short telling quotes (verbatim if available)."
)


def build_prompt(item: SpeechItem, text: str | None) -> str:
    body = (text or "(full text unavailable — rate from the title only)")
    body = body[: config.MAX_TEXT_CHARS]
    return (
        f"Speaker: {item.speaker or 'unknown'}\n"
        f"Central bank: {item.bank}\n"
        f"Title: {item.title}\n"
        f"Date: {item.published.isoformat()}\n\n"
        f"Speech text:\n{body}"
    )


def parse_rating(payload: dict, *, text_available: bool) -> Rating:
    return Rating(
        score=int(payload["score"]),
        confidence=payload["confidence"],
        is_monetary_policy=bool(payload["is_monetary_policy"]),
        summary=payload["summary"],
        stance_rationale=payload["stance_rationale"],
        key_quotes=list(payload.get("key_quotes", [])),
        text_available=text_available,
    )


def _client() -> anthropic.Anthropic:
    key = creds_mod.load()["ANTHROPIC_API_KEY"]
    return anthropic.Anthropic(api_key=key)


def rate(item: SpeechItem, text: str | None, *, client=None) -> Rating:
    text_available = text is not None
    client = client or _client()
    try:
        resp = client.messages.create(
            model=config.MODEL,
            max_tokens=config.MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_prompt(item, text)}],
            output_config={"format": {"type": "json_schema",
                                      "schema": RATING_SCHEMA}},
        )
        body = next(b.text for b in resp.content if b.type == "text")
        rating = parse_rating(json.loads(body), text_available=text_available)
        if not text_available:
            rating.confidence = "low"
        return rating
    except Exception as e:
        log.warning("rate failed for %s: %s: %s", item.url, type(e).__name__, e)
        return Rating(
            score=0, confidence="low", is_monetary_policy=False,
            summary="(rating unavailable — model call failed)",
            stance_rationale="", key_quotes=[],
            text_available=text_available, error=f"{type(e).__name__}: {e}",
        )
