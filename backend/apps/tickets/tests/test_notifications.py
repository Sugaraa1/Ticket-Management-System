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

    def test_notify_status_changed_emails_reporter_and_assignee_excluding_actor(self):
        self.ticket.assigned_to = self.dev
        notify_status_changed(self.ticket, "assigned", "in_progress", changed_by=self.dev)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(set(mail.outbox[0].to), {self.reporter.email})

    def test_notify_status_changed_skips_when_no_recipients_have_email(self):
        no_email_user = make_user("noemail")
        self.ticket.reported_by = no_email_user
        self.ticket.assigned_to = None
        notify_status_changed(self.ticket, "new", "assigned", changed_by=no_email_user)
        self.assertEqual(len(mail.outbox), 0)
