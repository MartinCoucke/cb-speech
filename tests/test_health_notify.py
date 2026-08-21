"""Health alerts must be able to reach the inbox on their own.

Alerts were only rendered inside the digest, and the digest is only sent when
there are new speeches. So when the browser-based sources broke, they produced
nothing, no digest was sent, and the warning was never delivered — the exact
silent failure the health monitor exists to prevent (it ran 17 times unseen).
"""
import main


def test_signature_is_order_independent():
    assert main.alert_signature(["b", "a"]) == main.alert_signature(["a", "b"])


def test_alert_only_email_sent_when_alerts_are_new(monkeypatch, tmp_path):
    monkeypatch.setattr(main.config, "NOTIFIED_FILE", tmp_path / "n.json")
    sent = []
    monkeypatch.setattr(main.email_send, "send",
                        lambda html, subject: sent.append(subject))
    assert main.notify_alerts_if_new(["nyfed is broken"]) is True
    assert len(sent) == 1
    assert "health" in sent[0].lower()


def test_same_alerts_are_not_re_sent(monkeypatch, tmp_path):
    monkeypatch.setattr(main.config, "NOTIFIED_FILE", tmp_path / "n.json")
    sent = []
    monkeypatch.setattr(main.email_send, "send",
                        lambda html, subject: sent.append(subject))
    main.notify_alerts_if_new(["nyfed is broken"])
    # A daily re-send of an unchanged warning would train the reader to ignore it.
    assert main.notify_alerts_if_new(["nyfed is broken"]) is False
    assert len(sent) == 1


def test_a_new_broken_source_re_notifies(monkeypatch, tmp_path):
    monkeypatch.setattr(main.config, "NOTIFIED_FILE", tmp_path / "n.json")
    sent = []
    monkeypatch.setattr(main.email_send, "send",
                        lambda html, subject: sent.append(subject))
    main.notify_alerts_if_new(["nyfed is broken"])
    assert main.notify_alerts_if_new(["nyfed is broken", "ecb is broken"]) is True
    assert len(sent) == 2


def test_no_alerts_sends_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(main.config, "NOTIFIED_FILE", tmp_path / "n.json")
    sent = []
    monkeypatch.setattr(main.email_send, "send",
                        lambda html, subject: sent.append(subject))
    assert main.notify_alerts_if_new([]) is False
    assert sent == []
