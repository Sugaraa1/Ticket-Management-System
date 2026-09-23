from datetime import timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.categories.models import Category
from apps.tickets.models import Ticket, can_transition

from .helpers import make_project, make_routed_category, make_user


class CanTransitionTests(TestCase):
    def test_allowed_transitions(self):
        self.assertTrue(can_transition("new", "assigned"))
        self.assertTrue(can_transition("qa_test", "closed"))
        self.assertTrue(can_transition("qa_test", "reopened"))

    def test_disallowed_transitions(self):
        self.assertFalse(can_transition("new", "closed"))
        self.assertFalse(can_transition("closed", "in_progress"))

    def test_same_status_is_allowed(self):
        self.assertTrue(can_transition("new", "new"))


class TicketSlaTests(TestCase):
    def setUp(self):
        self.reporter = make_user("reporter")
        self.category, self.team = make_routed_category()
        self.project = make_project()

    def _create_ticket(self, priority):
        return Ticket.objects.create(
            title="Bug",
            description="...",
            ticket_type=Ticket.TicketType.BUG,
            category=self.category,
            project=self.project,
            priority=priority,
            reported_by=self.reporter,
        )

    def test_sla_due_at_set_from_priority(self):
        ticket = self._create_ticket(Ticket.Priority.CRITICAL)
        expected = ticket.created_at + timedelta(hours=4)
        self.assertAlmostEqual(ticket.sla_due_at, expected, delta=timedelta(seconds=5))

    def test_is_overdue_true_when_past_due(self):
        ticket = self._create_ticket(Ticket.Priority.LOW)
        ticket.sla_due_at = timezone.now() - timedelta(hours=1)
        self.assertTrue(ticket.is_overdue)

    def test_is_overdue_false_when_no_due_date(self):
        ticket = self._create_ticket(Ticket.Priority.LOW)
        ticket.sla_due_at = None
        self.assertFalse(ticket.is_overdue)

    def test_is_overdue_false_when_closed_even_if_past_due(self):
        ticket = self._create_ticket(Ticket.Priority.LOW)
        ticket.sla_due_at = timezone.now() - timedelta(hours=1)
        ticket.status = Ticket.Status.CLOSED
        self.assertFalse(ticket.is_overdue)


class AutoRoutingTests(TestCase):
    def setUp(self):
        self.reporter = make_user("reporter")
        self.project = make_project()

    def test_ticket_gets_team_from_category_assignment(self):
        category, team = make_routed_category()
        ticket = Ticket.objects.create(
            title="X",
            description="d",
            ticket_type=Ticket.TicketType.TASK,
            category=category,
            project=self.project,
            reported_by=self.reporter,
        )
        self.assertEqual(ticket.team_id, team.id)

    def test_ticket_without_category_assignment_has_no_team(self):
        category = Category.objects.create(name="Unassigned")
        ticket = Ticket.objects.create(
            title="X",
            description="d",
            ticket_type=Ticket.TicketType.TASK,
            category=category,
            project=self.project,
            reported_by=self.reporter,
        )
        self.assertIsNone(ticket.team_id)


class TransitionTests(TestCase):
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

    def test_creates_status_history_on_create(self):
        history = list(self.ticket.history.all())
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].from_status, "")
        self.assertEqual(history[0].to_status, "new")

    def test_transition_to_valid_status_succeeds(self):
        self.ticket.transition_to(Ticket.Status.ASSIGNED, user=self.reporter)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, Ticket.Status.ASSIGNED)
        self.assertEqual(self.ticket.history.count(), 2)

    def test_transition_to_invalid_status_raises(self):
        with self.assertRaises(ValidationError):
            self.ticket.transition_to(Ticket.Status.CLOSED)

    def test_transition_to_with_comment_creates_comment(self):
        self.ticket.transition_to(
            Ticket.Status.ASSIGNED, user=self.reporter, comment="assigning"
        )
        self.assertTrue(self.ticket.comments.filter(body="assigning").exists())
