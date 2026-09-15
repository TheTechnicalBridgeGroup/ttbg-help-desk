import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

from flask import current_app, url_for

logger = logging.getLogger(__name__)

EVENT_SUBJECTS = {
    "reply": "New reply",
    "assignment": "Assignment update",
    "status": "Status update",
    "priority": "Priority update",
    "internal_note": "Internal note",
}


def send_new_ticket_notification(ticket):
    """Send an optional new-ticket notice to the shared support inbox."""
    if not _support_inbox_email_is_configured():
        current_app.logger.info(
            "%s saved; support inbox email is not configured.", ticket.number
        )
        return False

    recipient = os.getenv("NOTIFICATION_EMAIL", "").strip()
    detail_url = _ticket_url(ticket.id)
    message = EmailMessage()
    message["Subject"] = _clean_header(
        f"[{ticket.priority}] {ticket.number} — {ticket.title}"
    )
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

    return _deliver_safely(message, f"{ticket.number} support inbox")


def send_ticket_created_email(ticket):
    """Confirm ticket creation to the requester's account email."""
    if not _smtp_is_configured():
        current_app.logger.info(
            "%s saved; requester email is not configured.", ticket.number
        )
        return False

    requester = ticket.requester
    message = EmailMessage()
    message["Subject"] = _clean_header(
        f"Ticket received: {ticket.number} — {ticket.title}"
    )
    message["From"] = _sender_address()
    message["To"] = requester.email
    message.set_content(
        "\n".join(
            [
                f"Hi {requester.name},",
                "",
                "Your TTBG help desk ticket has been created.",
                "",
                f"Ticket: {ticket.number}",
                f"Title: {ticket.title}",
                f"Category: {ticket.category}",
                f"Priority: {ticket.priority}",
                f"Status: {ticket.status}",
                (
                    "Assigned to: "
                    f"{ticket.assignee.name if ticket.assignee else 'Unassigned'}"
                ),
                "",
                (
                    "You will receive another email when someone replies or "
                    "the ticket changes."
                ),
                f"View ticket: {_ticket_url(ticket.id)}",
            ]
        )
    )
    return _deliver_safely(message, f"{ticket.number} requester confirmation")


def send_user_notification_email(notification):
    """Email one committed in-app notification to its account owner."""
    if not _smtp_is_configured():
        current_app.logger.info(
            "Notification %s saved; account email is not configured.",
            notification.id,
        )
        return False

    ticket = notification.ticket
    user = notification.user
    subject_label = EVENT_SUBJECTS.get(notification.event_type, "Ticket update")
    message = EmailMessage()
    message["Subject"] = _clean_header(
        f"{subject_label}: {ticket.number} — {ticket.title}"
    )
    message["From"] = _sender_address()
    message["To"] = user.email
    message.set_content(
        "\n".join(
            [
                f"Hi {user.name},",
                "",
                notification.message,
                "",
                f"Ticket: {ticket.number}",
                f"Title: {ticket.title}",
                f"Status: {ticket.status}",
                f"Priority: {ticket.priority}",
                "",
                f"View ticket: {_ticket_url(ticket.id)}",
            ]
        )
    )
    return _deliver_safely(message, f"notification {notification.id}")


def send_user_notification_emails(notifications):
    """Email committed notifications without affecting the ticket workflow."""
    sent_count = 0
    for notification in notifications:
        if notification is not None and send_user_notification_email(notification):
            sent_count += 1
    return sent_count


def _smtp_is_configured():
    return all(
        [
            os.getenv("SMTP_HOST", "").strip(),
            os.getenv("SMTP_USERNAME", "").strip(),
            os.getenv("SMTP_PASSWORD", "").strip(),
        ]
    )


def _support_inbox_email_is_configured():
    return _smtp_is_configured() and bool(
        os.getenv("NOTIFICATION_EMAIL", "").strip()
    )


def _sender_address():
    return (
        os.getenv("SMTP_FROM_EMAIL", "").strip()
        or os.getenv("SMTP_USERNAME", "").strip()
    )


def _clean_header(value):
    """Prevent user-entered line breaks from becoming email headers."""
    return " ".join(str(value).splitlines()).strip()


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


def _deliver_safely(message, context_label):
    try:
        _deliver(message)
    except Exception:
        logger.exception("Email delivery failed for %s.", context_label)
        return False
    return True


def _env_flag(name, default=False):
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}
