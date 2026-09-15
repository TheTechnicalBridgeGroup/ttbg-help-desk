from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Email, EqualTo, Length, Optional


TICKET_CATEGORIES = [
    ("Access Request", "Access request"),
    ("Software Issue", "Software issue"),
    ("Security Concern", "Security concern"),
    ("Development Task", "Development task"),
    ("Other", "Other"),
]

TICKET_PRIORITIES = [
    ("Low", "Low — can wait"),
    ("Medium", "Medium — normal priority"),
    ("High", "High — blocking important work"),
    ("Urgent", "Urgent — security or business critical"),
]

TICKET_STATUSES = [
    ("New", "New"),
    ("In Progress", "In progress"),
    ("Waiting on Requester", "Waiting on requester"),
    ("Resolved", "Resolved"),
    ("Closed", "Closed"),
]


class LoginForm(FlaskForm):
    email = StringField(
        "Work email",
        validators=[DataRequired(), Email(), Length(max=255)],
    )
    password = PasswordField(
        "Password", validators=[DataRequired(), Length(min=8, max=128)]
    )
    submit = SubmitField("Sign in")


class TicketForm(FlaskForm):
    title = StringField(
        "What do you need help with?",
        validators=[DataRequired(), Length(min=5, max=180)],
    )
    category = SelectField(
        "Request type", choices=TICKET_CATEGORIES, validators=[DataRequired()]
    )
    priority = SelectField(
        "Priority", choices=TICKET_PRIORITIES, validators=[DataRequired()]
    )
    assignee_id = SelectField(
        "Assigned to", coerce=int, validators=[Optional()]
    )
    description = TextAreaField(
        "Details",
        validators=[DataRequired(), Length(min=10, max=10000)],
    )
    submit = SubmitField("Submit ticket")


class CommentForm(FlaskForm):
    body = TextAreaField(
        "Add a reply",
        validators=[DataRequired(), Length(min=2, max=5000)],
    )
    is_internal = BooleanField("Internal note — hidden from requester")
    submit = SubmitField("Post reply")


class TicketUpdateForm(FlaskForm):
    status = SelectField(
        "Status", choices=TICKET_STATUSES, validators=[DataRequired()]
    )
    priority = SelectField(
        "Priority", choices=TICKET_PRIORITIES, validators=[DataRequired()]
    )
    assignee_id = SelectField(
        "Assigned to", coerce=int, validators=[Optional()]
    )
    internal_notes = TextAreaField(
        "Admin notes",
        validators=[Optional(), Length(max=10000)],
    )
    submit = SubmitField("Save changes")


class UserCreateForm(FlaskForm):
    name = StringField(
        "Full name", validators=[DataRequired(), Length(min=2, max=120)]
    )
    email = StringField(
        "Work email", validators=[DataRequired(), Email(), Length(max=255)]
    )
    role = SelectField(
        "Access level",
        choices=[("employee", "Coworker"), ("admin", "Administrator")],
        validators=[DataRequired()],
    )
    temporary_password = PasswordField(
        "Temporary password",
        validators=[DataRequired(), Length(min=12, max=128)],
    )
    confirm_password = PasswordField(
        "Confirm password",
        validators=[DataRequired(), EqualTo("temporary_password")],
    )
    submit = SubmitField("Create account")


class PasswordChangeForm(FlaskForm):
    current_password = PasswordField(
        "Current password", validators=[DataRequired(), Length(max=128)]
    )
    new_password = PasswordField(
        "New password",
        validators=[DataRequired(), Length(min=12, max=128)],
    )
    confirm_password = PasswordField(
        "Confirm new password",
        validators=[DataRequired(), EqualTo("new_password")],
    )
    submit = SubmitField("Update password")


class PasswordResetForm(FlaskForm):
    temporary_password = PasswordField(
        "New temporary password",
        validators=[DataRequired(), Length(min=12, max=128)],
    )
    confirm_password = PasswordField(
        "Confirm temporary password",
        validators=[DataRequired(), EqualTo("temporary_password")],
    )
    submit = SubmitField("Reset password")
