"""Кодын шалгалтаар илэрсэн алдаануудын regression тестүүд."""
from django.test import TestCase
from django.urls import reverse

from apps.tickets.exports import _csv_value
from apps.tickets.models import StatusHistory, Ticket
from apps.tickets.permissions import ROLE_DEV, ROLE_PM, ROLE_QA

from .helpers import make_project, make_routed_category, make_user


class ReviewFixTests(TestCase):
    def setUp(self):
        self.dev = make_user("dev", ROLE_DEV)
        self.dev2 = make_user("dev2", ROLE_DEV)
        self.qa = make_user("qa", ROLE_QA)
        self.lead = make_user("lead", ROLE_PM)
        self.category, self.team = make_routed_category(
            team_lead=self.lead, qa_tester=self.qa, members=[self.dev, self.dev2]
        )
        self.ticket = Ticket.objects.create(
            title="x", description="d", ticket_type="bug", category=self.category,
            project=make_project(), reported_by=self.dev,
        )
        self.url = reverse("tickets:ticket_detail", args=[self.ticket.pk])

    def _to(self, *statuses):
        for status in statuses:
            if status == "assigned":
                self.ticket.assigned_to = self.dev
            self.ticket.transition_to(status)

    def test_empty_comment_is_rejected(self):
        self.client.force_login(self.dev)
        self.client.post(self.url, {"action": "comment", "body": ""})
        self.assertFalse(self.ticket.comments.exists())

    def test_other_team_qa_cannot_close(self):
        self._to("assigned", "in_progress", "resolved", "qa_test")
        self.client.force_login(make_user("qa_other", ROLE_QA))
        self.client.post(self.url, {"action": "transition", "new_status": "closed"})
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, "qa_test")

    def test_team_qa_can_close(self):
        self._to("assigned", "in_progress", "resolved", "qa_test")
        self.client.force_login(self.qa)
        self.client.post(self.url, {"action": "transition", "new_status": "closed"})
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.status, "closed")

    def test_team_lead_reassigns_to_active_member(self):
        self._to("assigned", "in_progress")
        self.client.force_login(self.lead)
        self.client.post(self.url, {"action": "reassign", "assigned_to": self.dev2.pk})
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assigned_to, self.dev2)
        self.assertEqual(self.ticket.status, "in_progress")
        self.assertTrue(self.ticket.comments.filter(body__contains="dev2").exists())

    def test_cannot_reassign_to_inactive_or_outsider(self):
        self._to("assigned")
        self.dev2.is_active = False
        self.dev2.save()
        self.client.force_login(self.lead)
        for target in (self.dev2, make_user("outsider", ROLE_DEV)):
            self.client.post(self.url, {"action": "reassign", "assigned_to": target.pk})
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assigned_to, self.dev)

    def test_developer_cannot_reassign(self):
        self._to("assigned")
        self.client.force_login(self.dev)
        self.client.post(self.url, {"action": "reassign", "assigned_to": self.dev2.pk})
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.assigned_to, self.dev)

    def test_resolution_uses_latest_close(self):
        from apps.tickets.reports import _closed_at_subquery

        self._to("assigned", "in_progress", "resolved", "qa_test", "closed")
        first = StatusHistory.objects.get(ticket=self.ticket, to_status="closed").changed_at
        # Шинэ "хаалт" бичлэг (дахин хаасан) нэмнэ.
        later = StatusHistory.objects.create(ticket=self.ticket, from_status="qa_test", to_status="closed")
        closed_at = Ticket.objects.annotate(c=_closed_at_subquery()).get(pk=self.ticket.pk).c
        self.assertEqual(closed_at, later.changed_at)
        self.assertGreaterEqual(closed_at, first)

    def test_formula_injection_is_neutralised(self):
        self.assertEqual(_csv_value("=HYPERLINK(1)"), "'=HYPERLINK(1)")
        self.assertEqual(_csv_value("Normal"), "Normal")

    def test_admin_page_redirects_to_login_with_next(self):
        response = self.client.get(reverse("accounts:user_list"))
        self.assertIn("next=", response["Location"])


class DeveloperTransitionScopeTests(TestCase):
    def setUp(self):
        self.dev = make_user("dev", ROLE_DEV)
        self.other_dev = make_user("other", ROLE_DEV)
        self.pm = make_user("pm", ROLE_PM)
        category, _team = make_routed_category(members=[self.dev, self.other_dev])
        self.ticket = Ticket.objects.create(
            title="x", description="d", ticket_type="bug", category=category,
            project=make_project(), reported_by=self.pm, assigned_to=self.dev,
        )
        self.url = reverse("tickets:ticket_detail", args=[self.ticket.pk])

    def _move(self, *statuses):
        for status in statuses:
            self.ticket.transition_to(status)

    def _post(self, user, status):
        self.client.force_login(user)
        self.client.post(self.url, {"action": "transition", "new_status": status})
        self.ticket.refresh_from_db()
        return self.ticket.status

    def test_other_developer_cannot_send_to_qa(self):
        self._move("assigned", "in_progress", "resolved")
        self.assertEqual(self._post(self.other_dev, "qa_test"), "resolved")
        self.assertEqual(self._post(self.dev, "qa_test"), "qa_test")

    def test_other_developer_cannot_start_or_resolve(self):
        self._move("assigned")
        self.assertEqual(self._post(self.other_dev, "in_progress"), "assigned")

    def test_pm_can_reject_in_progress_ticket(self):
        self._move("assigned", "in_progress")
        self.assertEqual(self._post(self.pm, "rejected"), "rejected")

    def test_pm_cannot_do_developer_work(self):
        self._move("assigned")
        self.assertEqual(self._post(self.pm, "in_progress"), "assigned")


class SecondReviewFixTests(TestCase):
    def setUp(self):
        self.pm = make_user("pm", ROLE_PM)
        self.dev = make_user("dev", ROLE_DEV)

    def test_orphan_tickets_are_routed_when_category_gets_team(self):
        from apps.categories.models import Category

        orphan_cat = Category.objects.create(name="Orphan")
        ticket = Ticket.objects.create(
            title="o", description="d", ticket_type="bug", category=orphan_cat,
            project=make_project(), reported_by=self.dev,
        )
        _cat, team = make_routed_category(team_lead=self.pm, members=[self.dev], name="X")
        self.client.force_login(self.pm)
        self.client.post(reverse("categories:category_edit", args=[orphan_cat.pk]),
                         {"name": "Orphan", "description": "", "teams": [team.pk]})
        ticket.refresh_from_db()
        self.assertEqual(ticket.team, team)

    def test_creating_ticket_in_teamless_category_warns(self):
        from apps.categories.models import Category

        category = Category.objects.create(name="NoTeam")
        self.client.force_login(self.dev)
        response = self.client.post(reverse("tickets:ticket_create"), {
            "title": "n", "ticket_type": "bug", "priority": "medium",
            "category": category.pk, "project": make_project().pk, "description": "d",
        }, follow=True)
        self.assertTrue(any("баг тохируулаагүй" in str(m) for m in response.context["messages"]))

    def test_inactive_team_qa_does_not_block_other_qa(self):
        qa, other_qa = make_user("qa", ROLE_QA), make_user("qa2", ROLE_QA)
        category, _team = make_routed_category(qa_tester=qa, members=[self.dev])
        ticket = Ticket.objects.create(
            title="x", description="d", ticket_type="bug", category=category,
            project=make_project(), reported_by=self.pm, assigned_to=self.dev,
        )
        for status in ("assigned", "in_progress", "resolved", "qa_test"):
            ticket.transition_to(status)
        qa.is_active = False
        qa.save()
        self.client.force_login(other_qa)
        self.client.post(reverse("tickets:ticket_detail", args=[ticket.pk]),
                         {"action": "transition", "new_status": "closed"})
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, "closed")
