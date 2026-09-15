from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_
from werkzeug.security import generate_password_hash

from .email_service import send_new_ticket_notification
from .extensions import db
from .forms import (
    CommentForm,
    TICKET_CATEGORIES,
    TICKET_STATUSES,
    PasswordResetForm,
    TicketForm,
    TicketUpdateForm,
    UserCreateForm,
)
from .models import Notification, Ticket, TicketComment, User

tickets_bp = Blueprint("tickets", __name__)

TERMINAL_STATUSES = {"Resolved", "Closed"}
NOTIFICATION_DROPDOWN_LIMIT = 8
NOTIFICATION_HISTORY_LIMIT = 100


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def _ticket_or_404(ticket_id):
    ticket = db.session.get(Ticket, ticket_id)
    if ticket is None:
        abort(404)
    if not current_user.is_admin and ticket.requester_id != current_user.id:
        abort(404)
    return ticket


def _notification_or_404(notification_id):
    notification = db.session.get(Notification, notification_id)
    if notification is None or notification.user_id != current_user.id:
        abort(404)
    return notification


def _create_notification(user_id, ticket, event_type, message):
    if not user_id or user_id == current_user.id:
        return
    db.session.add(
        Notification(
            user_id=user_id,
            ticket=ticket,
            event_type=event_type,
            message=message,
        )
    )


def _notify_users(user_ids, ticket, event_type, message):
    for user_id in set(user_ids):
        _create_notification(user_id, ticket, event_type, message)


def _safe_next_url(default_endpoint):
    next_url = request.form.get("next", "").strip()
    if next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return url_for(default_endpoint)


@tickets_bp.app_context_processor
def inject_notification_center():
    if not current_user.is_authenticated:
        return {
            "notification_dropdown_items": [],
            "notification_unread_count": 0,
        }

    notification_query = Notification.query.filter_by(user_id=current_user.id)
    return {
        "notification_dropdown_items": notification_query.order_by(
            Notification.created_at.desc()
        )
        .limit(NOTIFICATION_DROPDOWN_LIMIT)
        .all(),
        "notification_unread_count": notification_query.filter(
            Notification.read_at.is_(None)
        ).count(),
    }


def _assignee_choices():
    return [(0, "Unassigned")] + [
        (user.id, user.name)
        for user in User.query.filter_by(active=True, role="admin")
        .order_by(User.name.asc())
        .all()
    ]


def _visible_ticket_query():
    query = Ticket.query
    if not current_user.is_admin:
        query = query.filter_by(requester_id=current_user.id)
    return query


def _render_ticket_queue(*, archived):
    visible_query = _visible_ticket_query()
    if archived:
        base_query = visible_query.filter(Ticket.status.in_(TERMINAL_STATUSES))
        available_statuses = [
            choice for choice in TICKET_STATUSES if choice[0] in TERMINAL_STATUSES
        ]
        summary_cards = [
            ("Closed / resolved", base_query.count(), "accent"),
            ("Resolved", base_query.filter_by(status="Resolved").count(), ""),
            ("Closed", base_query.filter_by(status="Closed").count(), ""),
        ]
        page_title = "Closed / resolved tickets"
        eyebrow = "Completed technology requests"
        description = "Review tickets that have been resolved or closed."
        empty_message = "There are no closed or resolved tickets yet."
    else:
        base_query = visible_query.filter(
            Ticket.status.notin_(TERMINAL_STATUSES)
        )
        available_statuses = [
            choice for choice in TICKET_STATUSES if choice[0] not in TERMINAL_STATUSES
        ]
        summary_cards = [
            ("Active tickets", base_query.count(), "accent"),
            ("New", base_query.filter_by(status="New").count(), ""),
            ("In progress", base_query.filter_by(status="In Progress").count(), ""),
            (
                "Waiting on requester",
                base_query.filter_by(status="Waiting on Requester").count(),
                "",
            ),
        ]
        page_title = (
            "Active tickets" if current_user.is_admin else "My active tickets"
        )
        eyebrow = (
            "Technology queue"
            if current_user.is_admin
            else "My support requests"
        )
        description = (
            "Triage and manage active requests from the TTBG team."
            if current_user.is_admin
            else (
                "Track active requests and reply when the support team needs "
                "more information."
            )
        )
        empty_message = "There are no active support requests."

    ticket_query = base_query
    selected_status = request.args.get("status", "").strip()
    selected_category = request.args.get("category", "").strip()
    search_term = request.args.get("q", "").strip()

    valid_statuses = {value for value, _ in available_statuses}
    valid_categories = {value for value, _ in TICKET_CATEGORIES}
    if selected_status in valid_statuses:
        ticket_query = ticket_query.filter_by(status=selected_status)
    else:
        selected_status = ""
    if selected_category in valid_categories:
        ticket_query = ticket_query.filter_by(category=selected_category)
    else:
        selected_category = ""

    if search_term:
        number_term = search_term.upper().replace("TTBG-", "")
        conditions = [
            Ticket.title.ilike(f"%{search_term}%"),
            Ticket.description.ilike(f"%{search_term}%"),
        ]
        if number_term.isdigit():
            conditions.append(Ticket.id == int(number_term))
        ticket_query = ticket_query.filter(or_(*conditions))

    tickets = ticket_query.order_by(Ticket.updated_at.desc()).all()
    clear_endpoint = "tickets.closed_tickets" if archived else "tickets.dashboard"
    return render_template(
        "dashboard.html",
        tickets=tickets,
        summary_cards=summary_cards,
        statuses=available_statuses,
        categories=TICKET_CATEGORIES,
        selected_status=selected_status,
        selected_category=selected_category,
        search_term=search_term,
        page_title=page_title,
        eyebrow=eyebrow,
        description=description,
        empty_message=empty_message,
        archived=archived,
        clear_endpoint=clear_endpoint,
    )


@tickets_bp.get("/")
@tickets_bp.get("/tickets")
@login_required
def dashboard():
    return _render_ticket_queue(archived=False)


@tickets_bp.get("/tickets/closed")
@login_required
def closed_tickets():
    return _render_ticket_queue(archived=True)


@tickets_bp.route("/tickets/new", methods=["GET", "POST"])
@login_required
def new_ticket():
    form = TicketForm()
    form.assignee_id.choices = _assignee_choices()
    if form.validate_on_submit():
        ticket = Ticket(
            title=form.title.data.strip(),
            category=form.category.data,
            priority=form.priority.data,
            description=form.description.data.strip(),
            requester_id=current_user.id,
            assignee_id=form.assignee_id.data or None,
        )
        db.session.add(ticket)
        db.session.flush()
        if ticket.assignee_id:
            _create_notification(
                ticket.assignee_id,
                ticket,
                "assignment",
                f"{ticket.number} was assigned to you by {current_user.name}.",
            )
        db.session.commit()
        send_new_ticket_notification(ticket)
        flash(f"{ticket.number} was submitted.", "success")
        return redirect(url_for("tickets.ticket_detail", ticket_id=ticket.id))

    return render_template("ticket_form.html", form=form)


@tickets_bp.get("/tickets/<int:ticket_id>")
@login_required
def ticket_detail(ticket_id):
    ticket = _ticket_or_404(ticket_id)
    comment_form = CommentForm()
    update_form = None

    if current_user.is_admin:
        update_form = TicketUpdateForm(obj=ticket)
        update_form.assignee_id.choices = _assignee_choices()
        update_form.assignee_id.data = ticket.assignee_id or 0

    visible_comments = [
        comment
        for comment in ticket.comments
        if current_user.is_admin or not comment.is_internal
    ]
    return render_template(
        "ticket_detail.html",
        ticket=ticket,
        comments=visible_comments,
        comment_form=comment_form,
        update_form=update_form,
    )


@tickets_bp.post("/tickets/<int:ticket_id>/comments")
@login_required
def add_comment(ticket_id):
    ticket = _ticket_or_404(ticket_id)
    form = CommentForm()
    if form.validate_on_submit():
        is_internal = bool(form.is_internal.data and current_user.is_admin)
        comment = TicketComment(
            ticket_id=ticket.id,
            author_id=current_user.id,
            body=form.body.data.strip(),
            is_internal=is_internal,
        )
        ticket.updated_at = datetime.now(timezone.utc)
        db.session.add(comment)

        if is_internal:
            _create_notification(
                ticket.assignee_id,
                ticket,
                "internal_note",
                f"{current_user.name} added an internal note to {ticket.number}.",
            )
        else:
            _notify_users(
                {ticket.requester_id, ticket.assignee_id},
                ticket,
                "reply",
                f"{current_user.name} replied to {ticket.number}.",
            )
        db.session.commit()
        flash("Reply added.", "success")
    else:
        flash("Enter a reply before posting.", "error")
    return redirect(url_for("tickets.ticket_detail", ticket_id=ticket.id))


@tickets_bp.post("/tickets/<int:ticket_id>/update")
@admin_required
def update_ticket(ticket_id):
    ticket = _ticket_or_404(ticket_id)
    form = TicketUpdateForm()
    form.assignee_id.choices = _assignee_choices()

    if not form.validate_on_submit():
        flash("Please review the ticket update fields.", "error")
        return redirect(url_for("tickets.ticket_detail", ticket_id=ticket.id))

    previous_status = ticket.status
    previous_priority = ticket.priority
    previous_assignee_id = ticket.assignee_id
    ticket.status = form.status.data
    ticket.priority = form.priority.data
    ticket.assignee_id = form.assignee_id.data or None
    ticket.internal_notes = (form.internal_notes.data or "").strip() or None

    if (
        ticket.status in TERMINAL_STATUSES
        and previous_status not in TERMINAL_STATUSES
    ):
        ticket.resolved_at = datetime.now(timezone.utc)
    elif ticket.status not in TERMINAL_STATUSES:
        ticket.resolved_at = None

    if ticket.status != previous_status:
        _notify_users(
            {ticket.requester_id, ticket.assignee_id},
            ticket,
            "status",
            (
                f"{current_user.name} changed {ticket.number} from "
                f"{previous_status} to {ticket.status}."
            ),
        )

    if ticket.priority != previous_priority:
        _notify_users(
            {ticket.requester_id, ticket.assignee_id},
            ticket,
            "priority",
            (
                f"{current_user.name} changed {ticket.number} priority from "
                f"{previous_priority} to {ticket.priority}."
            ),
        )

    if ticket.assignee_id != previous_assignee_id:
        if ticket.assignee_id:
            assignee = db.session.get(User, ticket.assignee_id)
            _create_notification(
                ticket.assignee_id,
                ticket,
                "assignment",
                f"{current_user.name} assigned {ticket.number} to you.",
            )
            assignment_message = (
                f"{current_user.name} assigned {ticket.number} to "
                f"{assignee.name}."
            )
        else:
            assignment_message = f"{current_user.name} unassigned {ticket.number}."

        _create_notification(
            ticket.requester_id,
            ticket,
            "assignment",
            assignment_message,
        )
        if previous_assignee_id:
            _create_notification(
                previous_assignee_id,
                ticket,
                "assignment",
                f"{ticket.number} was removed from your assigned queue.",
            )

    db.session.commit()
    flash(f"{ticket.number} was updated.", "success")
    if (
        previous_status not in TERMINAL_STATUSES
        and ticket.status in TERMINAL_STATUSES
    ):
        return redirect(url_for("tickets.closed_tickets"))
    if (
        previous_status in TERMINAL_STATUSES
        and ticket.status not in TERMINAL_STATUSES
    ):
        return redirect(url_for("tickets.dashboard"))
    return redirect(url_for("tickets.ticket_detail", ticket_id=ticket.id))


@tickets_bp.get("/notifications")
@login_required
def notifications():
    notification_items = (
        Notification.query.filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(NOTIFICATION_HISTORY_LIMIT)
        .all()
    )
    return render_template(
        "notifications.html", notification_items=notification_items
    )


@tickets_bp.get("/notifications/feed")
@login_required
def notification_feed():
    notification_query = Notification.query.filter_by(user_id=current_user.id)
    notification_items = (
        notification_query.order_by(Notification.created_at.desc())
        .limit(NOTIFICATION_DROPDOWN_LIMIT)
        .all()
    )
    unread_count = notification_query.filter(
        Notification.read_at.is_(None)
    ).count()
    return {
        "badge_text": "9+" if unread_count > 9 else str(unread_count),
        "html": render_template(
            "_notification_list.html",
            items=notification_items,
            compact=True,
        ),
        "unread_count": unread_count,
    }


@tickets_bp.post("/notifications/<int:notification_id>/open")
@login_required
def open_notification(notification_id):
    notification = _notification_or_404(notification_id)
    _ticket_or_404(notification.ticket_id)
    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
        db.session.commit()
    return redirect(
        url_for("tickets.ticket_detail", ticket_id=notification.ticket_id)
    )


@tickets_bp.post("/notifications/read-all")
@login_required
def read_all_notifications():
    Notification.query.filter_by(user_id=current_user.id).filter(
        Notification.read_at.is_(None)
    ).update(
        {Notification.read_at: datetime.now(timezone.utc)},
        synchronize_session=False,
    )
    db.session.commit()
    return redirect(_safe_next_url("tickets.notifications"))


@tickets_bp.route("/admin/users", methods=["GET", "POST"])
@admin_required
def manage_users():
    form = UserCreateForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if User.query.filter_by(email=email).first():
            form.email.errors.append("An account already uses this email.")
        else:
            user = User(
                name=form.name.data.strip(),
                email=email,
                password_hash=generate_password_hash(form.temporary_password.data),
                role=form.role.data,
                active=True,
                must_change_password=True,
            )
            db.session.add(user)
            db.session.commit()
            flash(f"Account created for {user.name}.", "success")
            return redirect(url_for("tickets.manage_users"))

    users = User.query.order_by(User.active.desc(), User.name.asc()).all()
    return render_template("users.html", form=form, users=users)


@tickets_bp.post("/admin/users/<int:user_id>/toggle")
@admin_required
def toggle_user(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)
    if user.id == current_user.id:
        flash("You cannot deactivate your own account.", "error")
    else:
        user.active = not user.active
        db.session.commit()
        action = "activated" if user.active else "deactivated"
        flash(f"{user.name} was {action}.", "success")
    return redirect(url_for("tickets.manage_users"))


@tickets_bp.route(
    "/admin/users/<int:user_id>/reset-password", methods=["GET", "POST"]
)
@admin_required
def reset_user_password(user_id):
    user = db.session.get(User, user_id)
    if user is None:
        abort(404)

    form = PasswordResetForm()
    if form.validate_on_submit():
        user.password_hash = generate_password_hash(form.temporary_password.data)
        user.must_change_password = True
        user.active = True
        db.session.commit()
        flash(f"Password reset for {user.name}.", "success")
        return redirect(url_for("tickets.manage_users"))

    return render_template("reset_password.html", form=form, user=user)
