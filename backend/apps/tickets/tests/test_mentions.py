from django.core import mail
from django.test import TestCase
from django.urls import reverse

from apps.tickets.models import Ticket
from apps.tickets.permissions import ROLE_DEV, ROLE_PM

from .helpers import make_project, make_routed_category, make_user


def user(name, role=ROLE_DEV):
    u = make_user(name, role)
    u.email = f"{name}@example.com"
    u.save()
    return u


class MentionNotificationTests(TestCase):
    def setUp(self):
        self.reporter, self.dev, self.watcher = user("rep"), user("dev"), user("bat")
        self.pm = user("pm", ROLE_PM)
        self.outsider = user("outsider")
        category, self.team = make_routed_category(members=[self.dev])
        self.ticket = Ticket.objects.create(
            title="Login", description="d", ticket_type="bug", category=category,
            project=make_project(), reported_by=self.reporter,
        )
        self.url = reverse("tickets:ticket_detail", args=[self.ticket.pk])

    def post(self, who, **data):
        self.client.force_login(who)
        return self.client.post(self.url, data)

    def inbox(self, who):
        """Тухайн хүнд очсон мэйлүүдийн гарчиг."""
        return [m.subject for m in mail.outbox if who.email in m.to]

    def test_mention_gets_specific_notification_once(self):
        self.post(self.dev, action="comment", body="@bat can you check?")
        titles = self.inbox(self.watcher)
        self.assertEqual(len(titles), 1)
        self.assertIn("дурдлаа", titles[0])
        detail = self.client.get(self.url)
        self.assertContains(detail, '<span class="tms-mention">@bat</span>', html=True)

    def test_internal_note_mention_skips_people_who_cannot_see_it(self):
        self.post(self.dev, action="comment", body="@outsider secret", is_internal="on")
        self.assertFalse(self.inbox(self.outsider))

    def test_comment_is_escaped(self):
        self.post(self.dev, action="comment", body="<script>alert(1)</script> @bat")
        self.assertNotContains(self.client.get(self.url), "<script>alert(1)</script>")

    def test_comment_notifies_reporter_not_author(self):
        self.post(self.dev, action="comment", body="Fixed on staging")
        self.assertTrue(self.inbox(self.reporter))
        self.assertFalse(self.inbox(self.dev))
