"""Shared, atomic throttling and short-lived email recovery credentials."""
import hashlib
import hmac
import re
import secrets
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

from flask import current_app
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import AuthRateLimit, PasswordResetToken, User, utc_now

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="account-email")
_slots = threading.BoundedSemaphore(32)


def allow_request(scope, identity, limit, seconds):
    """DB-backed fixed windows; conditional increments remain atomic across workers."""
    now = int(time.time())
    window = now // seconds
    value = f"{scope}:{identity}:{window}"
    key = hmac.new(current_app.secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()
    # Bound retained state without storing email addresses or IPs in these rows.
    db.session.execute(delete(AuthRateLimit).where(AuthRateLimit.expires_at < utc_now()))
    row = AuthRateLimit(key=key, count=0,
                        expires_at=datetime.fromtimestamp((window + 1) * seconds, timezone.utc))
    try:
        with db.session.begin_nested():
            db.session.add(row)
            db.session.flush()
    except IntegrityError:
        pass  # Another request has already created this window.
    result = db.session.execute(update(AuthRateLimit).where(
        AuthRateLimit.key == key, AuthRateLimit.count < limit
    ).values(count=AuthRateLimit.count + 1))
    db.session.commit()
    return result.rowcount == 1


def submit_account_email(callback, *args):
    """Bounded background delivery keeps SMTP/account existence out of response timing.

    A process restart can discard pending mail; callers can request another link.
    No raw tokens are persisted in a mail queue or logged.
    """
    if not _slots.acquire(blocking=False):
        current_app.logger.warning("Account email queue is full; request a new link later.")
        return False
    app = current_app._get_current_object()
    def work():
        try:
            with app.app_context():
                try:
                    callback(*args)
                except Exception:
                    db.session.rollback()
                    # No traceback: database parameters could contain credentials.
                    app.logger.error("Account email processing failed; check service configuration.")
        finally:
            _slots.release()
    try:
        _pool.submit(work)
    except RuntimeError:
        _slots.release()
        return False
    return True


def trusted_reset_url(token):
    base = current_app.config.get("PORTAL_BASE_URL", "").rstrip("/")
    parts = urlsplit(base)
    if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
            or parts.query or parts.fragment or parts.path not in ("", "/")):
        raise ValueError("PORTAL_BASE_URL must be the public HTTPS origin, with no path or query.")
    # Fragments never reach HTTP access logs. JS moves it into the POST form.
    return f"{base}/reset-password#token={token}"


def issue_password_reset(email):
    from .email_service import send_password_reset_email
    user = User.query.filter_by(email=email, active=True).first()
    if not user:
        return
    token = secrets.token_urlsafe(32)
    link = trusted_reset_url(token)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    db.session.execute(delete(PasswordResetToken).where(PasswordResetToken.expires_at < utc_now()))
    db.session.add(PasswordResetToken(
        token_hash=token_hash, user_id=user.id,
        password_fingerprint=user.password_fingerprint(),
        expires_at=utc_now() + timedelta(minutes=15)))
    db.session.commit()
    if not send_password_reset_email(user.email, link):
        db.session.execute(delete(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash))
        db.session.commit()


def reset_user_for_token(token):
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token or ""):
        return None
    record = db.session.get(PasswordResetToken, hashlib.sha256(token.encode()).hexdigest())
    if not record:
        return None
    expiry = record.expires_at
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    user = db.session.get(User, record.user_id)
    if (expiry <= utc_now() or not user or not user.active
            or not hmac.compare_digest(record.password_fingerprint, user.password_fingerprint())):
        return None
    return user


def consume_reset(token, user, new_hash):
    # Claim this token and change the password in ONE transaction. Only one
    # concurrent reset (even with different tokens) can match the old hash.
    claimed = db.session.execute(delete(PasswordResetToken).where(
        PasswordResetToken.token_hash == hashlib.sha256(token.encode()).hexdigest(),
        PasswordResetToken.expires_at > utc_now()))
    if claimed.rowcount != 1:
        db.session.rollback()
        return False
    changed = db.session.execute(update(User).where(
        User.id == user.id, User.password_hash == user.password_hash, User.active.is_(True)
    ).values(password_hash=new_hash, must_change_password=False),
        execution_options={"synchronize_session": False})
    if changed.rowcount != 1:
        db.session.rollback()
        return False
    db.session.execute(delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
    db.session.commit()
    return True
