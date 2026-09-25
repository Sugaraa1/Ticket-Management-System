from django.test import TestCase
from django.urls import reverse

from apps.categories.models import Category
from apps.projects.models import Project
from apps.tickets.permissions import ROLE_ADMIN, ROLE_DEV, ROLE_PM
from apps.tickets.tests.helpers import make_routed_category, make_user


def names(response, key, attr="name"):
    return [getattr(obj, attr) for obj in response.context[key]]


class AdminListFilterTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin", ROLE_ADMIN)
        self.client.force_login(self.admin)

    def test_user_search_role_status_filters(self):
        make_user("alice", ROLE_DEV)
        bob = make_user("bob", ROLE_PM)
        bob.is_active = False
        bob.save()
        url = reverse("accounts:user_list")
        self.assertEqual(names(self.client.get(url, {"q": "ali"}), "users", "username"), ["alice"])
        self.assertEqual(names(self.client.get(url, {"role": ROLE_PM}), "users", "username"), ["bob"])
        self.assertEqual(
            names(self.client.get(url, {"status": "inactive"}), "users", "username"), ["bob"]
        )

    def test_project_status_filter_and_sort(self):
        Project.objects.create(name="Beta")
        Project.objects.create(name="Alpha", is_active=False)
        url = reverse("projects:project_list")
        self.assertEqual(names(self.client.get(url), "projects"), ["Alpha", "Beta"])
        self.assertEqual(names(self.client.get(url, {"status": "active"}), "projects"), ["Beta"])
        self.assertEqual(
            names(self.client.get(url, {"sort": "-created_at"}), "projects"), ["Alpha", "Beta"]
        )

    def test_category_filter_by_team_and_unrouted(self):
        _category, team = make_routed_category(name="Backend")
        Category.objects.create(name="Orphan")
        url = reverse("categories:category_list")
        self.assertEqual(names(self.client.get(url, {"team": "none"}), "categories"), ["Orphan"])
        self.assertEqual(names(self.client.get(url, {"team": team.pk}), "categories"), ["Backend"])

    def test_team_missing_lead_filter(self):
        make_routed_category(team_lead=self.admin, name="Led")
        make_routed_category(name="Unled")
        url = reverse("categories:team_list")
        self.assertEqual(names(self.client.get(url, {"missing": "lead"}), "teams"), ["Unled Team"])

    def test_invalid_params_are_ignored(self):
        Project.objects.create(name="Alpha")
        response = self.client.get(
            reverse("projects:project_list"), {"sort": "password", "status": "bogus", "page": "99"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(names(response, "projects"), ["Alpha"])

    def test_pagination(self):
        for i in range(30):
            Project.objects.create(name=f"P{i:02d}")
        url = reverse("projects:project_list")
        self.assertEqual(len(self.client.get(url).context["projects"]), 25)
        self.assertEqual(len(self.client.get(url, {"page": 2}).context["projects"]), 5)
