from datetime import timedelta

from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.tickets.models import Ticket
from apps.tickets.permissions import ROLE_DEV, ROLE_PM

from .helpers import make_project, make_routed_category, make_user


class FirstResponseMarkingTests(TestCase):
    def setUp(self):
        self.reporter = make_user("reporter")
        self.dev = make_user("dev")
        self.category, self.team = make_routed_category()
        self.project = make_project()
        self.ticket = Ticket.objects.create(
            title="X",
            description="d",
            ticket_type=Ticket.TicketType.BUG,
            category=self.category,
            project=self.project,
            reported_by=self.reporter,
        )

    def test_first_response_due_at_set_on_create(self):
        self.assertIsNotNone(self.ticket.first_response_due_at)
        self.assertIsNone(self.ticket.first_responded_at)

    def test_transition_away_from_new_marks_first_response(self):
        self.assertIsNone(self.ticket.first_responded_at)
        self.ticket.transition_to(Ticket.Status.ASSIGNED, user=self.reporter)
        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.first_responded_at)

    def test_comment_by_non_reporter_marks_first_response(self):
        self.ticket.mark_first_response()
        self.assertIsNotNone(self.ticket.first_responded_at)

    def test_mark_first_response_is_idempotent(self):
        self.ticket.mark_first_response()
        first_value = self.ticket.first_responded_at
        self.ticket.mark_first_response(when=timezone.now() + timedelta(hours=1))
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.first_responded_at, first_value)

    def test_comment_view_by_reporter_does_not_mark_first_response(self):
        self.client.force_login(self.reporter)
        self.client.post(
            reverse("tickets:ticket_detail", args=[self.ticket.pk]),
            {"action": "comment", "body": "follow up", "is_internal": False},
        )
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.first_responded_at)

    def test_comment_view_by_other_user_marks_first_response(self):
        self.client.force_login(self.dev)
        self.client.post(
            reverse("tickets:ticket_detail", args=[self.ticket.pk]),
            {"action": "comment", "body": "on it", "is_internal": False},
        )
        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.first_responded_at)


class SlaPropertyTests(TestCase):
    def setUp(self):
        self.reporter = make_user("reporter")
        self.category, self.team = make_routed_category()
        self.project = make_project()
        self.ticket = Ticket.objects.create(
            title="X",
            description="d",
            ticket_type=Ticket.TicketType.BUG,
            category=self.category,
            project=self.project,
            reported_by=self.reporter,
        )

    def test_is_first_response_overdue_false_once_responded(self):
        self.ticket.first_response_due_at = timezone.now() - timedelta(hours=1)
        self.ticket.first_responded_at = timezone.now()
        self.assertFalse(self.ticket.is_first_response_overdue)

    def test_is_first_response_overdue_true_when_past_due(self):
        self.ticket.first_response_due_at = timezone.now() - timedelta(hours=1)
        self.assertTrue(self.ticket.is_first_response_overdue)

    def test_first_response_warning_at_is_between_creation_and_due(self):
        warning_at = self.ticket.first_response_warning_at
        self.assertIsNotNone(warning_at)
        self.assertTrue(self.ticket.created_at < warning_at < self.ticket.first_response_due_at)


class CheckSlaDeadlinesCommandTests(TestCase):
    def setUp(self):
        self.reporter = make_user("reporter", email="reporter@example.com")
        self.lead = make_user("lead", email="lead@example.com")
        self.dev = make_user("dev", email="dev@example.com")
        self.category, self.team = make_routed_category(team_lead=self.lead)
        self.project = make_project()
        mail.outbox = []

    def _create_ticket(self, **overrides):
        ticket = Ticket.objects.create(
            title="X",
            description="d",
            ticket_type=Ticket.TicketType.BUG,
            category=self.category,
            project=self.project,
            reported_by=self.reporter,
            assigned_to=self.dev,
        )
        if overrides:
            Ticket.objects.filter(pk=ticket.pk).update(**overrides)
            ticket.refresh_from_db()
        return ticket

    def test_first_response_breach_sends_escalation_and_is_idempotent(self):
        now = timezone.now()
        ticket = self._create_ticket(
            created_at=now - timedelta(hours=2),
            first_response_due_at=now - timedelta(hours=1),
            sla_due_at=now + timedelta(hours=50),
        )

        call_command("check_sla_deadlines")
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.first_response_breach_notified_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.lead.email, mail.outbox[0].to)

        call_command("check_sla_deadlines")
        self.assertEqual(len(mail.outbox), 1, "should not resend once already notified")

    def test_first_response_warning_sent_before_breach(self):
        now = timezone.now()
        ticket = self._create_ticket(
            created_at=now - timedelta(minutes=9),
            first_response_due_at=now + timedelta(minutes=1),
            sla_due_at=now + timedelta(hours=50),
        )

        call_command("check_sla_deadlines")
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.first_response_warning_sent_at)
        self.assertIsNone(ticket.first_response_breach_notified_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.dev.email, mail.outbox[0].to)

    def test_no_first_response_notification_once_responded(self):
        now = timezone.now()
        ticket = self._create_ticket(
            created_at=now - timedelta(hours=2),
            first_response_due_at=now - timedelta(hours=1),
            first_responded_at=now - timedelta(minutes=30),
            sla_due_at=now + timedelta(hours=50),
        )

        call_command("check_sla_deadlines")
        ticket.refresh_from_db()
        self.assertIsNone(ticket.first_response_breach_notified_at)
        self.assertEqual(len(mail.outbox), 0)

    def test_resolution_breach_sends_escalation(self):
        now = timezone.now()
        ticket = self._create_ticket(
            created_at=now - timedelta(hours=100),
            first_response_due_at=now - timedelta(hours=99),
            first_responded_at=now - timedelta(hours=98),
            sla_due_at=now - timedelta(hours=1),
        )

        call_command("check_sla_deadlines")
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.sla_breach_notified_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.lead.email, mail.outbox[0].to)

    def test_closed_ticket_is_excluded(self):
        now = timezone.now()
        ticket = self._create_ticket(
            created_at=now - timedelta(hours=100),
            first_response_due_at=now - timedelta(hours=99),
            sla_due_at=now - timedelta(hours=1),
            status=Ticket.Status.CLOSED,
        )

        call_command("check_sla_deadlines")
        ticket.refresh_from_db()
        self.assertIsNone(ticket.sla_breach_notified_at)
        self.assertIsNone(ticket.first_response_breach_notified_at)
        self.assertEqual(len(mail.outbox), 0)


class RunSlaCheckViewTests(TestCase):
    def setUp(self):
        self.pm = make_user("pm", ROLE_PM)
        self.dev = make_user("dev", ROLE_DEV)
        self.lead = make_user("lead", email="lead@example.com")
        self.category, self.team = make_routed_category(team_lead=self.lead)
        self.project = make_project()
        self.reporter = make_user("reporter")
        now = timezone.now()
        self.ticket = Ticket.objects.create(
            title="Overdue",
            description="d",
            ticket_type=Ticket.TicketType.BUG,
            category=self.category,
            project=self.project,
            reported_by=self.reporter,
        )
        Ticket.objects.filter(pk=self.ticket.pk).update(
            created_at=now - timedelta(hours=100),
            first_response_due_at=now - timedelta(hours=99),
            first_responded_at=now - timedelta(hours=98),
            sla_due_at=now - timedelta(hours=1),
        )
        mail.outbox = []

    def test_pm_can_trigger_check_from_web(self):
        self.client.force_login(self.pm)
        response = self.client.post(reverse("tickets:run_sla_check"), follow=True)
        self.assertEqual(response.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.sla_breach_notified_at)
        self.assertEqual(len(mail.outbox), 1)

    def test_developer_cannot_trigger_check(self):
        self.client.force_login(self.dev)
        self.client.post(reverse("tickets:run_sla_check"), follow=True)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.sla_breach_notified_at)
        self.assertEqual(len(mail.outbox), 0)

    def test_anonymous_redirected_to_login(self):
        response = self.client.post(reverse("tickets:run_sla_check"))
        self.assertEqual(response.status_code, 302)
