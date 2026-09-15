from urllib.parse import urljoin, urlparse

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db
from .forms import LoginForm, PasswordChangeForm
from .models import User

auth_bp = Blueprint("auth", __name__)


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
        user = User.query.filter_by(email=email, active=True).first()

        if user and check_password_hash(user.password_hash, form.password.data):
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
            flash("Your password has been updated.", "success")
            return redirect(url_for("tickets.dashboard"))

    return render_template("change_password.html", form=form)
