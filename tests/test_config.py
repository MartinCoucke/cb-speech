import config

# Feeds that deliver same-day (not the lagged BIS aggregator).
_DIRECT_KINDS = ("rss", "playwright", "html_list", "js_list")


def test_feeds_have_required_keys():
    assert config.FEEDS, "FEEDS must not be empty"
    for f in config.FEEDS:
        assert {"name", "url", "kind", "region", "bank"} <= set(f.keys())
        assert f["kind"] in ("rss", "bis", "playwright", "html_list", "js_list")


def test_html_list_feeds_declare_their_selectors():
    """A missing selector key would raise at fetch time, in production."""
    required = {"base", "row_selector", "link_selector", "date_formats"}
    html_feeds = [f for f in config.FEEDS
              if f["kind"] in ("html_list", "js_list")]
    assert html_feeds, "expected at least one html_list source"
    for f in html_feeds:
        assert required <= set(f.keys()), f"{f['name']} is missing selectors"
        assert (f.get("date_selector") or f.get("date_regex")
                or f.get("date_url_regex")), (
            f"{f['name']} needs a date selector, regex, or url regex")
        assert f["date_formats"], f"{f['name']} has no date formats"


def test_five_regions_have_a_direct_feed():
    direct_regions = {f["region"] for f in config.FEEDS if f["kind"] in _DIRECT_KINDS}
    assert {"US", "Europe", "UK", "Australia", "Canada"} <= direct_regions


def test_model_is_sonnet():
    assert config.MODEL == "claude-sonnet-4-6"


def test_banca_italia_covers_governor_and_board():
    """Panetta (Governor) and the rest of the board are on separate listings.
    Covering only one would tighten the bank's BIS gate while leaving the other
    half with no source at all."""
    urls = [f["url"] for f in config.FEEDS if f["bank"] == "Banca d'Italia"]
    assert any("interventi-governatore" in u for u in urls)
    assert any("interventi-direttorio" in u for u in urls)
