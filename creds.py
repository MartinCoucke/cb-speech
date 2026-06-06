"""Load secrets, env-first (GitHub Actions) then secrets.txt (local)."""
from __future__ import annotations

import os

import config

_REQUIRED = ("GMAIL_APP_PASSWORD", "ANTHROPIC_API_KEY")


def _parse(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def load() -> dict[str, str]:
    env = {k: os.environ.get(k) for k in _REQUIRED}
    if all(env.values()):
        return {k: v for k, v in env.items()}  # type: ignore[misc]

    if not config.SECRETS_FILE.exists():
        raise FileNotFoundError(
            f"Missing secrets. Set env vars {_REQUIRED} or create "
            f"{config.SECRETS_FILE} with one KEY=value per line."
        )
    data = _parse(config.SECRETS_FILE.read_text(encoding="utf-8-sig"))
    missing = [k for k in _REQUIRED if k not in data]
    if missing:
        raise KeyError(f"Missing {missing} in {config.SECRETS_FILE}")
    return {k: data[k] for k in _REQUIRED}
