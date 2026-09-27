"""Email delivery for account flows (password reset, verification).

Deliberately tiny and pluggable:

- console: structured-logs the message instead of sending. Development
  default, and an honest fallback in production when no provider is
  configured yet (the send site logs a warning so it's visible).
- smtp: stdlib smtplib against any relay, run off the event loop.
- resend: Resend's HTTP API (https://resend.com) via httpx.

Sends are best-effort by design at call sites like signup: a mail outage
must never fail account creation. Flows where the email IS the product
(password reset) surface failures to the caller.
"""

import asyncio
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage as MimeMessage

import httpx

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

log = get_logger("core.email")


@dataclass(frozen=True)
class EmailMessage:
    to: str
    subject: str
    text: str


class EmailSender:
    """Interface. send() raises on delivery failure."""

    async def send(self, message: EmailMessage) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class ConsoleEmailSender(EmailSender):
    """Logs the email. The log line carries everything needed to complete the
    flow by hand in development (the link is in the text)."""

    async def send(self, message: EmailMessage) -> None:
        log.info(
            "email_console_delivery",
            to=message.to,
            subject=message.subject,
            text=message.text,
        )


class SmtpEmailSender(EmailSender):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def _send_sync(self, message: EmailMessage) -> None:
        s = self._settings
        mime = MimeMessage()
        mime["From"] = s.email_from
        mime["To"] = message.to
        mime["Subject"] = message.subject
        mime.set_content(message.text)
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=15) as client:
            if s.smtp_starttls:
                client.starttls()
            if s.smtp_username and s.smtp_password is not None:
                client.login(s.smtp_username, s.smtp_password.get_secret_value())
            client.send_message(mime)

    async def send(self, message: EmailMessage) -> None:
        await asyncio.to_thread(self._send_sync, message)


class ResendEmailSender(EmailSender):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, message: EmailMessage) -> None:
        key = self._settings.resend_api_key
        if key is None:  # validated at startup in production; guard anyway
            raise RuntimeError("RESEND_API_KEY is not configured")
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {key.get_secret_value()}"},
                json={
                    "from": self._settings.email_from,
                    "to": [message.to],
                    "subject": message.subject,
                    "text": message.text,
                },
            )
            resp.raise_for_status()


def get_email_sender(settings: Settings | None = None) -> EmailSender:
    settings = settings or get_settings()
    if settings.email_backend == "smtp":
        return SmtpEmailSender(settings)
    if settings.email_backend == "resend":
        return ResendEmailSender(settings)
    if settings.is_production:
        # Legal to defer configuring email, but it must be visible: password
        # reset emails are going to the server log, not to users.
        log.warning("email_backend_console_in_production")
    return ConsoleEmailSender()
