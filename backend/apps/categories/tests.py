from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .forms import CategoryTeamsForm, TeamForm
from .models import Category, CategoryTeamAssignment, Subcategory, Team


class TeamFormTests(TestCase):
    def test_team_form_includes_lead_and_qa_fields(self):
        form = TeamForm()
        self.assertEqual(set(form.fields), {"name", "team_lead", "qa_tester"})

    def test_team_lead_and_qa_tester_are_optional(self):
        form = TeamForm(data={"name": "Backend"})
        self.assertTrue(form.is_valid())


class CategoryTeamsFormTests(TestCase):
    def test_form_only_has_teams_field(self):
        self.assertEqual(set(CategoryTeamsForm().fields), {"teams"})


class CategoryTeamRoutingTests(TestCase):
    def test_category_team_lead_comes_from_team(self):
        lead = User.objects.create_user(username="lead", password="pass1234")
        team = Team.objects.create(name="Backend", team_lead=lead)
        category = Category.objects.create(name="API")
        assignment = CategoryTeamAssignment.objects.create(category=category, team=team)
        self.assertEqual(assignment.team.team_lead, lead)

    def test_ticket_routes_to_least_loaded_team(self):
        from apps.categories.models import route_team_for_category

        category = Category.objects.create(name="Shared")
        busy = Team.objects.create(name="Busy")
        free = Team.objects.create(name="Free")
        CategoryTeamAssignment.objects.create(category=category, team=busy)
        CategoryTeamAssignment.objects.create(category=category, team=free)
        self.assertEqual(route_team_for_category(category.id), busy)  # tie -> lowest id


class TeamDetailPickerTests(TestCase):
    def setUp(self):
        from apps.tickets.permissions import ROLE_ADMIN, ROLE_DEV
        from apps.tickets.tests.helpers import make_routed_category, make_user

        self.client.force_login(make_user("admin", ROLE_ADMIN))
        self.alice, self.bob = make_user("alice", ROLE_DEV), make_user("bob", ROLE_DEV)
        _category, self.team = make_routed_category(members=[self.bob])
        self.url = reverse("categories:team_detail", args=[self.team.pk])

    def test_selected_members_listed_first_with_search(self):
        response = self.client.get(self.url)
        choices = [c["user"].username for c in response.context["member_choices"]]
        self.assertEqual(choices[0], "bob")
        self.assertEqual(response.context["selected_count"], 1)
        self.assertContains(response, "js-picker-search")
        self.assertContains(response, "js-workload-search")

    def test_saving_members_still_works(self):
        self.client.post(self.url, {"members": [self.alice.pk, self.bob.pk]})
        self.assertEqual(set(self.team.members.values_list("username", flat=True)), {"alice", "bob"})


class CategoryDeleteTests(TestCase):
    def setUp(self):
        from apps.tickets.permissions import ROLE_ADMIN, ROLE_PM
        from apps.tickets.tests.helpers import make_user

        self.admin = make_user("adm", ROLE_ADMIN)
        self.pm = make_user("pm", ROLE_PM)
        self.team = Team.objects.create(name="T")
        self.category = Category.objects.create(name="API")
        CategoryTeamAssignment.objects.create(category=self.category, team=self.team)
        self.url = reverse("categories:category_delete", args=[self.category.pk])

    def test_admin_deletes_category_without_tickets(self):
        self.client.force_login(self.admin)
        self.client.post(self.url)
        self.assertFalse(Category.objects.filter(pk=self.category.pk).exists())
        self.assertTrue(Team.objects.filter(pk=self.team.pk).exists())

    def test_pm_cannot_delete(self):
        self.client.force_login(self.pm)
        self.client.post(self.url)
        self.assertTrue(Category.objects.filter(pk=self.category.pk).exists())

    def test_get_does_not_delete(self):
        self.client.force_login(self.admin)
        self.client.get(self.url)
        self.assertTrue(Category.objects.filter(pk=self.category.pk).exists())

    def test_category_with_tickets_is_kept(self):
        from apps.tickets.models import Ticket
        from apps.tickets.tests.helpers import make_project

        Ticket.objects.create(
            title="x", description="d", ticket_type="bug", category=self.category,
            project=make_project(), reported_by=self.admin,
        )
        self.client.force_login(self.admin)
        self.client.post(self.url)
        self.assertTrue(Category.objects.filter(pk=self.category.pk).exists())


class SubcategoryTests(TestCase):
    def setUp(self):
        from apps.tickets.permissions import ROLE_DEV, ROLE_PM
        from apps.tickets.tests.helpers import make_project, make_user

        self.pm = make_user("pm", ROLE_PM)
        self.dev = make_user("dev", ROLE_DEV)
        self.project = make_project()
        self.mobile = Category.objects.create(name="Mobile")
        self.web = Category.objects.create(name="Web")
        self.ios = Subcategory.objects.create(category=self.mobile, name="iOS")

    def _ticket_data(self, category, subcategory=""):
        return {
            "title": "t", "ticket_type": "bug", "priority": "medium", "description": "d",
            "category": category.pk, "subcategory": subcategory, "project": self.project.pk,
        }

    def test_ticket_with_matching_subcategory(self):
        from apps.tickets.forms import TicketForm

        form = TicketForm(self._ticket_data(self.mobile, self.ios.pk))
        self.assertTrue(form.is_valid(), form.errors)

    def test_subcategory_is_optional(self):
        from apps.tickets.forms import TicketForm

        self.assertTrue(TicketForm(self._ticket_data(self.web)).is_valid())

    def test_subcategory_of_other_category_is_rejected(self):
        from apps.tickets.forms import TicketForm

        form = TicketForm(self._ticket_data(self.web, self.ios.pk))
        self.assertIn("subcategory", form.errors)

    def test_pm_adds_and_deletes_subcategory(self):
        self.client.force_login(self.pm)
        self.client.post(reverse("categories:subcategory_create", args=[self.mobile.pk]), {"name": "Android"})
        self.client.post(reverse("categories:subcategory_create", args=[self.mobile.pk]), {"name": "android"})
        self.assertEqual(self.mobile.subcategories.filter(name__iexact="android").count(), 1)
        self.client.post(reverse("categories:subcategory_delete", args=[self.mobile.pk, self.ios.pk]))
        self.assertFalse(Subcategory.objects.filter(pk=self.ios.pk).exists())

    def test_developer_cannot_add_subcategory(self):
        self.client.force_login(self.dev)
        self.client.post(reverse("categories:subcategory_create", args=[self.web.pk]), {"name": "X"})
        self.assertFalse(self.web.subcategories.exists())
