from datetime import date, timedelta
import fetcher
import main
from models import SpeechItem


def _item(title, days_ago, speaker=None, id_=None):
    d = date.today() - timedelta(days=days_ago)
    id_ = id_ or ("https://x/" + title)
    return SpeechItem(id=id_, title=title, url=id_, published=d, speaker=speaker,
                      bank="b", region="US", source="fed")


def test_select_new_filters_seen_and_old():
    items = [_item("alpha", 0), _item("beta", 0), _item("gamma", 10)]
    seen = {fetcher.content_key(_item("beta", 0)): "2026-06-01"}
    new = main.select_new(items, seen, lookback_hours=48)
    titles = {i.title for i in new}
    assert titles == {"alpha"}  # beta already seen, gamma too old


def test_update_seen_adds_content_keys():
    seen = {"old|key": "2026-06-01"}
    item = _item("delta", 0)
    main.update_seen(seen, [item], today="2026-06-06")
    assert seen[fetcher.content_key(item)] == "2026-06-06"
    assert seen["old|key"] == "2026-06-01"
