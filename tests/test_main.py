from datetime import date, timedelta
import fetcher
import main
from models import SpeechItem


def _item(title, days_ago, speaker=None, id_=None, region="US"):
    d = date.today() - timedelta(days=days_ago)
    id_ = id_ or ("https://x/" + title)
    return SpeechItem(id=id_, title=title, url=id_, published=d, speaker=speaker,
                      bank="b", region=region, source="fed")


def test_select_new_filters_seen_and_old():
    items = [_item("alpha", 0), _item("beta", 0), _item("gamma", 10)]
    seen = {k: "2026-06-01" for k in fetcher.identity_keys(_item("beta", 0))}
    new = main.select_new(items, seen, lookback_hours=48)
    assert {i.title for i in new} == {"alpha"}


def test_select_new_matches_on_any_key():
    """A speech first stored without a speaker is still recognised when it
    later arrives with one."""
    stored = _item("stability of thy times", 0, speaker=None)
    seen = {k: "2026-08-01" for k in fetcher.identity_keys(stored)}
    incoming = _item("stability of thy times", 0, speaker="John C Williams")
    assert main.select_new([incoming], seen, lookback_hours=48) == []


def test_legacy_single_key_still_suppresses():
    """Pre-existing seen.json entries use the bare `surname|title` format."""
    incoming = _item("economic outlook", 0, speaker="Lisa D Cook")
    seen = {"cook|economic outlook": "2026-07-16"}
    assert main.select_new([incoming], seen, lookback_hours=48) == []


def test_update_seen_writes_every_key():
    seen = {}
    item = _item("delta", 0, speaker="Jane Doe")
    main.update_seen(seen, [item], today="2026-08-04")
    assert fetcher.identity_keys(item) <= set(seen)
    assert all(v == "2026-08-04" for v in seen.values())
