"""Fetch a speech page and return clean plain text (HTML or PDF)."""
from __future__ import annotations

import io
import logging

import httpx
from bs4 import BeautifulSoup
from pypdf import PdfReader

import config

log = logging.getLogger(__name__)


def extract_from_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = main.get_text(separator="\n")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines)


def extract_from_pdf(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    parts = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(p.strip() for p in parts if p.strip())


def extract_text(url: str) -> str | None:
    """Return clean text, or None if the page can't be fetched/parsed."""
    try:
        headers = {"User-Agent": config.HTTP_USER_AGENT}
        r = httpx.get(url, headers=headers, timeout=config.HTTP_TIMEOUT_S,
                      follow_redirects=True)
        r.raise_for_status()
        ctype = r.headers.get("content-type", "").lower()
        if "pdf" in ctype or url.lower().endswith(".pdf"):
            text = extract_from_pdf(r.content)
        else:
            text = extract_from_html(r.text)
        return text or None
    except Exception as e:
        log.warning("extract failed for %s: %s: %s", url, type(e).__name__, e)
        return None
