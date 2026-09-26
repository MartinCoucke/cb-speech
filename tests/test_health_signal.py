"""Health must distinguish "source is broken" from "nothing happened".

The old signal was consecutive runs with zero *matched* items. That is sound for
a scraped listing (the NY Fed returns 700 rows every day, so zero means broken)
but meaningless for a filtered feed: `ecb_policy` only keeps decision headlines,
and the ECB sets rates roughly every six weeks, so zero matches is normal for
weeks at a time. It sat at 19 and was reported as broken while working perfectly
— 8 spurious warning emails went out.

The signal is now the count *before* filtering: no entries at all means broken;
entries present with nothing matching means a quiet period. A separate, much
longer counter still catches a filter that has genuinely drifted.
"""
import main


def _counts(name, items, raw_items, no_speaker=0):
    return {name: {"items": items, "raw_items": raw_items,
                   "no_speaker": no_speaker}}


def test_quiet_filtered_feed_is_healthy(monkeypatch):
    """15 entries in the feed, none are a rate decision — this is the ECB
    between meetings, not a breakage."""
    monkeypatch.setattr(main.config, "SOURCE_HEALTH_ALERT_RUNS", 3)
    monkeypatch.setattr(main.config, "STALE_MATCH_ALERT_RUNS", 75)
    health = {}
    for _ in range(30):
        main.update_health(health, _counts("ecb_policy", items=0, raw_items=15))
    assert main.health_alerts(health, _counts("ecb_policy", 0, 15)) == []


def test_empty_feed_alerts_quickly(monkeypatch):
    """No entries at all means the fetch or parse is broken."""
    monkeypatch.setattr(main.config, "SOURCE_HEALTH_ALERT_RUNS", 3)
    monkeypatch.setattr(main.config, "STALE_MATCH_ALERT_RUNS", 75)
    health = {}
    for _ in range(3):
        main.update_health(health, _counts("nyfed", items=0, raw_items=0))
    alerts = main.health_alerts(health, _counts("nyfed", 0, 0))
    assert len(alerts) == 1
    assert "no entries" in alerts[0]


def test_producing_source_resets_both_counters(monkeypatch):
    monkeypatch.setattr(main.config, "SOURCE_HEALTH_ALERT_RUNS", 3)
    health = {}
    for _ in range(5):
        main.update_health(health, _counts("nyfed", items=0, raw_items=0))
    main.update_health(health, _counts("nyfed", items=4, raw_items=700))
    assert main.health_alerts(health, _counts("nyfed", 4, 700)) == []


def test_long_dry_spell_flags_a_drifted_filter(monkeypatch):
    """A live feed whose filter has stopped matching anything for months is a
    real failure — just a much slower one than an empty feed."""
    monkeypatch.setattr(main.config, "SOURCE_HEALTH_ALERT_RUNS", 3)
    monkeypatch.setattr(main.config, "STALE_MATCH_ALERT_RUNS", 75)
    health = {}
    for _ in range(75):
        main.update_health(health, _counts("ecb_policy", items=0, raw_items=15))
    alerts = main.health_alerts(health, _counts("ecb_policy", 0, 15))
    assert len(alerts) == 1
    assert "drift" in alerts[0].lower()


def test_broken_and_stale_do_not_double_report(monkeypatch):
    monkeypatch.setattr(main.config, "SOURCE_HEALTH_ALERT_RUNS", 3)
    monkeypatch.setattr(main.config, "STALE_MATCH_ALERT_RUNS", 5)
    health = {}
    for _ in range(10):
        main.update_health(health, _counts("boe", items=0, raw_items=0))
    assert len(main.health_alerts(health, _counts("boe", 0, 0))) == 1


def test_legacy_int_state_is_migrated(monkeypatch):
    """state/source_health.json already exists in production holding plain
    ints; it must not crash or lose the streak."""
    monkeypatch.setattr(main.config, "SOURCE_HEALTH_ALERT_RUNS", 3)
    health = {"nyfed": 2}                       # legacy format
    main.update_health(health, _counts("nyfed", items=0, raw_items=0))
    alerts = main.health_alerts(health, _counts("nyfed", 0, 0))
    assert len(alerts) == 1                     # 2 + 1 == threshold
