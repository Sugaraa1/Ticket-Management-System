from django.test import TestCase

from apps.projects.models import Module, Project
from apps.tickets.forms import TicketForm
from apps.tickets.models import Ticket

from .helpers import make_routed_category


class TicketFormModuleProjectConsistencyTests(TestCase):
    def setUp(self):
        self.category, self.team = make_routed_category()
        self.project_a = Project.objects.create(name="Project A")
        self.project_b = Project.objects.create(name="Project B")
        self.module_of_b = Module.objects.create(project=self.project_b, name="Module B1")

    def _data(self, **overrides):
        data = {
            "title": "Test ticket",
            "description": "desc",
            "ticket_type": Ticket.TicketType.BUG,
            "category": self.category.id,
            "project": self.project_a.id,
            "module": "",
            "priority": Ticket.Priority.MEDIUM,
        }
        data.update(overrides)
        return data

    def test_rejects_module_from_a_different_project(self):
        form = TicketForm(data=self._data(module=self.module_of_b.id))
        self.assertFalse(form.is_valid())
        self.assertIn("module", form.errors)

    def test_accepts_module_matching_selected_project(self):
        module_of_a = Module.objects.create(project=self.project_a, name="Module A1")
        form = TicketForm(data=self._data(module=module_of_a.id))
        self.assertTrue(form.is_valid(), form.errors)

    def test_accepts_no_module_selected(self):
        form = TicketForm(data=self._data(module=""))
        self.assertTrue(form.is_valid(), form.errors)
