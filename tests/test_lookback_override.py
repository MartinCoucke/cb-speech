"""A one-off backfill must be possible without editing code.

A 25-day outage leaves speeches outside the 48h window permanently: nothing is
marked seen, but select_new also drops anything older than the lookback. The
override lets a manual run widen the window once to recover them.
"""
import importlib
import main


def test_default_lookback_is_used_when_env_is_unset(monkeypatch):
    monkeypatch.delenv("LOOKBACK_HOURS", raising=False)
    import config
    importlib.reload(config)
    assert config.LOOKBACK_HOURS == 48


def test_env_override_widens_the_window(monkeypatch):
    monkeypatch.setenv("LOOKBACK_HOURS", "720")
    import config
    importlib.reload(config)
    assert config.LOOKBACK_HOURS == 720
    monkeypatch.delenv("LOOKBACK_HOURS")
    importlib.reload(config)


def test_garbage_override_falls_back_to_the_default(monkeypatch):
    """A bad value must not crash the daily run."""
    monkeypatch.setenv("LOOKBACK_HOURS", "not-a-number")
    import config
    importlib.reload(config)
    assert config.LOOKBACK_HOURS == 48
    monkeypatch.delenv("LOOKBACK_HOURS")
    importlib.reload(config)


def test_wider_window_selects_older_items():
    from datetime import date, timedelta
    from models import SpeechItem
    old = SpeechItem(id="x", title="Old one", url="x",
                     published=date.today() - timedelta(days=10),
                     speaker="A B", bank="b", region="US", source="fed")
    assert main.select_new([old], {}, lookback_hours=48) == []
    assert main.select_new([old], {}, lookback_hours=24 * 30) == [old]
