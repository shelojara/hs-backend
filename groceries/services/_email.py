"""Gmail send; separate module so tests patch ``groceries.services._email.send_email_via_gmail``."""

from backend.email_services import send_email_via_gmail

__all__ = ["send_email_via_gmail"]
