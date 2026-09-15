from datetime import datetime, timezone

from flask_login import UserMixin

from .extensions import db, login_manager


def utc_now():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(40), nullable=False, default="employee")
    active = db.Column(db.Boolean, nullable=False, default=True)
    must_change_password = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now
    )

    requested_tickets = db.relationship(
        "Ticket",
        foreign_keys="Ticket.requester_id",
        back_populates="requester",
    )
    assigned_tickets = db.relationship(
        "Ticket",
        foreign_keys="Ticket.assignee_id",
        back_populates="assignee",
    )
    notifications = db.relationship(
        "Notification",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    @property
    def is_active(self):
        return self.active

    @property
    def is_admin(self):
        return self.role == "admin"


class Ticket(db.Model):
    __tablename__ = "tickets"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(180), nullable=False)
    category = db.Column(db.String(60), nullable=False, index=True)
    description = db.Column(db.Text, nullable=False)
    priority = db.Column(
        db.String(30), nullable=False, default="Medium", index=True
    )
    status = db.Column(
        db.String(40), nullable=False, default="New", index=True
    )
    requester_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    assignee_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=True, index=True
    )
    internal_notes = db.Column(db.Text)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, index=True
    )
    updated_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        index=True,
    )
    resolved_at = db.Column(db.DateTime(timezone=True))

    requester = db.relationship(
        "User", foreign_keys=[requester_id], back_populates="requested_tickets"
    )
    assignee = db.relationship(
        "User", foreign_keys=[assignee_id], back_populates="assigned_tickets"
    )
    comments = db.relationship(
        "TicketComment",
        back_populates="ticket",
        cascade="all, delete-orphan",
        order_by="TicketComment.created_at.asc()",
    )
    notifications = db.relationship(
        "Notification",
        back_populates="ticket",
        cascade="all, delete-orphan",
    )

    @property
    def number(self):
        return f"TTBG-{self.id:05d}"

    @property
    def is_open(self):
        return self.status not in {"Resolved", "Closed"}


class TicketComment(db.Model):
    __tablename__ = "ticket_comments"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(
        db.Integer, db.ForeignKey("tickets.id"), nullable=False, index=True
    )
    author_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    body = db.Column(db.Text, nullable=False)
    is_internal = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now
    )

    ticket = db.relationship("Ticket", back_populates="comments")
    author = db.relationship("User")


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
    )
    ticket_id = db.Column(
        db.Integer, db.ForeignKey("tickets.id"), nullable=False, index=True
    )
    event_type = db.Column(db.String(40), nullable=False, index=True)
    message = db.Column(db.String(300), nullable=False)
    created_at = db.Column(
        db.DateTime(timezone=True), nullable=False, default=utc_now, index=True
    )
    read_at = db.Column(db.DateTime(timezone=True), index=True)

    user = db.relationship("User", back_populates="notifications")
    ticket = db.relationship("Ticket", back_populates="notifications")

    @property
    def is_unread(self):
        return self.read_at is None


@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None
