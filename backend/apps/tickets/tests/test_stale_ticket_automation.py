from datetime import timedelta

from django.core import mail
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from apps.tickets.models import Ticket
from apps.tickets.permissions import ROLE_DEV, ROLE_PM

from .helpers import make_project, make_routed_category, make_user


@override_settings(STALE_TICKET_REMINDER_HOURS=48)
class ActivityTrackingTests(TestCase):
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

    def test_last_activity_at_set_on_create(self):
        self.assertIsNotNone(self.ticket.last_activity_at)

    def test_transition_bumps_last_activity_and_clears_reminder(self):
        Ticket.objects.filter(pk=self.ticket.pk).update(
            last_activity_at=timezone.now() - timedelta(hours=100),
            stale_reminder_sent_at=timezone.now() - timedelta(hours=10),
        )
        self.ticket.refresh_from_db()
        self.ticket.transition_to(Ticket.Status.ASSIGNED, user=self.reporter)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.stale_reminder_sent_at)
        self.assertGreater(self.ticket.last_activity_at, timezone.now() - timedelta(minutes=1))

    def test_mark_activity_updates_fields(self):
        Ticket.objects.filter(pk=self.ticket.pk).update(
            last_activity_at=timezone.now() - timedelta(hours=100),
            stale_reminder_sent_at=timezone.now() - timedelta(hours=10),
        )
        self.ticket.refresh_from_db()
        self.ticket.mark_activity()
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.stale_reminder_sent_at)
        self.assertGreater(self.ticket.last_activity_at, timezone.now() - timedelta(minutes=1))

    def test_comment_by_any_user_marks_activity(self):
        Ticket.objects.filter(pk=self.ticket.pk).update(
            last_activity_at=timezone.now() - timedelta(hours=100)
        )
        self.client.force_login(self.reporter)
        self.client.post(
            reverse("tickets:ticket_detail", args=[self.ticket.pk]),
            {"action": "comment", "body": "hello", "is_internal": False},
        )
        self.ticket.refresh_from_db()
        self.assertGreater(self.ticket.last_activity_at, timezone.now() - timedelta(minutes=1))


@override_settings(STALE_TICKET_REMINDER_HOURS=48)
class CheckStaleTicketsCommandTests(TestCase):
    def setUp(self):
        self.reporter = make_user("reporter")
        self.dev = make_user("dev", email="dev@example.com")
        self.lead = make_user("lead", email="lead@example.com")
        self.category, self.team = make_routed_category(team_lead=self.lead)
        self.project = make_project()
        mail.outbox = []

    def _create_ticket(self, assigned_to=None, **overrides):
        ticket = Ticket.objects.create(
            title="X",
            description="d",
            ticket_type=Ticket.TicketType.BUG,
            category=self.category,
            project=self.project,
            reported_by=self.reporter,
            assigned_to=assigned_to,
        )
        if overrides:
            Ticket.objects.filter(pk=ticket.pk).update(**overrides)
            ticket.refresh_from_db()
        return ticket

    def test_sends_reminder_when_idle_past_threshold(self):
        now = timezone.now()
        ticket = self._create_ticket(
            assigned_to=self.dev, last_activity_at=now - timedelta(hours=49)
        )

        call_command("check_stale_tickets")
        ticket.refresh_from_db()
        self.assertIsNotNone(ticket.stale_reminder_sent_at)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.dev.email, mail.outbox[0].to)

    def test_no_reminder_before_threshold(self):
        now = timezone.now()
        ticket = self._create_ticket(
            assigned_to=self.dev, last_activity_at=now - timedelta(hours=10)
        )

        call_command("check_stale_tickets")
        ticket.refresh_from_db()
        self.assertIsNone(ticket.stale_reminder_sent_at)
        self.assertEqual(len(mail.outbox), 0)

    def test_no_repeat_reminder_before_next_interval(self):
        now = timezone.now()
        ticket = self._create_ticket(
            assigned_to=self.dev,
            last_activity_at=now - timedelta(hours=100),
            stale_reminder_sent_at=now - timedelta(hours=5),
        )

        call_command("check_stale_tickets")
        self.assertEqual(len(mail.outbox), 0, "should wait a full interval before repeating")

    def test_repeat_reminder_after_another_full_interval(self):
        now = timezone.now()
        ticket = self._create_ticket(
            assigned_to=self.dev,
            last_activity_at=now - timedelta(hours=200),
            stale_reminder_sent_at=now - timedelta(hours=50),
        )

        call_command("check_stale_tickets")
        ticket.refresh_from_db()
        self.assertEqual(len(mail.outbox), 1)
        self.assertGreater(ticket.stale_reminder_sent_at, now - timedelta(minutes=1))

    def test_falls_back_to_team_lead_when_unassigned(self):
        now = timezone.now()
        self._create_ticket(assigned_to=None, last_activity_at=now - timedelta(hours=49))

        call_command("check_stale_tickets")
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn(self.lead.email, mail.outbox[0].to)

    def test_closed_ticket_excluded(self):
        now = timezone.now()
        ticket = self._create_ticket(
            assigned_to=self.dev,
            last_activity_at=now - timedelta(hours=100),
            status=Ticket.Status.CLOSED,
        )

        call_command("check_stale_tickets")
        ticket.refresh_from_db()
        self.assertIsNone(ticket.stale_reminder_sent_at)
        self.assertEqual(len(mail.outbox), 0)


@override_settings(STALE_TICKET_REMINDER_HOURS=48)
class RunStaleCheckViewTests(TestCase):
    def setUp(self):
        self.pm = make_user("pm", ROLE_PM)
        self.dev_role_user = make_user("devrole", ROLE_DEV)
        self.reporter = make_user("reporter")
        self.dev = make_user("dev", email="dev@example.com")
        self.category, self.team = make_routed_category()
        self.project = make_project()
        now = timezone.now()
        self.ticket = Ticket.objects.create(
            title="X",
            description="d",
            ticket_type=Ticket.TicketType.BUG,
            category=self.category,
            project=self.project,
            reported_by=self.reporter,
            assigned_to=self.dev,
        )
        Ticket.objects.filter(pk=self.ticket.pk).update(
            last_activity_at=now - timedelta(hours=100)
        )
        mail.outbox = []

    def test_pm_can_trigger_from_web(self):
        self.client.force_login(self.pm)
        self.client.post(reverse("tickets:run_stale_check"), follow=True)
        self.ticket.refresh_from_db()
        self.assertIsNotNone(self.ticket.stale_reminder_sent_at)
        self.assertEqual(len(mail.outbox), 1)

    def test_developer_cannot_trigger(self):
        self.client.force_login(self.dev_role_user)
        self.client.post(reverse("tickets:run_stale_check"), follow=True)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.stale_reminder_sent_at)
