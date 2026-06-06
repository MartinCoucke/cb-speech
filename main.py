"""Orchestrator: fetch feeds, dedup, extract, rate, email, persist state.

Exit codes:
  0  = success (email sent if there were new speeches; silent if none)
  2  = all feeds failed (no items at all)
  3  = email send failed (state NOT updated; speeches retry next run)
  99 = unhandled exception

State (`state/seen.json`) is keyed by a source-independent content key (see
fetcher.content_key) and written only after a successful send, so a failed
extract/rate/send never silently marks a speech as seen.
"""
from __future__ import annotations

import json
import logging
import sys
import traceback
from datetime import date, datetime, timedelta, timezone

import config
import email_send
import extract
import fetcher
import rate as rate_mod
from models import SpeechItem

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("main")


def _today_str() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def load_seen() -> dict[str, str]:
    if not config.SEEN_FILE.exists():
        return {}
    try:
        return json.loads(config.SEEN_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        log.warning("corrupt seen.json — treating as empty: %s", e)
        return {}


def select_new(items: list[SpeechItem], seen: dict[str, str],
               *, lookback_hours: int) -> list[SpeechItem]:
    cutoff = date.today() - timedelta(hours=lookback_hours)
    return [i for i in items
            if fetcher.content_key(i) not in seen and i.published >= cutoff]


def update_seen(seen: dict[str, str], items: list[SpeechItem],
                *, today: str) -> None:
    for i in items:
        seen[fetcher.content_key(i)] = today


def _append_log(line: str) -> None:
    with config.RUNS_LOG.open("a", encoding="utf-8") as fp:
        fp.write(line + "\n")


def _archive_name(item: SpeechItem) -> str:
    return f"{item.source}-{abs(hash(item.id))}.json"


def run() -> int:
    started = datetime.now(timezone.utc)
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    archive_dir = config.ARCHIVE_DIR / _today_str()
    archive_dir.mkdir(parents=True, exist_ok=True)

    items = fetcher.fetch_all()
    if not items:
        log.error("no items from any feed")
        _append_log(f"{started.isoformat()} | fail | no_feed_data")
        return 2

    seen = load_seen()
    new = select_new(items, seen, lookback_hours=config.LOOKBACK_HOURS)
    if not new:
        log.info("no new speeches")
        _append_log(f"{started.isoformat()} | ok | no_new_speeches "
                    f"({len(items)} seen)")
        return 0

    rated = []
    for item in new:
        text = extract.extract_text(item.url)
        rating = rate_mod.rate(item, text)
        rated.append((item, rating))
        (archive_dir / _archive_name(item)).write_text(
            json.dumps(
                {"item": item.__dict__ | {"published": item.published.isoformat()},
                 "rating": rating.__dict__},
                indent=2, default=str),
            encoding="utf-8",
        )
        log.info("rated %s: score=%s conf=%s", item.url, rating.score,
                 rating.confidence)

    html = email_send.build_html(rated)
    subject = email_send.build_subject(rated)
    (archive_dir / "view.html").write_text(html, encoding="utf-8")

    try:
        email_send.send(html, subject)
    except Exception as e:
        log.error("email send failed: %s", e)
        _append_log(f"{started.isoformat()} | fail | send_failed: {e}")
        return 3  # state NOT updated — speeches retry next run

    update_seen(seen, new, today=_today_str())
    config.SEEN_FILE.write_text(json.dumps(seen, indent=2), encoding="utf-8")
    _append_log(f"{started.isoformat()} | ok | sent {len(new)} new speeches")
    return 0


def main() -> int:
    try:
        return run()
    except Exception:
        log.error("unhandled exception:\n%s", traceback.format_exc())
        return 99


if __name__ == "__main__":
    sys.exit(main())
