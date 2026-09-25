from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .forms import CategoryTeamsForm, TeamForm
from .models import Category, CategoryTeamAssignment, Team


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
