from urllib.parse import urljoin, urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for, session
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db
from .forms import LoginForm, PasswordChangeForm, ForgotPasswordForm, EmailPasswordResetForm
from .password_security import (allow_request, submit_account_email, issue_password_reset,
                                reset_user_for_token, consume_reset)
from .email_service import send_password_changed_email
from .models import User

auth_bp = Blueprint("auth", __name__)
_DUMMY_PASSWORD_HASH = generate_password_hash("unused-timing-equalizer")


def _is_safe_redirect(target):
    host_url = urlparse(request.host_url)
    redirect_url = urlparse(urljoin(request.host_url, target))
    return (
        redirect_url.scheme in ("http", "https")
        and host_url.netloc == redirect_url.netloc
    )


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("tickets.dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        ip_allowed = allow_request("login-ip", request.remote_addr or "unknown", 30, 900)
        email_allowed = ip_allowed and allow_request("login-email", email, 10, 900)
        if not ip_allowed or not email_allowed:
            flash("Too many sign-in attempts. Please try again in 15 minutes.", "error")
            return render_template("login.html", form=form), 429
        user = User.query.filter_by(email=email, active=True).first()

        password_ok = check_password_hash(user.password_hash if user else _DUMMY_PASSWORD_HASH, form.password.data)
        if user and password_ok:
            session.clear()
            login_user(user)
            next_url = request.args.get("next")
            if next_url and _is_safe_redirect(next_url):
                return redirect(next_url)
            return redirect(url_for("tickets.dashboard"))

        flash("The email address or password was incorrect.", "error")

    return render_template("login.html", form=form)


@auth_bp.post("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@auth_bp.route("/account/password", methods=["GET", "POST"])
@login_required
def change_password():
    form = PasswordChangeForm()
    if form.validate_on_submit():
        if not check_password_hash(
            current_user.password_hash, form.current_password.data
        ):
            form.current_password.errors.append("Current password is incorrect.")
        elif check_password_hash(
            current_user.password_hash, form.new_password.data
        ):
            form.new_password.errors.append(
                "Your new password must be different from the current password."
            )
        else:
            current_user.password_hash = generate_password_hash(
                form.new_password.data
            )
            current_user.must_change_password = False
            db.session.commit()
            # Refresh this session; all other password-bound sessions are invalid.
            login_user(current_user._get_current_object())
            submit_account_email(send_password_changed_email, current_user.email)
            flash("Your password has been updated.", "success")
            return redirect(url_for("tickets.dashboard"))

    return render_template("change_password.html", form=form)


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    form = ForgotPasswordForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        # Apply identical limits to known, unknown and inactive account emails.
        ip_ok = allow_request("reset-ip", request.remote_addr or "unknown", 20, 3600)
        email_ok = ip_ok and allow_request("reset-email", email, 3, 3600)
        cooldown_ok = email_ok and allow_request("reset-cooldown", email, 1, 60)
        if ip_ok and email_ok and cooldown_ok:
            submit_account_email(issue_password_reset, email)
        flash("If this email belongs to an active TTBG account, a reset link will arrive shortly. "
              "Check your spam folder. If needed, wait a few minutes before trying again.", "success")
        return redirect(url_for("auth.forgot_password"))
    return render_template("forgot_password.html", form=form)


@auth_bp.route("/reset-password", methods=["GET", "POST"])
def email_reset_password():
    form = EmailPasswordResetForm()
    token = request.form.get("reset_token", "") if request.method == "POST" else ""
    if request.method == "POST":
        if not allow_request("reset-confirm-ip", request.remote_addr or "unknown", 20, 900):
            flash("Too many attempts. Please wait 15 minutes and request a new link.", "error")
            return redirect(url_for("auth.forgot_password"))
        user = reset_user_for_token(token)
        if not user:
            flash("This reset link is invalid or has expired. Please request a new one.", "error")
            return redirect(url_for("auth.forgot_password"))
        if form.validate_on_submit():
            if check_password_hash(user.password_hash, form.new_password.data):
                form.new_password.errors.append("Choose a password different from your current password.")
            else:
                email = user.email
                if consume_reset(token, user, generate_password_hash(form.new_password.data)):
                    logout_user()
                    session.clear()
                    submit_account_email(send_password_changed_email, email)
                    flash("Your password has been reset. Please sign in with your new password.", "success")
                    return redirect(url_for("auth.login"))
                flash("This reset link is invalid or has expired. Please request a new one.", "error")
                return redirect(url_for("auth.forgot_password"))
    return render_template("email_reset_password.html", form=form, reset_token=token)
