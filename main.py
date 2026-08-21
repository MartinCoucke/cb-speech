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


def load_health() -> dict[str, int]:
    if not config.HEALTH_FILE.exists():
        return {}
    try:
        return json.loads(config.HEALTH_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        log.warning("corrupt source_health.json — resetting")
        return {}


def update_health(health: dict[str, int],
                  counts: dict[str, dict[str, int]]) -> None:
    """Count consecutive zero-item runs per source."""
    for name, stats in counts.items():
        health[name] = health.get(name, 0) + 1 if stats["items"] == 0 else 0


def health_alerts(health: dict[str, int],
                  counts: dict[str, dict[str, int]]) -> list[str]:
    """Human-readable warnings for sources that look broken.

    A scraper that silently returns nothing is indistinguishable from a quiet
    news day, so it has to be surfaced explicitly.
    """
    alerts = []
    for name, runs in sorted(health.items()):
        if runs >= config.SOURCE_HEALTH_ALERT_RUNS:
            alerts.append(f"{name} has returned no items for {runs} consecutive "
                          f"runs — the source may be broken.")
    for name, stats in sorted(counts.items()):
        missing, total = stats.get("no_speaker", 0), stats.get("items", 0)
        if total and missing / total >= config.SPEAKER_MISSING_ALERT_RATIO:
            alerts.append(f"{name}: {missing} of {total} items had no speaker "
                          f"— the byline selector may have drifted.")
    return alerts


def alert_signature(alerts: list[str]) -> str:
    return "|".join(sorted(alerts))


def notify_alerts_if_new(alerts: list[str]) -> bool:
    """Email health alerts on their own, when they are new.

    Alerts used to ride along in the digest, but the digest is only sent when
    there are new speeches. A source that breaks produces nothing, so no digest
    goes out and the warning is never seen — which is how four browser-based
    sources stayed dead for 17 runs. Only a *changed* alert set is sent, so a
    standing warning does not arrive daily.
    """
    if not alerts:
        return False
    signature = alert_signature(alerts)
    previous = ""
    if config.NOTIFIED_FILE.exists():
        try:
            previous = json.loads(config.NOTIFIED_FILE.read_text(encoding="utf-8")).get("signature", "")
        except json.JSONDecodeError:
            previous = ""
    if signature == previous:
        return False
    html = email_send.build_html([], alerts=alerts)
    subject = config.HEALTH_SUBJECT_TEMPLATE.format(date=date.today().isoformat())
    email_send.send(html, subject)
    config.NOTIFIED_FILE.parent.mkdir(parents=True, exist_ok=True)
    config.NOTIFIED_FILE.write_text(json.dumps({"signature": signature}, indent=2),
                                    encoding="utf-8")
    log.warning("sent source-health warning email")
    return True


def select_new(items: list[SpeechItem], seen: dict[str, str],
               *, lookback_hours: int) -> list[SpeechItem]:
    """Items not already seen (by ANY identity key) and recent enough."""
    cutoff = date.today() - timedelta(hours=lookback_hours)
    return [i for i in items
            if not (fetcher.identity_keys(i) & seen.keys())
            and i.published >= cutoff]


def update_seen(seen: dict[str, str], items: list[SpeechItem],
                *, today: str) -> None:
    """Record every identity key so the speech is recognised from any source."""
    for i in items:
        for key in fetcher.identity_keys(i):
            seen[key] = today


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

    items, counts = fetcher.fetch_all()
    health = load_health()
    update_health(health, counts)
    alerts = health_alerts(health, counts)
    config.HEALTH_FILE.write_text(json.dumps(health, indent=2), encoding="utf-8")
    for a in alerts:
        log.warning("health: %s", a)

    if not items:
        log.error("no items from any feed")
        _append_log(f"{started.isoformat()} | fail | no_feed_data")
        return 2

    seen = load_seen()
    new = select_new(items, seen, lookback_hours=config.LOOKBACK_HOURS)
    if not new:
        log.info("no new speeches")
        notified = notify_alerts_if_new(alerts)
        _append_log(f"{started.isoformat()} | ok | no_new_speeches "
                    f"({len(items)} seen)"
                    + (f" | health_warning_sent: {len(alerts)}" if notified else ""))
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

    html = email_send.build_html(rated, alerts=alerts)
    subject = email_send.build_subject(rated)
    (archive_dir / "view.html").write_text(html, encoding="utf-8")

    try:
        email_send.send(html, subject)
    except Exception as e:
        log.error("email send failed: %s", e)
        _append_log(f"{started.isoformat()} | fail | send_failed: {e}")
        return 3  # state NOT updated — speeches retry next run

    # The digest carried the alerts, so record them as notified.
    if alerts:
        config.NOTIFIED_FILE.write_text(
            json.dumps({"signature": alert_signature(alerts)}, indent=2),
            encoding="utf-8")
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
