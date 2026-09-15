import os
import unittest
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from app import create_app
from app.extensions import db
from app.models import Notification, Ticket, User


class HelpDeskTestCase(unittest.TestCase):
    def setUp(self):
        self.email_env_patcher = patch.dict(
            os.environ,
            {
                "SMTP_HOST": "",
                "SMTP_USERNAME": "",
                "SMTP_PASSWORD": "",
                "NOTIFICATION_EMAIL": "",
            },
        )
        self.email_env_patcher.start()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:",
                "WTF_CSRF_ENABLED": False,
            }
        )
        self.client = self.app.test_client()
        with self.app.app_context():
            self.admin = User(
                name="Kedric Admin",
                email="admin@example.com",
                password_hash=generate_password_hash("AdminPassword123!"),
                role="admin",
                active=True,
                must_change_password=False,
            )
            self.employee = User(
                name="Team Member",
                email="member@example.com",
                password_hash=generate_password_hash("MemberPassword123!"),
                role="employee",
                active=True,
                must_change_password=False,
            )
            self.other_employee = User(
                name="Other Member",
                email="other@example.com",
                password_hash=generate_password_hash("OtherPassword123!"),
                role="employee",
                active=True,
                must_change_password=False,
            )
            db.session.add_all(
                [self.admin, self.employee, self.other_employee]
            )
            db.session.commit()
            self.admin_id = self.admin.id
            self.employee_id = self.employee.id
            self.other_employee_id = self.other_employee.id

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
        self.email_env_patcher.stop()

    def login(self, email, password):
        return self.client.post(
            "/login",
            data={"email": email, "password": password},
            follow_redirects=True,
        )

    def logout(self):
        with self.client.session_transaction() as session:
            session.clear()

    def create_ticket(
        self,
        requester_id,
        title="Need dashboard access",
        status="New",
        assignee_id=None,
    ):
        with self.app.app_context():
            ticket = Ticket(
                title=title,
                category="Access Request",
                description="Please provide access to the mentor dashboard.",
                priority="Medium",
                status=status,
                requester_id=requester_id,
                assignee_id=assignee_id,
            )
            db.session.add(ticket)
            db.session.commit()
            return ticket.id

    def create_notification(
        self,
        user_id,
        ticket_id,
        message="A ticket was updated.",
        event_type="status",
    ):
        with self.app.app_context():
            notification = Notification(
                user_id=user_id,
                ticket_id=ticket_id,
                event_type=event_type,
                message=message,
            )
            db.session.add(notification)
            db.session.commit()
            return notification.id

    def test_all_human_pages_require_login(self):
        for path in [
            "/",
            "/tickets",
            "/tickets/closed",
            "/tickets/new",
            "/notifications",
            "/admin/users",
        ]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 302)
            self.assertIn("/login", response.location)

        response = self.client.get("/healthz")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"status": "ok"})

    def test_employee_can_submit_and_view_ticket(self):
        self.login("member@example.com", "MemberPassword123!")
        response = self.client.post(
            "/tickets/new",
            data={
                "title": "Cannot open scheduling software",
                "category": "Software Issue",
                "priority": "High",
                "description": "The scheduling page shows an error after I sign in.",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"TTBG-00001", response.data)
        self.assertIn(b"Cannot open scheduling software", response.data)

    def test_ticket_creation_confirmation_uses_requester_account_email(self):
        self.login("member@example.com", "MemberPassword123!")
        email_environment = {
            "PORTAL_BASE_URL": "https://ttbg-help-desk.onrender.com",
            "SMTP_HOST": "smtp.example.com",
            "SMTP_USERNAME": "notifications@example.com",
            "SMTP_PASSWORD": "test-app-password",
            "SMTP_FROM_EMAIL": "notifications@example.com",
            "NOTIFICATION_EMAIL": "",
        }

        with patch.dict(os.environ, email_environment), patch(
            "app.email_service._deliver"
        ) as deliver:
            response = self.client.post(
                "/tickets/new",
                data={
                    "title": "Email confirmation request",
                    "category": "Other",
                    "priority": "Medium",
                    "description": "Please confirm this request by email.",
                },
                follow_redirects=True,
            )

        self.assertEqual(response.status_code, 200)
        deliver.assert_called_once()
        email_message = deliver.call_args.args[0]
        self.assertEqual(email_message["To"], "member@example.com")
        self.assertIn("Ticket received: TTBG-00001", email_message["Subject"])
        self.assertIn(
            "https://ttbg-help-desk.onrender.com/tickets/1",
            email_message.get_content(),
        )

    def test_public_reply_emails_the_notification_owner(self):
        ticket_id = self.create_ticket(
            self.employee_id,
            title="Reply email request",
            assignee_id=self.admin_id,
        )
        self.login("admin@example.com", "AdminPassword123!")
        email_environment = {
            "PORTAL_BASE_URL": "https://ttbg-help-desk.onrender.com",
            "SMTP_HOST": "smtp.example.com",
            "SMTP_USERNAME": "notifications@example.com",
            "SMTP_PASSWORD": "test-app-password",
            "SMTP_FROM_EMAIL": "notifications@example.com",
        }

        with patch.dict(os.environ, email_environment), patch(
            "app.email_service._deliver"
        ) as deliver:
            response = self.client.post(
                f"/tickets/{ticket_id}/comments",
                data={"body": "Your access is ready."},
            )

        self.assertEqual(response.status_code, 302)
        deliver.assert_called_once()
        email_message = deliver.call_args.args[0]
        self.assertEqual(email_message["To"], "member@example.com")
        self.assertIn("New reply: TTBG-00001", email_message["Subject"])
        self.assertIn("Kedric Admin replied", email_message.get_content())

    def test_internal_note_email_goes_only_to_assigned_staff(self):
        with self.app.app_context():
            other_admin = db.session.get(User, self.other_employee_id)
            other_admin.role = "admin"
            db.session.commit()
        ticket_id = self.create_ticket(
            self.employee_id,
            title="Private internal note",
            assignee_id=self.other_employee_id,
        )
        self.login("admin@example.com", "AdminPassword123!")
        email_environment = {
            "PORTAL_BASE_URL": "https://ttbg-help-desk.onrender.com",
            "SMTP_HOST": "smtp.example.com",
            "SMTP_USERNAME": "notifications@example.com",
            "SMTP_PASSWORD": "test-app-password",
            "SMTP_FROM_EMAIL": "notifications@example.com",
        }

        with patch.dict(os.environ, email_environment), patch(
            "app.email_service._deliver"
        ) as deliver:
            response = self.client.post(
                f"/tickets/{ticket_id}/comments",
                data={
                    "body": "Requester must not receive this.",
                    "is_internal": "y",
                },
            )

        self.assertEqual(response.status_code, 302)
        deliver.assert_called_once()
        email_message = deliver.call_args.args[0]
        self.assertEqual(email_message["To"], "other@example.com")
        self.assertIn("Internal note: TTBG-00001", email_message["Subject"])

    def test_status_priority_and_assignment_each_send_account_email(self):
        ticket_id = self.create_ticket(
            self.employee_id,
            title="Multiple email updates",
        )
        self.login("admin@example.com", "AdminPassword123!")
        email_environment = {
            "PORTAL_BASE_URL": "https://ttbg-help-desk.onrender.com",
            "SMTP_HOST": "smtp.example.com",
            "SMTP_USERNAME": "notifications@example.com",
            "SMTP_PASSWORD": "test-app-password",
            "SMTP_FROM_EMAIL": "notifications@example.com",
        }

        with patch.dict(os.environ, email_environment), patch(
            "app.email_service._deliver"
        ) as deliver:
            response = self.client.post(
                f"/tickets/{ticket_id}/update",
                data={
                    "status": "In Progress",
                    "priority": "High",
                    "assignee_id": self.admin_id,
                    "internal_notes": "Starting work.",
                },
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(deliver.call_count, 3)
        messages = [call.args[0] for call in deliver.call_args_list]
        self.assertEqual(
            {message["To"] for message in messages}, {"member@example.com"}
        )
        subject_prefixes = {
            message["Subject"].split(":", 1)[0] for message in messages
        }
        self.assertEqual(
            subject_prefixes,
            {"Status update", "Priority update", "Assignment update"},
        )

    def test_email_failure_does_not_roll_back_ticket_creation(self):
        self.login("member@example.com", "MemberPassword123!")
        email_environment = {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_USERNAME": "notifications@example.com",
            "SMTP_PASSWORD": "test-app-password",
            "SMTP_FROM_EMAIL": "notifications@example.com",
        }

        with self.assertLogs("app.email_service", level="ERROR"):
            with patch.dict(os.environ, email_environment), patch(
                "app.email_service._deliver",
                side_effect=OSError("mail unavailable"),
            ):
                response = self.client.post(
                    "/tickets/new",
                    data={
                        "title": "Ticket survives email outage",
                        "category": "Other",
                        "priority": "Low",
                        "description": "This ticket must remain committed.",
                    },
                    follow_redirects=True,
                )

        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            ticket = Ticket.query.filter_by(
                title="Ticket survives email outage"
            ).one()
            self.assertEqual(ticket.requester_id, self.employee_id)

    def test_employee_can_assign_ticket_during_submission(self):
        self.login("member@example.com", "MemberPassword123!")
        response = self.client.post(
            "/tickets/new",
            data={
                "title": "Assign this request now",
                "category": "Development Task",
                "priority": "Medium",
                "assignee_id": self.admin_id,
                "description": "Please assign this development request immediately.",
            },
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Kedric Admin", response.data)
        with self.app.app_context():
            ticket = Ticket.query.filter_by(title="Assign this request now").one()
            self.assertEqual(ticket.assignee_id, self.admin_id)
            notification = Notification.query.filter_by(
                user_id=self.admin_id,
                ticket_id=ticket.id,
                event_type="assignment",
            ).one()
            self.assertIn("assigned to you", notification.message)

    def test_submission_rejects_non_admin_assignee(self):
        self.login("member@example.com", "MemberPassword123!")
        response = self.client.post(
            "/tickets/new",
            data={
                "title": "Invalid assignee request",
                "category": "Other",
                "priority": "Low",
                "assignee_id": self.other_employee_id,
                "description": (
                    "This submission must reject a non-administrator assignee."
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertIsNone(
                Ticket.query.filter_by(title="Invalid assignee request").first()
            )

    def test_employee_cannot_view_another_requesters_ticket(self):
        ticket_id = self.create_ticket(
            self.other_employee_id, title="Other employee private ticket"
        )
        self.login("member@example.com", "MemberPassword123!")

        response = self.client.get(f"/tickets/{ticket_id}")
        self.assertEqual(response.status_code, 404)
        dashboard = self.client.get("/tickets")
        self.assertNotIn(b"Other employee private ticket", dashboard.data)

    def test_admin_can_update_every_ticket(self):
        ticket_id = self.create_ticket(self.employee_id)
        self.login("admin@example.com", "AdminPassword123!")

        response = self.client.post(
            f"/tickets/{ticket_id}/update",
            data={
                "status": "In Progress",
                "priority": "High",
                "assignee_id": self.admin_id,
                "internal_notes": "Investigating access group membership.",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"In Progress", response.data)
        self.assertIn(b"Kedric Admin", response.data)

        with self.app.app_context():
            ticket = db.session.get(Ticket, ticket_id)
            self.assertEqual(ticket.status, "In Progress")
            self.assertEqual(ticket.assignee_id, self.admin_id)

    def test_closed_and_resolved_tickets_move_to_separate_queue(self):
        active_id = self.create_ticket(self.employee_id, title="Active request")
        closed_id = self.create_ticket(
            self.employee_id, title="Closed request", status="Closed"
        )
        resolved_id = self.create_ticket(
            self.employee_id, title="Resolved request", status="Resolved"
        )
        self.login("admin@example.com", "AdminPassword123!")

        active_queue = self.client.get("/tickets")
        self.assertIn(b"Active request", active_queue.data)
        self.assertNotIn(b"Closed request", active_queue.data)
        self.assertNotIn(b"Resolved request", active_queue.data)

        closed_queue = self.client.get("/tickets/closed")
        self.assertNotIn(b"Active request", closed_queue.data)
        self.assertIn(b"Closed request", closed_queue.data)
        self.assertIn(b"Resolved request", closed_queue.data)

        response = self.client.post(
            f"/tickets/{active_id}/update",
            data={
                "status": "Closed",
                "priority": "Medium",
                "assignee_id": self.admin_id,
                "internal_notes": "Work complete.",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/tickets/closed"))

        active_queue = self.client.get("/tickets")
        closed_queue = self.client.get("/tickets/closed")
        self.assertNotIn(b"Active request", active_queue.data)
        self.assertIn(b"Active request", closed_queue.data)
        with self.app.app_context():
            self.assertIsNotNone(db.session.get(Ticket, active_id).resolved_at)
            self.assertEqual(db.session.get(Ticket, closed_id).status, "Closed")
            self.assertEqual(db.session.get(Ticket, resolved_id).status, "Resolved")

    def test_employee_closed_queue_contains_only_own_tickets(self):
        self.create_ticket(
            self.employee_id, title="My resolved request", status="Resolved"
        )
        self.create_ticket(
            self.other_employee_id, title="Private closed request", status="Closed"
        )
        self.login("member@example.com", "MemberPassword123!")

        response = self.client.get("/tickets/closed")
        self.assertIn(b"My resolved request", response.data)
        self.assertNotIn(b"Private closed request", response.data)

    def test_reopened_ticket_returns_to_active_queue(self):
        ticket_id = self.create_ticket(
            self.employee_id, title="Reopened request", status="Resolved"
        )
        self.login("admin@example.com", "AdminPassword123!")

        response = self.client.post(
            f"/tickets/{ticket_id}/update",
            data={
                "status": "In Progress",
                "priority": "Medium",
                "assignee_id": self.admin_id,
                "internal_notes": "More work is required.",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/tickets"))
        self.assertIn(b"Reopened request", self.client.get("/tickets").data)
        self.assertNotIn(
            b"Reopened request", self.client.get("/tickets/closed").data
        )

        with self.app.app_context():
            ticket = db.session.get(Ticket, ticket_id)
            self.assertEqual(ticket.status, "In Progress")
            self.assertIsNone(ticket.resolved_at)

    def test_internal_comments_are_hidden_from_requester(self):
        ticket_id = self.create_ticket(self.employee_id)
        self.login("admin@example.com", "AdminPassword123!")
        self.client.post(
            f"/tickets/{ticket_id}/comments",
            data={"body": "Private security investigation.", "is_internal": "y"},
        )
        self.client.post(
            f"/tickets/{ticket_id}/comments",
            data={"body": "We are reviewing your request."},
        )
        self.logout()

        self.login("member@example.com", "MemberPassword123!")
        response = self.client.get(f"/tickets/{ticket_id}")
        self.assertNotIn(b"Private security investigation", response.data)
        self.assertIn(b"We are reviewing your request", response.data)
        with self.app.app_context():
            requester_notifications = Notification.query.filter_by(
                user_id=self.employee_id,
                ticket_id=ticket_id,
            ).all()
            self.assertEqual(len(requester_notifications), 1)
            self.assertEqual(requester_notifications[0].event_type, "reply")

    def test_requester_reply_notifies_assignee(self):
        ticket_id = self.create_ticket(
            self.employee_id,
            title="Assigned conversation",
            assignee_id=self.admin_id,
        )
        self.login("member@example.com", "MemberPassword123!")
        self.client.post(
            f"/tickets/{ticket_id}/comments",
            data={"body": "Here is the additional information you requested."},
        )

        with self.app.app_context():
            notification = Notification.query.filter_by(
                user_id=self.admin_id,
                ticket_id=ticket_id,
                event_type="reply",
            ).one()
            self.assertIn("Team Member replied", notification.message)

    def test_status_and_priority_changes_notify_requester(self):
        ticket_id = self.create_ticket(self.employee_id, title="Tracked change")
        self.login("admin@example.com", "AdminPassword123!")
        self.client.post(
            f"/tickets/{ticket_id}/update",
            data={
                "status": "In Progress",
                "priority": "High",
                "assignee_id": self.admin_id,
                "internal_notes": "Starting work.",
            },
        )

        with self.app.app_context():
            event_types = {
                notification.event_type
                for notification in Notification.query.filter_by(
                    user_id=self.employee_id,
                    ticket_id=ticket_id,
                ).all()
            }
            self.assertEqual(event_types, {"status", "priority", "assignment"})

    def test_notification_badge_caps_at_nine_plus_and_mark_all_read(self):
        ticket_id = self.create_ticket(self.employee_id)
        for number in range(10):
            self.create_notification(
                self.employee_id,
                ticket_id,
                message=f"Notification {number}",
            )
        self.login("member@example.com", "MemberPassword123!")

        dashboard = self.client.get("/tickets")
        self.assertIn(b"notification-badge", dashboard.data)
        self.assertIn(b">9+<", dashboard.data)

        feed = self.client.get("/notifications/feed")
        self.assertEqual(feed.status_code, 200)
        self.assertEqual(feed.json["unread_count"], 10)
        self.assertEqual(feed.json["badge_text"], "9+")
        self.assertIn("Notification 9", feed.json["html"])

        response = self.client.post(
            "/notifications/read-all",
            data={"next": "/tickets"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/tickets"))
        with self.app.app_context():
            unread_count = Notification.query.filter_by(
                user_id=self.employee_id,
                read_at=None,
            ).count()
            self.assertEqual(unread_count, 0)

    def test_opening_notification_marks_it_read_and_opens_ticket(self):
        ticket_id = self.create_ticket(self.employee_id)
        notification_id = self.create_notification(
            self.employee_id,
            ticket_id,
            message="Your ticket status changed.",
        )
        self.login("member@example.com", "MemberPassword123!")

        response = self.client.post(
            f"/notifications/{notification_id}/open"
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith(f"/tickets/{ticket_id}"))
        with self.app.app_context():
            notification = db.session.get(Notification, notification_id)
            self.assertIsNotNone(notification.read_at)

    def test_user_cannot_open_another_users_notification(self):
        ticket_id = self.create_ticket(self.other_employee_id)
        notification_id = self.create_notification(
            self.other_employee_id,
            ticket_id,
        )
        self.login("member@example.com", "MemberPassword123!")

        response = self.client.post(
            f"/notifications/{notification_id}/open"
        )
        self.assertEqual(response.status_code, 404)

    def test_admin_created_account_must_change_password(self):
        self.login("admin@example.com", "AdminPassword123!")
        response = self.client.post(
            "/admin/users",
            data={
                "name": "New Coworker",
                "email": "new@example.com",
                "role": "employee",
                "temporary_password": "TemporaryPass123!",
                "confirm_password": "TemporaryPass123!",
            },
            follow_redirects=True,
        )
        self.assertIn(b"Account created for New Coworker", response.data)
        self.logout()

        response = self.client.post(
            "/login",
            data={
                "email": "new@example.com",
                "password": "TemporaryPass123!",
            },
        )
        self.assertEqual(response.status_code, 302)
        dashboard = self.client.get("/tickets")
        self.assertEqual(dashboard.status_code, 302)
        self.assertIn("/account/password", dashboard.location)


if __name__ == "__main__":
    unittest.main()
