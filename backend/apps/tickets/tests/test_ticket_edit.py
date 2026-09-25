from django.test import TestCase
from django.urls import reverse

from apps.projects.models import Module, Project
from apps.tickets.models import Ticket
from apps.tickets.permissions import ROLE_DEV, ROLE_PM

from .helpers import make_project, make_routed_category, make_user


class TicketEditTests(TestCase):
    def setUp(self):
        self.reporter = make_user("rep", ROLE_DEV)
        self.dev = make_user("dev", ROLE_DEV)
        self.category, self.team = make_routed_category(members=[self.dev])
        self.other_category, self.other_team = make_routed_category(name="Frontend", members=[self.dev])
        self.project = make_project()
        self.ticket = Ticket.objects.create(
            title="Old title", description="d", ticket_type="bug", category=self.category,
            project=self.project, reported_by=self.reporter,
        )
        self.url = reverse("tickets:ticket_edit", args=[self.ticket.pk])

    def _data(self, **overrides):
        data = {"title": self.ticket.title, "ticket_type": self.ticket.ticket_type,
                "category": self.ticket.category_id, "project": self.ticket.project_id,
                "module": "", "description": self.ticket.description}
        data.update(overrides)
        return data

    def test_reporter_edits_and_change_is_logged(self):
        self.client.force_login(self.reporter)
        self.client.post(self.url, self._data(title="New title"))
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.title, "New title")
        log = self.ticket.comments.last().body
        self.assertIn("Old title → New title", log)

    def test_category_change_on_new_ticket_reroutes_team(self):
        self.client.force_login(self.reporter)
        self.client.post(self.url, self._data(category=self.other_category.pk))
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.team, self.other_team)

    def test_category_locked_after_assignment(self):
        self.ticket.assigned_to = self.dev
        self.ticket.transition_to("assigned")
        self.client.force_login(self.reporter)
        self.client.post(self.url, self._data(category=self.other_category.pk, title="T2"))
        self.ticket.refresh_from_db()
        self.assertEqual((self.ticket.category, self.ticket.team, self.ticket.title),
                         (self.category, self.team, "T2"))

    def test_module_must_belong_to_project(self):
        foreign = Module.objects.create(project=Project.objects.create(name="Other"), name="X")
        self.client.force_login(self.reporter)
        response = self.client.post(self.url, self._data(module=foreign.pk))
        self.assertEqual(response.status_code, 200)
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.module)

    def test_unrelated_developer_cannot_edit(self):
        self.client.force_login(self.dev)
        self.client.post(self.url, self._data(title="Hacked"))
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.title, "Old title")

    def test_pm_can_edit_but_not_closed_ticket(self):
        pm = make_user("pm", ROLE_PM)
        self.client.force_login(pm)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        Ticket.objects.filter(pk=self.ticket.pk).update(status="closed")
        self.assertEqual(self.client.get(self.url).status_code, 302)

    def test_detail_shows_edit_button_only_when_allowed(self):
        detail = reverse("tickets:ticket_detail", args=[self.ticket.pk])
        self.client.force_login(self.reporter)
        self.assertContains(self.client.get(detail), self.url)
        self.client.force_login(self.dev)
        self.assertNotContains(self.client.get(detail), self.url)
