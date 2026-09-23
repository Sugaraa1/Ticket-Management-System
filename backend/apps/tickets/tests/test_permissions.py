from django.test import TestCase

from apps.tickets.models import Ticket
from apps.tickets.permissions import (
    ROLE_DEV,
    ROLE_PM,
    ROLE_QA,
    can_user_assign,
    can_user_transition,
    team_members_with_workload,
)

from .helpers import make_project, make_routed_category, make_user


class TransitionPermissionTests(TestCase):
    def setUp(self):
        self.pm = make_user("pm", ROLE_PM)
        self.dev = make_user("dev", ROLE_DEV)
        self.other_dev = make_user("dev2", ROLE_DEV)
        self.qa = make_user("qa", ROLE_QA)
        self.category, self.team = make_routed_category()
        self.project = make_project()
        self.ticket = Ticket.objects.create(
            title="X",
            description="d",
            ticket_type=Ticket.TicketType.BUG,
            category=self.category,
            project=self.project,
            reported_by=self.pm,
        )

    def test_pm_can_assign_new_ticket(self):
        allowed, _ = can_user_transition(self.ticket, "assigned", self.pm)
        self.assertTrue(allowed)

    def test_dev_cannot_assign_new_ticket(self):
        allowed, _ = can_user_transition(self.ticket, "assigned", self.dev)
        self.assertFalse(allowed)

    def test_unknown_transition_is_rejected(self):
        allowed, _ = can_user_transition(self.ticket, "closed", self.pm)
        self.assertFalse(allowed)

    def test_assignee_only_transition_blocks_other_developer(self):
        self.ticket.assigned_to = self.dev
        self.ticket.status = "assigned"
        allowed, _ = can_user_transition(self.ticket, "in_progress", self.other_dev)
        self.assertFalse(allowed)

    def test_assignee_only_transition_allows_assignee(self):
        self.ticket.assigned_to = self.dev
        self.ticket.status = "assigned"
        allowed, _ = can_user_transition(self.ticket, "in_progress", self.dev)
        self.assertTrue(allowed)

    def test_qa_can_close_from_qa_test(self):
        self.ticket.status = "qa_test"
        allowed, _ = can_user_transition(self.ticket, "closed", self.qa)
        self.assertTrue(allowed)

    def test_can_user_assign(self):
        self.assertTrue(can_user_assign(self.pm))
        self.assertFalse(can_user_assign(self.dev))


class WorkloadTests(TestCase):
    def test_members_ordered_by_active_ticket_count(self):
        busy = make_user("busy", ROLE_DEV)
        free = make_user("free", ROLE_DEV)
        category, team = make_routed_category(members=[busy, free])
        project = make_project()
        reporter = make_user("reporter")
        Ticket.objects.create(
            title="A",
            description="d",
            ticket_type=Ticket.TicketType.BUG,
            category=category,
            project=project,
            reported_by=reporter,
            assigned_to=busy,
            status="assigned",
        )

        ordered = list(team_members_with_workload(team))
        self.assertEqual(ordered[0], free)
        self.assertEqual(ordered[1], busy)

    def test_empty_team_returns_empty_list(self):
        self.assertEqual(team_members_with_workload(None), [])
