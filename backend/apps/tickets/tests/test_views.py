from django.test import TestCase
from django.urls import reverse

from apps.tickets.models import Ticket

from .helpers import make_project, make_routed_category, make_user


class TicketListPaginationTests(TestCase):
    def setUp(self):
        self.user = make_user("viewer")
        self.category, self.team = make_routed_category()
        self.project = make_project()
        for i in range(30):
            Ticket.objects.create(
                title=f"Ticket {i}",
                description="d",
                ticket_type=Ticket.TicketType.TASK,
                category=self.category,
                project=self.project,
                reported_by=self.user,
            )
        self.client.force_login(self.user)

    def test_first_page_has_default_page_size(self):
        response = self.client.get(reverse("tickets:ticket_list"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["tickets"]), 25)
        self.assertTrue(response.context["page_obj"].has_next())

    def test_second_page_has_remaining_items(self):
        response = self.client.get(reverse("tickets:ticket_list"), {"page": 2})
        self.assertEqual(len(response.context["tickets"]), 5)
        self.assertFalse(response.context["page_obj"].has_next())

    def test_out_of_range_page_returns_last_page(self):
        response = self.client.get(reverse("tickets:ticket_list"), {"page": 999})
        self.assertEqual(response.status_code, 200)
        page_obj = response.context["page_obj"]
        self.assertEqual(page_obj.number, page_obj.paginator.num_pages)

    def test_non_numeric_page_returns_first_page(self):
        response = self.client.get(reverse("tickets:ticket_list"), {"page": "abc"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["page_obj"].number, 1)

    def test_filters_preserved_in_querystring_for_pagination_links(self):
        response = self.client.get(
            reverse("tickets:ticket_list"), {"status": "new", "page": 1}
        )
        self.assertIn("status=new", response.context["querystring"])
        self.assertNotIn("page=", response.context["querystring"])

    def test_requires_login(self):
        self.client.logout()
        response = self.client.get(reverse("tickets:ticket_list"))
        self.assertEqual(response.status_code, 302)
