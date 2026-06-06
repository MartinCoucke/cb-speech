import config

# Feeds that deliver same-day (not the lagged BIS aggregator).
_DIRECT_KINDS = ("rss", "playwright")


def test_feeds_have_required_keys():
    assert config.FEEDS, "FEEDS must not be empty"
    for f in config.FEEDS:
        assert {"name", "url", "kind", "region", "bank"} <= set(f.keys())
        assert f["kind"] in ("rss", "bis", "playwright")


def test_five_regions_have_a_direct_feed():
    direct_regions = {f["region"] for f in config.FEEDS if f["kind"] in _DIRECT_KINDS}
    assert {"US", "Europe", "UK", "Australia", "Canada"} <= direct_regions


def test_model_is_sonnet():
    assert config.MODEL == "claude-sonnet-4-6"
