"""Build the grouped HTML digest and send it via Gmail SMTP."""
from __future__ import annotations

import logging
import smtplib
import ssl
from datetime import date
from email.message import EmailMessage

import config
import creds as creds_mod
from models import Rating, SpeechItem

log = logging.getLogger(__name__)

Rated = tuple[SpeechItem, Rating]


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


def _badge(score: int) -> str:
    if score > 0:
        color, label = "#991b1b", f"+{score} hawkish"
    elif score < 0:
        color, label = "#1e40af", f"{score} dovish"
    else:
        color, label = "#6b7280", "0 neutral"
    return (f"<span style='background:{color}; color:#fff; padding:2px 8px; "
            f"border-radius:10px; font-size:12px; font-weight:600;'>{label}</span>")


def build_subject(rated: list[Rated]) -> str:
    hawk = sum(1 for _, r in rated if r.score > 0)
    dove = sum(1 for _, r in rated if r.score < 0)
    neutral = sum(1 for _, r in rated if r.score == 0)
    summary = (f"{len(rated)} new ({hawk} hawkish, {dove} dovish, "
               f"{neutral} neutral)")
    return config.SUBJECT_TEMPLATE.format(summary=summary,
                                          date=date.today().isoformat())


def _entry(item: SpeechItem, r: Rating) -> str:
    quotes = "".join(
        f"<li style='color:#374151;'>“{_esc(q)}”</li>" for q in r.key_quotes
    )
    quote_block = f"<ul style='margin:6px 0;'>{quotes}</ul>" if quotes else ""
    flags = []
    if not r.is_monetary_policy:
        flags.append("non-monetary")
    if not r.text_available:
        flags.append("rated from title only")
    if r.error:
        flags.append("rating error")
    flag_str = (f" <span style='color:#b45309; font-size:12px;'>"
                f"[{_esc(', '.join(flags))}]</span>") if flags else ""
    return (
        "<div style='margin:0 0 16px; padding:12px; border:1px solid #eee; "
        "border-radius:8px;'>"
        f"<div>{_badge(r.score)} "
        f"<span style='color:#6b7280; font-size:12px;'>confidence: "
        f"{_esc(r.confidence)}</span>{flag_str}</div>"
        f"<div style='font-weight:600; margin:6px 0 2px;'>"
        f"{_esc(item.speaker or 'Unknown speaker')} — {_esc(item.bank)}</div>"
        f"<div style='font-size:13px; margin-bottom:6px;'>"
        f"<a href='{_esc(item.url)}'>{_esc(item.title)}</a> "
        f"<span style='color:#9ca3af;'>({item.published.isoformat()})</span></div>"
        f"<div style='margin:4px 0;'>{_esc(r.summary)}</div>"
        f"<div style='color:#4b5563; font-size:13px;'><em>{_esc(r.stance_rationale)}</em></div>"
        f"{quote_block}"
        "</div>"
    )


def build_html(rated: list[Rated]) -> str:
    today = date.today().isoformat()
    sections: list[str] = []
    for region in config.REGION_ORDER:
        group = [(i, r) for i, r in rated if i.region == region]
        if not group:
            continue
        group.sort(key=lambda pr: abs(pr[1].score), reverse=True)
        entries = "".join(_entry(i, r) for i, r in group)
        sections.append(
            f"<h2 style='font-size:18px; margin:20px 0 8px;'>{region}</h2>{entries}"
        )
    return (
        "<!DOCTYPE html><html><body style='font-family:-apple-system,Segoe UI,"
        "Helvetica,sans-serif; color:#111827; max-width:780px; margin:0 auto; "
        "padding:16px;'>"
        "<h1 style='font-size:20px; margin:0 0 4px;'>Central bank speeches — "
        "daily digest</h1>"
        f"<div style='color:#6b7280; font-size:12px;'>{today}</div>"
        f"{''.join(sections)}"
        "<hr style='margin:24px 0 8px; border:none; border-top:1px solid #e5e5e5;'>"
        "<div style='color:#9ca3af; font-size:11px;'>Sources: bank RSS feeds, "
        "ECB site, and BIS central bankers' speeches. Scores rated by Claude "
        "Sonnet 4.6 (-5 dovish … +5 hawkish).</div>"
        "</body></html>"
    )


def send(html: str, subject: str) -> None:
    secrets = creds_mod.load()
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config.SENDER_EMAIL
    msg["To"] = ", ".join(config.RECIPIENT_EMAILS)
    msg.set_content("This email requires an HTML-capable client.")
    msg.add_alternative(html, subtype="html")

    last_err = None
    for attempt in range(3):
        try:
            with smtplib.SMTP(config.GMAIL_SMTP_HOST, config.GMAIL_SMTP_PORT,
                              timeout=30) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(config.SENDER_EMAIL, secrets["GMAIL_APP_PASSWORD"])
                smtp.send_message(msg)
                log.info("email sent: %s", subject)
                return
        except Exception as e:
            last_err = e
            log.warning("SMTP attempt %d failed: %s", attempt + 1, e)
    raise RuntimeError(f"SMTP send failed after retries: {last_err}")
