import pytest
import creds


def test_load_prefers_env(monkeypatch):
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "pw")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "key")
    out = creds.load()
    assert out == {"GMAIL_APP_PASSWORD": "pw", "ANTHROPIC_API_KEY": "key"}


def test_load_reads_secrets_file(monkeypatch, tmp_path):
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    f = tmp_path / "secrets.txt"
    f.write_text("GMAIL_APP_PASSWORD=pw\nANTHROPIC_API_KEY=key\n", encoding="utf-8")
    monkeypatch.setattr(creds.config, "SECRETS_FILE", f)
    assert creds.load()["ANTHROPIC_API_KEY"] == "key"


def test_load_raises_when_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("GMAIL_APP_PASSWORD", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(creds.config, "SECRETS_FILE", tmp_path / "nope.txt")
    with pytest.raises(FileNotFoundError):
        creds.load()
