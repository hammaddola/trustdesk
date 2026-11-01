"""Email adapters: console (dev), SMTP, Resend."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

import anyio
import httpx

from trustdesk_ai.config.settings import Settings
from trustdesk_ai.providers.base import EmailProvider, ProviderError

log = logging.getLogger(__name__)


class ConsoleEmail:
    """Development only: logs that an email would be sent (recipient domain only, never the body)."""

    name = "console"

    async def send(self, to: str, subject: str, body: str, reply_to: str | None = None) -> None:
        log.info("[console email] to=*@%s subject=%r (%d chars)", to.rsplit("@", 1)[-1], subject, len(body))


class SmtpEmail:
    name = "smtp"

    def __init__(self, host: str, port: int, username: str | None, password: str | None, sender: str) -> None:
        self._host, self._port, self._user, self._password, self._from = host, port, username, password, sender

    async def send(self, to: str, subject: str, body: str, reply_to: str | None = None) -> None:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self._from, to, subject
        if reply_to:
            msg["Reply-To"] = reply_to
        msg.set_content(body)

        def deliver() -> None:
            with smtplib.SMTP(self._host, self._port, timeout=20) as smtp:
                smtp.starttls()
                if self._user and self._password:
                    smtp.login(self._user, self._password)
                smtp.send_message(msg)

        try:
            await anyio.to_thread.run_sync(deliver)
        except (smtplib.SMTPException, OSError) as exc:
            raise ProviderError(f"smtp delivery failed: {type(exc).__name__}") from exc


class ResendEmail:
    name = "resend"

    def __init__(self, api_key: str, sender: str) -> None:
        self._headers, self._from = {"Authorization": f"Bearer {api_key}"}, sender

    async def send(self, to: str, subject: str, body: str, reply_to: str | None = None) -> None:
        payload: dict[str, object] = {"from": self._from, "to": [to], "subject": subject, "text": body}
        if reply_to:
            payload["reply_to"] = reply_to
        try:
            async with httpx.AsyncClient(timeout=20, headers=self._headers) as http:
                resp = await http.post("https://api.resend.com/emails", json=payload)
        except httpx.HTTPError as exc:
            raise ProviderError(f"resend unreachable: {type(exc).__name__}") from exc
        if resp.status_code >= 300:
            raise ProviderError(f"resend returned HTTP {resp.status_code}")


def build_email(s: Settings) -> EmailProvider | None:
    """None means email delivery is disabled (console provider in production)."""
    if not s.email_delivery_enabled:
        return None
    sender = s.email_from or "TrustDesk <no-reply@localhost>"
    if s.email_provider == "smtp" and s.smtp_host:
        pw = s.smtp_password.get_secret_value() if s.smtp_password else None
        return SmtpEmail(s.smtp_host, s.smtp_port, s.smtp_username, pw, sender)
    if s.email_provider == "resend" and s.resend_api_key:
        return ResendEmail(s.resend_api_key.get_secret_value(), sender)
    return ConsoleEmail()
