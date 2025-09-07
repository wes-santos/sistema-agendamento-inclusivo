from __future__ import annotations

import smtplib
from collections.abc import Sequence
from email.message import EmailMessage

from app.core.settings import settings


def _build_message(
    subject: str, to: Sequence[str], html: str, text: str | None = None
) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{settings.MAIL_FROM_NAME} <{settings.MAIL_FROM}>"
    msg["To"] = ", ".join(to)
    if text:
        msg.set_content(text)
        msg.add_alternative(html, subtype="html")
    else:
        # sempre tenha uma parte text por compatibilidade mínima
        msg.set_content("Visualize este e-mail em um cliente compatível com HTML.")
        msg.add_alternative(html, subtype="html")
    return msg


def send_email(
    subject: str, to: Sequence[str], html: str, text: str | None = None
) -> None:
    msg = _build_message(subject, to, html, text)
    if settings.MAIL_TLS:
        with smtplib.SMTP(settings.MAIL_HOST, settings.MAIL_PORT) as s:
            s.starttls()
            if settings.MAIL_USER:
                s.login(settings.MAIL_USER, settings.MAIL_PASS)
            s.send_message(msg)
    else:
        with smtplib.SMTP(settings.MAIL_HOST, settings.MAIL_PORT) as s:
            if settings.MAIL_USER:
                s.login(settings.MAIL_USER, settings.MAIL_PASS)
            s.send_message(msg)
