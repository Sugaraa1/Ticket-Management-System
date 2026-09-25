from django.core import mail
from django.test import TestCase

from apps.tickets.models import Ticket
from apps.tickets.notifications import (
    notify_status_changed,
    notify_ticket_assigned,
    notify_ticket_routed,
)

from .helpers import make_project, make_routed_category, make_user


class NotificationTests(TestCase):
    def setUp(self):
        self.reporter = make_user("reporter", email="reporter@example.com")
        self.lead = make_user("lead", email="lead@example.com")
        self.dev = make_user("dev", email="dev@example.com")
        self.category, self.team = make_routed_category(team_lead=self.lead)
        self.project = make_project()
        self.ticket = Ticket.objects.create(
            title="Bug",
            description="d",
            ticket_type=Ticket.TicketType.BUG,
            category=self.category,
            project=self.project,
            reported_by=self.reporter,
        )
        mail.outbox = []

    def test_notify_ticket_routed_emails_team_lead(self):
        notify_ticket_routed(self.ticket)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.lead.email, mail.outbox[0].to)

    def test_notify_ticket_routed_skips_when_no_team_lead(self):
        self.team.team_lead = None
        self.team.save()
        notify_ticket_routed(self.ticket)
        self.assertEqual(len(mail.outbox), 0)

    def test_notify_ticket_routed_skips_when_no_team(self):
        self.ticket.team = None
        notify_ticket_routed(self.ticket)
        self.assertEqual(len(mail.outbox), 0)

    def test_notify_ticket_assigned_emails_assignee(self):
        self.ticket.assigned_to = self.dev
        notify_ticket_assigned(self.ticket, changed_by=self.reporter)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.dev.email, mail.outbox[0].to)

    def test_notify_ticket_assigned_excludes_actor(self):
        self.ticket.assigned_to = self.reporter
        notify_ticket_assigned(self.ticket, changed_by=self.reporter)
        self.assertEqual(len(mail.outbox), 0)

    def test_notify_ticket_assigned_skips_when_no_assignee(self):
        notify_ticket_assigned(self.ticket, changed_by=self.reporter)
        self.assertEqual(len(mail.outbox), 0)

    def test_in_progress_sends_no_mail(self):
        self.ticket.assigned_to = self.dev
        notify_status_changed(self.ticket, "assigned", "in_progress", changed_by=self.dev)
        self.assertEqual(len(mail.outbox), 0)

    def test_notify_status_changed_skips_when_no_recipients_have_email(self):
        no_email_user = make_user("noemail")
        self.ticket.reported_by = no_email_user
        self.ticket.assigned_to = None
        notify_status_changed(self.ticket, "new", "assigned", changed_by=no_email_user)
        self.assertEqual(len(mail.outbox), 0)


class NotificationSchemeTests(TestCase):
    """Мэйл дараагийн алхмыг хийх хүнд очно; мэдээлэгч зөвхөн эцсийн үр дүнг авна."""

    def setUp(self):
        from apps.tickets.permissions import ROLE_DEV, ROLE_PM, ROLE_QA

        def user(name, role):
            u = make_user(name, role)
            u.email = f"{name}@example.com"
            u.save()
            return u

        self.reporter, self.dev = user("rep", ROLE_DEV), user("dev", ROLE_DEV)
        self.lead, self.qa = user("lead", ROLE_PM), user("qa", ROLE_QA)
        category, self.team = make_routed_category(team_lead=self.lead, qa_tester=self.qa, members=[self.dev])
        self.ticket = Ticket.objects.create(
            title="Login", description="d", ticket_type="bug", category=category,
            project=make_project(), reported_by=self.reporter, assigned_to=self.dev,
        )

    def _to(self, to_status, actor):
        mail.outbox.clear()
        notify_status_changed(self.ticket, "x", to_status, changed_by=actor)
        return sorted(address for m in mail.outbox for address in m.to)

    def test_scheme(self):
        self.assertEqual(self._to("in_progress", self.dev), [])
        self.assertEqual(self._to("resolved", self.dev), [])
        self.assertEqual(self._to("qa_test", self.dev), ["qa@example.com"])
        self.assertEqual(self._to("reopened", self.qa), ["dev@example.com", "lead@example.com"])
        self.assertEqual(self._to("closed", self.qa), ["lead@example.com", "rep@example.com"])
        self.assertEqual(self._to("rejected", self.lead), ["rep@example.com"])

    def test_qa_mail_falls_back_to_lead_when_team_has_no_qa(self):
        self.team.qa_tester = None
        self.team.save()
        self.assertEqual(self._to("qa_test", self.dev), ["lead@example.com"])

    def test_mail_contains_ticket_link(self):
        self._to("qa_test", self.dev)
        self.assertIn(f"/tickets/{self.ticket.pk}/", mail.outbox[0].body)

    def test_creating_ticket_does_not_mail_reporter(self):
        self.client.force_login(self.reporter)
        mail.outbox.clear()
        from django.urls import reverse

        self.client.post(reverse("tickets:ticket_create"), {
            "title": "New", "ticket_type": "bug", "priority": "medium",
            "category": self.ticket.category_id, "project": self.ticket.project_id, "description": "d",
        })
        recipients = [address for m in mail.outbox for address in m.to]
        self.assertEqual(recipients, ["lead@example.com"])

    def test_send_failure_is_logged_not_raised(self):
        from unittest import mock

        with mock.patch("apps.tickets.notifications._django_send_mail", side_effect=OSError("smtp down")):
            with self.assertLogs("apps.tickets.notifications", level="ERROR"):
                self._to("qa_test", self.dev)
