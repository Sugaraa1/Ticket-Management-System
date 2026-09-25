from datetime import timedelta

from django.test import TestCase
from django.urls import reverse

from apps.tickets.models import Ticket
from apps.tickets.permissions import ROLE_DEV, ROLE_PM

from .helpers import make_project, make_routed_category, make_user


class PriorityChangeTests(TestCase):
    def setUp(self):
        self.pm = make_user("pm", ROLE_PM)
        self.dev = make_user("dev", ROLE_DEV)
        self.category, _ = make_routed_category()
        self.ticket = Ticket.objects.create(
            title="X",
            description="d",
            ticket_type=Ticket.TicketType.BUG,
            category=self.category,
            project=make_project(),
            reported_by=self.dev,
            priority=Ticket.Priority.LOW,
        )

    def test_change_priority_recalculates_sla_from_creation(self):
        self.ticket.sla_warning_sent_at = self.ticket.created_at
        self.ticket.save(update_fields=["sla_warning_sent_at"])

        self.assertTrue(self.ticket.change_priority(Ticket.Priority.CRITICAL, user=self.pm))
        self.ticket.refresh_from_db()

        self.assertEqual(self.ticket.sla_due_at, self.ticket.created_at + timedelta(hours=4))
        self.assertEqual(
            self.ticket.first_response_due_at, self.ticket.created_at + timedelta(hours=1)
        )
        self.assertIsNone(self.ticket.sla_warning_sent_at)
        self.assertTrue(self.ticket.comments.filter(author=self.pm).exists())

    def test_same_priority_is_noop(self):
        self.assertFalse(self.ticket.change_priority(Ticket.Priority.LOW, user=self.pm))
        self.assertFalse(self.ticket.comments.exists())

    def test_developer_cannot_change_priority_via_view(self):
        self.client.force_login(self.dev)
        self.client.post(
            reverse("tickets:ticket_detail", args=[self.ticket.pk]),
            {"action": "priority", "priority": Ticket.Priority.CRITICAL},
        )
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.priority, Ticket.Priority.LOW)

    def test_pm_can_change_priority_via_view(self):
        self.client.force_login(self.pm)
        self.client.post(
            reverse("tickets:ticket_detail", args=[self.ticket.pk]),
            {"action": "priority", "priority": Ticket.Priority.HIGH},
        )
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.priority, Ticket.Priority.HIGH)


class ProfilePageTests(TestCase):
    def setUp(self):
        self.dev = make_user("dev", ROLE_DEV)
        self.other = make_user("other")
        self.category, _ = make_routed_category()
        project = make_project()
        common = dict(
            description="d",
            ticket_type=Ticket.TicketType.TASK,
            category=self.category,
            project=project,
        )
        self.mine = Ticket.objects.create(title="Mine", reported_by=self.other, assigned_to=self.dev, **common)
        self.reported = Ticket.objects.create(title="Reported", reported_by=self.dev, **common)
        self.unrelated = Ticket.objects.create(title="Unrelated", reported_by=self.other, **common)

    def test_profile_shows_only_my_tickets(self):
        self.client.force_login(self.dev)
        response = self.client.get(reverse("tickets:dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.mine, response.context["assigned_active"])
        self.assertIn(self.reported, response.context["reported_open"])
        self.assertNotContains(response, "Unrelated")
        self.assertEqual(response.context["stats"]["assigned_active"], 1)

    def test_list_and_drawer_render(self):
        self.client.force_login(self.dev)
        response = self.client.get(reverse("tickets:ticket_list"))
        self.assertContains(response, 'id="quickTicket"')
        self.assertContains(response, self.mine.reported_by.username)


class QueueAndAttachmentTests(TestCase):
    def test_qa_tester_sees_qa_queue(self):
        from apps.tickets.queues import qa_queue

        qa = make_user("qa")
        category, team = make_routed_category(qa_tester=qa)
        t = Ticket.objects.create(
            title="Q", description="d", ticket_type=Ticket.TicketType.BUG,
            category=category, project=make_project(), reported_by=qa,
        )
        Ticket.objects.filter(pk=t.pk).update(status=Ticket.Status.QA_TEST)
        self.assertIn(t, qa_queue(qa))

    def test_oversized_attachment_rejected(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.test import override_settings

        from apps.tickets.forms import AttachmentForm

        with override_settings(ATTACHMENT_MAX_SIZE_MB=0):
            form = AttachmentForm(files={"file": SimpleUploadedFile("a.pdf", b"xx")})
            self.assertFalse(form.is_valid())
        form = AttachmentForm(files={"file": SimpleUploadedFile("a.exe", b"xx")})
        self.assertFalse(form.is_valid())


class MyTeamPageTests(TestCase):
    def test_no_team_shows_empty_message(self):
        self.client.force_login(make_user("loner"))
        response = self.client.get(reverse("tickets:my_team"))
        self.assertContains(response, "Танд одоогоор баг алга байна.")

    def test_member_sees_team(self):
        dev = make_user("dev", ROLE_DEV)
        _, team = make_routed_category(members=[dev])
        self.client.force_login(dev)
        response = self.client.get(reverse("tickets:my_team"))
        self.assertContains(response, team.name)
