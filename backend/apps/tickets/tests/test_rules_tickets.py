"""
Тикетийн өгөгдөл ба workflow-ийн дүрмүүд (docs/rules.md — TKT-*, WF-*, SEC-04).

Эх сурвалж: ITIL 4 Incident/Request management (бүртгэл, шалтгаан, аудит),
OWASP ASVS V5 (оролтын шалгалт, XSS).
"""
from django.test import TestCase
from django.urls import reverse

from apps.tickets.forms import TicketForm
from apps.tickets.models import StatusHistory, Ticket
from apps.tickets.permissions import ROLE_DEV, ROLE_PM, ROLE_QA

from .helpers import make_project, make_routed_category, make_user


class TicketDataRulesTests(TestCase):
    def setUp(self):
        self.category, _ = make_routed_category()
        self.project = make_project()
        self.valid = {
            "title": "Нэвтрэх товч ажиллахгүй", "ticket_type": "bug", "priority": "medium",
            "category": self.category.pk, "project": self.project.pk, "description": "Алхам: ...",
        }

    def test_required_fields(self):
        """[TKT-01] Title, type, category, project and description are required"""
        for field in ("title", "ticket_type", "category", "project", "description"):
            with self.subTest(field=field):
                form = TicketForm({**self.valid, field: ""})
                self.assertIn(field, form.errors)

    def test_whitespace_only_title_rejected(self):
        """[TKT-02] Whitespace-only title is rejected"""
        self.assertIn("title", TicketForm({**self.valid, "title": "     "}).errors)

    def test_title_length_limit(self):
        """[TKT-03] Title over 255 characters is rejected; exactly 255 is accepted"""
        self.assertIn("title", TicketForm({**self.valid, "title": "а" * 256}).errors)
        self.assertTrue(TicketForm({**self.valid, "title": "а" * 255}).is_valid())

    def test_unknown_priority_rejected(self):
        """[TKT-04] Priority outside the allowed list (e.g. "urgent!!") is rejected"""
        self.assertIn("priority", TicketForm({**self.valid, "priority": "urgent!!"}).errors)

    def test_new_ticket_starts_as_new_and_unassigned(self):
        """[TKT-05] New ticket starts as New, unassigned, with an SLA due date"""
        reporter = make_user("rep")
        self.client.force_login(reporter)
        self.client.post(reverse("tickets:ticket_create"), self.valid)
        ticket = Ticket.objects.get()
        self.assertEqual((ticket.status, ticket.assigned_to), ("new", None))
        self.assertEqual(ticket.reported_by, reporter)
        self.assertIsNotNone(ticket.sla_due_at)

    def test_reporter_cannot_be_forged(self):
        """[TKT-06] Reporter cannot be forged via POST data"""
        reporter, other = make_user("rep"), make_user("other")
        self.client.force_login(reporter)
        self.client.post(reverse("tickets:ticket_create"), {**self.valid, "reported_by": other.pk})
        self.assertEqual(Ticket.objects.get().reported_by, reporter)


class WorkflowRulesTests(TestCase):
    def setUp(self):
        self.pm = make_user("pm", ROLE_PM)
        self.dev = make_user("dev", ROLE_DEV)
        self.qa = make_user("qa", ROLE_QA)
        category, _ = make_routed_category(team_lead=self.pm, qa_tester=self.qa, members=[self.dev])
        self.ticket = Ticket.objects.create(
            title="x", description="d", ticket_type="bug", category=category,
            project=make_project(), reported_by=self.pm,
        )
        self.url = reverse("tickets:ticket_detail", args=[self.ticket.pk])

    def _move(self, *statuses):
        for status in statuses:
            if status == "assigned":
                self.ticket.assigned_to = self.dev
            self.ticket.transition_to(status)

    def _post(self, user, status, comment=""):
        self.client.force_login(user)
        self.client.post(self.url, {"action": "transition", "new_status": status, "comment": comment})
        self.ticket.refresh_from_db()

    def test_transition_is_audited_with_actor(self):
        """[WF-01] Every transition is audited with actor, time, from and to status"""
        self._move("assigned")
        self._post(self.dev, "in_progress")
        entry = StatusHistory.objects.filter(ticket=self.ticket).latest("changed_at")
        self.assertEqual(
            (entry.from_status, entry.to_status, entry.changed_by), ("assigned", "in_progress", self.dev)
        )

    def test_rejection_requires_reason(self):
        """[WF-02] Rejecting a ticket requires a reason (ITIL)"""
        self._move("assigned", "in_progress")
        self._post(self.dev, "rejected", comment="")
        self.assertEqual(self.ticket.status, "in_progress")

    def test_qa_reopen_requires_reason(self):
        """[WF-03] QA reopening a ticket requires a reason"""
        self._move("assigned", "in_progress", "resolved", "qa_test")
        self._post(self.qa, "reopened", comment="")
        self.assertEqual(self.ticket.status, "qa_test")

    def test_rejection_with_reason_succeeds(self):
        """[WF-02] Rejecting with a reason moves the ticket to Rejected"""
        self._move("assigned", "in_progress")
        self._post(self.dev, "rejected", comment="Энэ нь манай системийн алдаа биш")
        self.assertEqual(self.ticket.status, "rejected")

    def test_developer_cannot_reopen_rejected_ticket(self):
        """[WF-04] Only PM (or Admin) can reopen a rejected ticket"""
        self._move("assigned", "in_progress", "rejected")
        self._post(self.dev, "reopened", comment="дахин")
        self.assertEqual(self.ticket.status, "rejected")

    def test_closed_ticket_is_final(self):
        """[WF-05] Closed ticket cannot move to any other status"""
        self._move("assigned", "in_progress", "resolved", "qa_test", "closed")
        for status in ("new", "assigned", "in_progress", "reopened"):
            with self.subTest(to=status):
                self._post(self.pm, status, comment="x")
                self.assertEqual(self.ticket.status, "closed")

    def test_reporter_cannot_close_own_ticket_bypassing_qa(self):
        """[WF-06] Reporter cannot close their own ticket bypassing QA"""
        reporter = make_user("reporter", ROLE_DEV)
        self.ticket.reported_by = reporter
        self.ticket.save()
        self._move("assigned", "in_progress", "resolved", "qa_test")
        self._post(reporter, "closed")
        self.assertEqual(self.ticket.status, "qa_test")


class OutputEscapingTests(TestCase):
    def test_ticket_title_is_escaped_everywhere(self):
        """[SEC-04] HTML/script in ticket fields is escaped on list and detail pages"""
        user = make_user("u", ROLE_PM)
        category, _ = make_routed_category()
        ticket = Ticket.objects.create(
            title="<script>alert(1)</script>", description="<img src=x onerror=alert(1)>",
            ticket_type="bug", category=category, project=make_project(), reported_by=user,
        )
        self.client.force_login(user)
        for url in (reverse("tickets:ticket_list"), reverse("tickets:ticket_detail", args=[ticket.pk])):
            with self.subTest(url=url):
                html = self.client.get(url).content.decode()
                self.assertNotIn("<script>alert(1)</script>", html)
                self.assertNotIn("<img src=x onerror", html)
