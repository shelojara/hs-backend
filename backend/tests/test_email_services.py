from unittest.mock import MagicMock, patch

import pytest

from backend.email_services import (
    GmailSmtpConfig,
    gmail_smtp_config_from_env,
    send_email_via_gmail,
)


def test_gmail_smtp_config_from_env_missing_raises(monkeypatch):
    monkeypatch.delenv("GMAIL_SMTP_USERNAME", raising=False)
    monkeypatch.delenv("GMAIL_SMTP_PASSWORD", raising=False)
    with pytest.raises(ValueError, match="GMAIL_SMTP_USERNAME"):
        gmail_smtp_config_from_env()


def test_gmail_smtp_config_from_env_reads_optional_host_port(monkeypatch):
    monkeypatch.setenv("GMAIL_SMTP_USERNAME", "user@gmail.com")
    monkeypatch.setenv("GMAIL_SMTP_PASSWORD", "secret")
    monkeypatch.setenv("GMAIL_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("GMAIL_SMTP_PORT", "2525")
    cfg = gmail_smtp_config_from_env()
    assert cfg.username == "user@gmail.com"
    assert cfg.password == "secret"
    assert cfg.host == "smtp.example.test"
    assert cfg.port == 2525


@patch("backend.email_services.smtplib.SMTP")
def test_send_email_via_gmail_uses_starttls_and_login(mock_smtp):
    instance = MagicMock()
    mock_smtp.return_value.__enter__.return_value = instance

    cfg = GmailSmtpConfig(username="sender@gmail.com", password="pw")
    send_email_via_gmail(
        to_addrs="a@example.com, b@example.com",
        subject="Hello",
        body="Line one\n",
        cc_addrs=["c@example.com"],
        bcc_addrs="d@example.com",
        reply_to="support@example.com",
        config=cfg,
    )

    mock_smtp.assert_called_once_with("smtp.gmail.com", 587, timeout=30)
    instance.ehlo.assert_called()
    instance.starttls.assert_called_once()
    instance.login.assert_called_once_with("sender@gmail.com", "pw")
    instance.send_message.assert_called_once()
    kwargs = instance.send_message.call_args.kwargs
    assert kwargs["from_addr"] == "sender@gmail.com"
    assert set(kwargs["to_addrs"]) == {
        "a@example.com",
        "b@example.com",
        "c@example.com",
        "d@example.com",
    }
    message = instance.send_message.call_args.args[0]
    assert message["Subject"] == "Hello"
    assert message["From"] == "sender@gmail.com"
    assert message["Reply-To"] == "support@example.com"
    assert message.get_content() == "Line one\n"
