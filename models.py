"""Shared data shapes for the CB speech agent."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class SpeechItem:
    id: str            # normalized URL — the dedup key
    title: str
    url: str
    published: date
    speaker: str | None
    bank: str
    region: str        # one of: US, Europe, UK, Australia, Canada
    source: str        # feed name that produced this item


@dataclass
class Rating:
    score: int                 # -5 (very dovish) .. +5 (very hawkish)
    confidence: str            # high | medium | low
    is_monetary_policy: bool
    summary: str
    stance_rationale: str
    key_quotes: list[str] = field(default_factory=list)
    text_available: bool = True
    error: str | None = None   # set when the rating could not be produced
