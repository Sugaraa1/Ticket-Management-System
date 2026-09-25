from django.test import TestCase
from django.urls import reverse

from apps.projects.models import Module, Project
from apps.tickets.permissions import ROLE_DEV, ROLE_PM
from apps.tickets.tests.helpers import make_user


class ProjectToggleTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name="Demo")

    def test_pm_toggles_active_both_ways(self):
        self.client.force_login(make_user("pm", ROLE_PM))
        url = reverse("projects:project_toggle_active", args=[self.project.pk])
        self.client.post(url)
        self.project.refresh_from_db()
        self.assertFalse(self.project.is_active)
        self.client.post(url)
        self.project.refresh_from_db()
        self.assertTrue(self.project.is_active)

    def test_developer_cannot_toggle(self):
        self.client.force_login(make_user("dev", ROLE_DEV))
        self.client.post(reverse("projects:project_toggle_active", args=[self.project.pk]))
        self.project.refresh_from_db()
        self.assertTrue(self.project.is_active)

    def test_list_rows_link_to_project(self):
        self.client.force_login(make_user("pm", ROLE_PM))
        response = self.client.get(reverse("projects:project_list"))
        self.assertContains(response, f'data-href="{reverse("projects:project_edit", args=[self.project.pk])}"')

    def test_toggle_script_is_in_page_body_not_title(self):
        self.client.force_login(make_user("pm", ROLE_PM))
        html = self.client.get(reverse("projects:project_list")).content.decode()
        title = html[html.index("<title>"):html.index("</title>")]
        self.assertNotIn("<script", title)
        self.assertIn(".js-active-toggle input", html)


class ModuleManagementTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name="Demo")
        self.module = Module.objects.create(project=self.project, name="Auth")
        self.client.force_login(make_user("pm", ROLE_PM))

    def _url(self, action):
        return reverse(f"projects:module_{action}", args=[self.project.pk, self.module.pk])

    def test_rename_module(self):
        self.client.post(self._url("edit"), {"name": "Login"})
        self.module.refresh_from_db()
        self.assertEqual(self.module.name, "Login")

    def test_duplicate_name_rejected(self):
        Module.objects.create(project=self.project, name="Billing")
        self.client.post(self._url("edit"), {"name": "billing"})
        self.module.refresh_from_db()
        self.assertEqual(self.module.name, "Auth")

    def test_duplicate_on_create_does_not_crash(self):
        response = self.client.post(
            reverse("projects:module_create", args=[self.project.pk]), {"name": "Auth"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.project.modules.count(), 1)

    def test_delete_keeps_tickets(self):
        from apps.tickets.models import Ticket
        from apps.tickets.tests.helpers import make_routed_category

        category, _team = make_routed_category()
        ticket = Ticket.objects.create(
            title="t", description="d", ticket_type=Ticket.TicketType.BUG, category=category,
            project=self.project, module=self.module, reported_by=make_user("rep"),
        )
        self.client.post(self._url("delete"))
        self.assertFalse(Module.objects.filter(pk=self.module.pk).exists())
        ticket.refresh_from_db()
        self.assertIsNone(ticket.module)

    def test_developer_cannot_delete(self):
        self.client.force_login(make_user("dev", ROLE_DEV))
        self.client.post(self._url("delete"))
        self.assertTrue(Module.objects.filter(pk=self.module.pk).exists())


class ProjectDeleteTests(TestCase):
    def setUp(self):
        self.project = Project.objects.create(name="Demo")
        Module.objects.create(project=self.project, name="Auth")
        self.client.force_login(make_user("pm", ROLE_PM))

    def test_delete_project_without_tickets(self):
        self.client.post(reverse("projects:project_delete", args=[self.project.pk]))
        self.assertFalse(Project.objects.filter(pk=self.project.pk).exists())
        self.assertFalse(Module.objects.exists())

    def test_project_with_tickets_is_deactivated_not_deleted(self):
        from apps.tickets.models import Ticket
        from apps.tickets.tests.helpers import make_routed_category

        category, _team = make_routed_category()
        Ticket.objects.create(
            title="t", description="d", ticket_type=Ticket.TicketType.BUG,
            category=category, project=self.project, reported_by=make_user("rep"),
        )
        self.client.post(reverse("projects:project_delete", args=[self.project.pk]))
        self.project.refresh_from_db()
        self.assertFalse(self.project.is_active)

    def test_developer_cannot_delete_project(self):
        self.client.force_login(make_user("dev", ROLE_DEV))
        self.client.post(reverse("projects:project_delete", args=[self.project.pk]))
        self.assertTrue(Project.objects.filter(pk=self.project.pk).exists())

    def test_delete_button_asks_for_confirmation(self):
        response = self.client.get(reverse("projects:project_list"))
        self.assertContains(response, "итгэлтэй байна уу")
        self.assertContains(response, 'id="tmsConfirm"')
        self.assertNotContains(response, "return confirm(")
