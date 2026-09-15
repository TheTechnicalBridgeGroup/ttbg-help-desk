import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app, url_for

logger = logging.getLogger(__name__)


def send_new_ticket_notification(ticket):
    """Send an optional notification after the ticket is safely committed."""
    if not _email_is_configured():
        current_app.logger.info(
            "%s saved; email notification is not configured.", ticket.number
        )
        return False

    recipient = os.getenv("NOTIFICATION_EMAIL", "").strip()
    detail_url = _ticket_url(ticket.id)
    message = EmailMessage()
    message["Subject"] = f"[{ticket.priority}] {ticket.number} — {ticket.title}"
    message["From"] = _sender_address()
    message["To"] = recipient
    message.set_content(
        "\n".join(
            [
                "A new TTBG help desk ticket was submitted.",
                "",
                f"Ticket: {ticket.number}",
                f"Requester: {ticket.requester.name}",
                f"Category: {ticket.category}",
                f"Priority: {ticket.priority}",
                f"Title: {ticket.title}",
                "",
                ticket.description,
                "",
                f"Open ticket: {detail_url}",
            ]
        )
    )

    try:
        _deliver(message)
    except Exception:
        logger.exception("%s notification email failed.", ticket.number)
        return False
    return True


def _email_is_configured():
    return all(
        [
            os.getenv("SMTP_HOST", "").strip(),
            os.getenv("SMTP_USERNAME", "").strip(),
            os.getenv("SMTP_PASSWORD", "").strip(),
            os.getenv("NOTIFICATION_EMAIL", "").strip(),
        ]
    )


def _sender_address():
    return (
        os.getenv("SMTP_FROM_EMAIL", "").strip()
        or os.getenv("SMTP_USERNAME", "").strip()
    )


def _ticket_url(ticket_id):
    base_url = os.getenv("PORTAL_BASE_URL", "").strip().rstrip("/")
    if base_url:
        return f"{base_url}/tickets/{ticket_id}"
    return url_for("tickets.ticket_detail", ticket_id=ticket_id, _external=True)


def _deliver(message):
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    use_ssl = _env_flag("SMTP_USE_SSL", default=False)
    use_tls = _env_flag("SMTP_USE_TLS", default=True)
    context = ssl.create_default_context()

    if use_ssl:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=20) as server:
            server.login(username, password)
            server.send_message(message)
        return

    with smtplib.SMTP(host, port, timeout=20) as server:
        server.ehlo()
        if use_tls:
            server.starttls(context=context)
            server.ehlo()
        server.login(username, password)
        server.send_message(message)


def _env_flag(name, default=False):
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}
