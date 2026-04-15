"""Send outbound mail through Gmail SMTP (app password or SMTP relay credentials)."""

from __future__ import annotations

import os
import smtplib
import ssl
from collections.abc import Sequence
from email.message import EmailMessage

__all__ = [
    "GmailSmtpConfig",
    "gmail_smtp_config_from_env",
    "send_email_via_gmail",
]

GMAIL_SMTP_HOST_DEFAULT = "smtp.gmail.com"
GMAIL_SMTP_PORT_DEFAULT = 587


class GmailSmtpConfig:
    """Connection and auth parameters for Gmail SMTP over STARTTLS."""

    def __init__(
        self,
        *,
        username: str,
        password: str,
        host: str = GMAIL_SMTP_HOST_DEFAULT,
        port: int = GMAIL_SMTP_PORT_DEFAULT,
    ) -> None:
        self.username = username
        self.password = password
        self.host = host
        self.port = port


def gmail_smtp_config_from_env(
    *,
    username_var: str = "GMAIL_SMTP_USERNAME",
    password_var: str = "GMAIL_SMTP_PASSWORD",
    host_var: str = "GMAIL_SMTP_HOST",
    port_var: str = "GMAIL_SMTP_PORT",
) -> GmailSmtpConfig:
    """Load :class:`GmailSmtpConfig` from environment variables.

    Expected variables:
    - ``GMAIL_SMTP_USERNAME``: full Gmail address used to authenticate.
    - ``GMAIL_SMTP_PASSWORD``: app password (recommended) or account password if allowed.
    - ``GMAIL_SMTP_HOST`` / ``GMAIL_SMTP_PORT`` (optional; default ``smtp.gmail.com`` / ``587``).
    """
    username = os.getenv(username_var, "").strip()
    password = os.getenv(password_var, "").strip()
    if not username or not password:
        msg = (
            f"Missing {username_var} or {password_var} in environment; "
            "both are required to send mail through Gmail SMTP."
        )
        raise ValueError(msg)

    host = os.getenv(host_var, GMAIL_SMTP_HOST_DEFAULT).strip() or GMAIL_SMTP_HOST_DEFAULT
    port_raw = os.getenv(port_var, "").strip()
    port = int(port_raw) if port_raw else GMAIL_SMTP_PORT_DEFAULT
    return GmailSmtpConfig(username=username, password=password, host=host, port=port)


def send_email_via_gmail(
    *,
    to_addrs: str | Sequence[str],
    subject: str,
    body: str,
    from_addr: str | None = None,
    cc_addrs: str | Sequence[str] | None = None,
    bcc_addrs: str | Sequence[str] | None = None,
    reply_to: str | None = None,
    config: GmailSmtpConfig | None = None,
) -> None:
    """Send a plain-text email through Gmail using SMTP AUTH + STARTTLS.

    If ``config`` is omitted, values are read via :func:`gmail_smtp_config_from_env`.
    ``from_addr`` defaults to the SMTP username when omitted.
    """
    cfg = config or gmail_smtp_config_from_env()
    sender = (from_addr or cfg.username).strip()
    recipients = _normalize_recipients(to_addrs)
    if not recipients:
        raise ValueError("At least one recipient address is required in to_addrs.")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    if cc_addrs:
        cc = _normalize_recipients(cc_addrs)
        if cc:
            message["Cc"] = ", ".join(cc)
    if reply_to:
        message["Reply-To"] = reply_to.strip()
    message.set_content(body)

    envelope_to = list(recipients)
    if cc_addrs:
        envelope_to.extend(_normalize_recipients(cc_addrs))
    if bcc_addrs:
        envelope_to.extend(_normalize_recipients(bcc_addrs))
    envelope_to = list(dict.fromkeys(envelope_to))

    context = ssl.create_default_context()
    with smtplib.SMTP(cfg.host, cfg.port, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls(context=context)
        smtp.ehlo()
        smtp.login(cfg.username, cfg.password)
        smtp.send_message(message, from_addr=sender, to_addrs=envelope_to)


def _normalize_recipients(value: str | Sequence[str]) -> list[str]:
    if isinstance(value, str):
        parts = [p.strip() for p in value.replace(";", ",").split(",")]
        return [p for p in parts if p]
    return [str(p).strip() for p in value if str(p).strip()]
