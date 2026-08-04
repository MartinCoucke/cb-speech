import main


def test_zero_items_increments_and_nonzero_resets():
    health = {"nyfed": 2}
    counts = {"nyfed": {"items": 0, "no_speaker": 0},
              "fed": {"items": 5, "no_speaker": 0}}
    main.update_health(health, counts)
    assert health["nyfed"] == 3
    assert health["fed"] == 0


def test_alerts_only_at_threshold(monkeypatch):
    monkeypatch.setattr(main.config, "SOURCE_HEALTH_ALERT_RUNS", 3)
    assert main.health_alerts({"nyfed": 2}, {}) == []
    alerts = main.health_alerts({"nyfed": 3}, {})
    assert len(alerts) == 1
    assert "nyfed" in alerts[0]


def test_missing_speakers_produce_an_alert(monkeypatch):
    monkeypatch.setattr(main.config, "SOURCE_HEALTH_ALERT_RUNS", 3)
    counts = {"bostonfed": {"items": 10, "no_speaker": 4}}
    alerts = main.health_alerts({"bostonfed": 0}, counts)
    assert len(alerts) == 1
    assert "speaker" in alerts[0].lower()
