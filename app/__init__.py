import os

import click
from dotenv import load_dotenv
from flask import Flask, request, url_for
from flask_login import current_user
from sqlalchemy import text
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash

from .extensions import csrf, db, login_manager
from .models import User


def create_app(test_config=None):
    load_dotenv()

    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.getenv("SECRET_KEY", "development-only-change-me"),
        SQLALCHEMY_DATABASE_URI=_database_url(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=28800,
    )
    if test_config:
        app.config.update(test_config)

    database_url = app.config["SQLALCHEMY_DATABASE_URI"]
    if database_url.startswith("postgresql"):
        app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
            "pool_pre_ping": True,
            "pool_recycle": 300,
            "pool_size": 3,
            "max_overflow": 2,
            "pool_timeout": 30,
        }

    if _is_production() and not app.config.get("TESTING"):
        app.config["SESSION_COOKIE_SECURE"] = True
        app.config["PREFERRED_URL_SCHEME"] = "https"

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please sign in to access the TTBG help desk."
    login_manager.session_protection = "strong"

    from .auth import auth_bp
    from .tickets import tickets_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(tickets_bp)

    @app.before_request
    def require_password_change():
        if not current_user.is_authenticated or not current_user.must_change_password:
            return None
        allowed_endpoints = {
            "auth.change_password",
            "auth.logout",
            "static",
        }
        if request.endpoint not in allowed_endpoints:
            from flask import redirect

            return redirect(url_for("auth.change_password"))
        return None

    @app.get("/healthz")
    def health_check():
        try:
            db.session.execute(text("SELECT 1"))
        except Exception:
            app.logger.exception("Database health check failed.")
            return {"status": "unhealthy"}, 503
        return {"status": "ok"}, 200

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        if request.endpoint != "static":
            response.headers["Cache-Control"] = (
                "no-store, no-cache, must-revalidate, max-age=0"
            )
            response.headers["Pragma"] = "no-cache"
        if _is_production() and not app.config.get("TESTING"):
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response

    @app.errorhandler(403)
    def forbidden(_error):
        from flask import render_template

        return render_template(
            "error.html", code=403, message="You do not have access to this page."
        ), 403

    @app.errorhandler(404)
    def not_found(_error):
        from flask import render_template

        return render_template(
            "error.html", code=404, message="The requested page could not be found."
        ), 404

    @app.cli.command("create-user")
    @click.option("--name", prompt=True)
    @click.option("--email", prompt=True)
    @click.option(
        "--role",
        type=click.Choice(["employee", "admin"]),
        default="employee",
        show_default=True,
    )
    @click.option(
        "--password", prompt=True, hide_input=True, confirmation_prompt=True
    )
    def create_user(name, email, role, password):
        normalized_email = email.strip().lower()
        if len(password) < 12:
            raise click.ClickException("Passwords must contain at least 12 characters.")
        if User.query.filter_by(email=normalized_email).first():
            raise click.ClickException("A user with that email already exists.")
        user = User(
            name=name.strip(),
            email=normalized_email,
            password_hash=generate_password_hash(password),
            role=role,
            active=True,
            must_change_password=True,
        )
        db.session.add(user)
        db.session.commit()
        click.echo(f"Created {role}: {normalized_email}")

    with app.app_context():
        db.create_all()
        _create_environment_admin()

    return app


def _database_url():
    database_url = os.getenv("DATABASE_URL", "sqlite:///ttbg_tickets.db").strip()
    if database_url.startswith("postgresql://"):
        return database_url.replace(
            "postgresql://", "postgresql+psycopg://", 1
        )
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    return database_url


def _is_production():
    return bool(os.getenv("RENDER") or os.getenv("RENDER_EXTERNAL_HOSTNAME"))


def _create_environment_admin():
    email = os.getenv("ADMIN_EMAIL", "").strip().lower()
    password = os.getenv("ADMIN_PASSWORD", "")
    name = os.getenv("ADMIN_NAME", "TTBG Administrator").strip()

    if not email or not password:
        return
    existing = User.query.filter_by(email=email).first()
    if existing:
        return
    if len(password) < 12:
        raise RuntimeError("ADMIN_PASSWORD must contain at least 12 characters.")

    user = User(
        name=name,
        email=email,
        password_hash=generate_password_hash(password),
        role="admin",
        active=True,
        must_change_password=False,
    )
    db.session.add(user)
    db.session.commit()
