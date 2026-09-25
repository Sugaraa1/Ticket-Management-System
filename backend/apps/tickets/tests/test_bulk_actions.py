from django.test import TestCase
from django.urls import reverse

from apps.tickets.models import Ticket
from apps.tickets.permissions import ROLE_DEV, ROLE_PM

from .helpers import make_project, make_routed_category, make_user


def _ticket(category, reporter, title="t", **kw):
    return Ticket.objects.create(title=title, description="d", ticket_type="bug",
                                 category=category, project=make_project(f"P-{title}"), reported_by=reporter, **kw)


class BulkActionTests(TestCase):
    def setUp(self):
        self.pm = make_user("pm", ROLE_PM)
        self.dev = make_user("dev", ROLE_DEV)
        self.category, self.team = make_routed_category(members=[self.dev])
        self.other_cat, _ = make_routed_category(name="Other")  # dev нь энэ багт байхгүй
        self.t1 = _ticket(self.category, self.pm, "a")
        self.t2 = _ticket(self.category, self.pm, "b")
        self.t3 = _ticket(self.other_cat, self.pm, "c")
        self.url = reverse("tickets:ticket_bulk")

    def post(self, user, action, value, *tickets, next_url="/?priority=high"):
        self.client.force_login(user)
        return self.client.post(self.url, {"ids": [t.pk for t in tickets], "bulk_action": action,
                                           "value": value, "next": next_url})

    def test_bulk_assign_skips_tickets_outside_team(self):
        response = self.post(self.pm, "assign", self.dev.pk, self.t1, self.t2, self.t3)
        self.assertRedirects(response, "/?priority=high", fetch_redirect_response=False)
        for t in (self.t1, self.t2, self.t3):
            t.refresh_from_db()
        self.assertEqual([self.t1.status, self.t2.status, self.t3.status], ["assigned", "assigned", "new"])
        self.assertEqual(self.t1.assigned_to, self.dev)

    def test_bulk_priority(self):
        self.post(self.pm, "priority", "critical", self.t1, self.t2)
        self.assertEqual(set(Ticket.objects.filter(pk__in=[self.t1.pk, self.t2.pk]).values_list("priority", flat=True)), {"critical"})

    def test_developer_has_no_bulk_ui_or_access(self):
        self.client.force_login(self.dev)
        self.assertNotContains(self.client.get(reverse("tickets:ticket_list")), 'form="bulk-form"')
        self.post(self.dev, "status", "in_progress", self.t1)
        self.t1.refresh_from_db()
        self.assertEqual(self.t1.status, "new")

    def test_developer_cannot_bulk_change_priority(self):
        self.post(self.dev, "priority", "critical", self.t1)
        self.t1.refresh_from_db()
        self.assertEqual(self.t1.priority, "medium")

    def test_bulk_status_respects_workflow(self):
        self.post(self.pm, "status", "closed", self.t1)  # NEW → CLOSED зөвшөөрөгдөхгүй
        self.t1.refresh_from_db()
        self.assertEqual(self.t1.status, "new")

    def test_external_next_url_is_ignored(self):
        response = self.post(self.pm, "priority", "high", self.t1, next_url="https://evil.example/")
        self.assertEqual(response["Location"], reverse("tickets:ticket_list"))

    def test_list_has_bulk_checkboxes(self):
        self.client.force_login(self.pm)
        self.assertContains(self.client.get(reverse("tickets:ticket_list")), 'form="bulk-form"')
