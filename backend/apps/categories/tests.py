from django.contrib.auth.models import User
from django.test import TestCase

from .forms import CategoryTeamAssignmentForm, TeamForm
from .models import Category, CategoryTeamAssignment, Team


class TeamFormTests(TestCase):
    def test_team_form_includes_lead_and_qa_fields(self):
        form = TeamForm()
        self.assertEqual(set(form.fields), {"name", "team_lead", "qa_tester"})

    def test_team_lead_and_qa_tester_are_optional(self):
        form = TeamForm(data={"name": "Backend"})
        self.assertTrue(form.is_valid())


class CategoryTeamAssignmentFormTests(TestCase):
    def test_assignment_form_only_has_team_field(self):
        form = CategoryTeamAssignmentForm()
        self.assertEqual(set(form.fields), {"team"})


class CategoryTeamRoutingTests(TestCase):
    def test_category_team_lead_comes_from_team(self):
        lead = User.objects.create_user(username="lead", password="pass1234")
        team = Team.objects.create(name="Backend", team_lead=lead)
        category = Category.objects.create(name="API")
        assignment = CategoryTeamAssignment.objects.create(category=category, team=team)
        self.assertEqual(assignment.team.team_lead, lead)
