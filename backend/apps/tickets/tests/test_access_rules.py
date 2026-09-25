from io import StringIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.categories.forms import TeamForm
from apps.tickets.models import Attachment, Comment, Ticket
from apps.tickets.permissions import ROLE_DEV, ROLE_QA

from .helpers import make_project, make_routed_category, make_user


class AccessRuleTests(TestCase):
    def setUp(self):
        self.lead = make_user("lead", ROLE_DEV)  # PM биш Team Lead
        self.dev = make_user("dev", ROLE_DEV)
        self.dev2 = make_user("dev2", ROLE_DEV)
        self.outsider = make_user("outsider", ROLE_QA)
        self.category, self.team = make_routed_category(team_lead=self.lead, members=[self.dev, self.dev2])
        self.ticket = Ticket.objects.create(
            title="x", description="d", ticket_type="bug", category=self.category,
            project=make_project(), reported_by=self.outsider,
        )
        self.url = reverse("tickets:ticket_detail", args=[self.ticket.pk])

    # --- 5. Team Lead: any user
    def test_team_form_accepts_any_active_user_as_lead(self):
        form = TeamForm(data={"name": "New", "team_lead": self.dev.pk})
        self.assertTrue(form.is_valid(), form.errors)

    def test_non_pm_team_lead_can_assign_and_change_priority(self):
        self.client.force_login(self.lead)
        self.client.post(self.url, {"action": "transition", "new_status": "assigned", "assigned_to": self.dev.pk})
        self.client.post(self.url, {"action": "priority", "priority": "high"})
        self.ticket.refresh_from_db()
        self.assertEqual((self.ticket.status, self.ticket.assigned_to, self.ticket.priority), ("assigned", self.dev, "high"))

    def test_team_lead_rights_do_not_leak_to_other_teams(self):
        other_cat, _team = make_routed_category(name="Other", members=[self.dev])
        other = Ticket.objects.create(
            title="y", description="d", ticket_type="bug", category=other_cat,
            project=make_project("P2"), reported_by=self.dev,
        )
        self.client.force_login(self.lead)
        self.client.post(reverse("tickets:ticket_detail", args=[other.pk]),
                         {"action": "transition", "new_status": "assigned", "assigned_to": self.dev.pk})
        other.refresh_from_db()
        self.assertEqual(other.status, "new")

    # --- 3. Internal notes
    def test_internal_note_hidden_from_reporter_outside_team(self):
        Comment.objects.create(ticket=self.ticket, author=self.dev, body="secret", is_internal=True)
        Comment.objects.create(ticket=self.ticket, author=self.dev, body="public")
        self.client.force_login(self.outsider)
        response = self.client.get(self.url)
        self.assertNotContains(response, "secret")
        self.assertContains(response, "public")
        self.assertNotContains(response, 'name="is_internal"')

    def test_outsider_cannot_post_internal_note(self):
        self.client.force_login(self.outsider)
        self.client.post(self.url, {"action": "comment", "body": "hi", "is_internal": "on"})
        self.assertFalse(self.ticket.comments.get(body="hi").is_internal)

    def test_team_member_sees_internal_note(self):
        Comment.objects.create(ticket=self.ticket, author=self.dev, body="secret", is_internal=True)
        self.client.force_login(self.dev2)
        self.assertContains(self.client.get(self.url), "secret")

    # --- 2. Private attachments
    def test_attachment_requires_login_and_is_not_under_media(self):
        attachment = Attachment.objects.create(
            ticket=self.ticket, uploaded_by=self.dev,
            file=SimpleUploadedFile("notes.txt", b"hello"),
        )
        self.addCleanup(attachment.file.delete, save=False)
        from django.conf import settings

        self.assertFalse(attachment.file.path.startswith(str(settings.MEDIA_ROOT) + "/"))
        url = reverse("tickets:attachment_download", args=[attachment.pk])
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.dev)
        response = self.client.get(url)
        self.assertEqual(b"".join(response.streaming_content), b"hello")

    # --- 1. Scheduler
    def test_scheduler_once_runs_both_jobs(self):
        out = StringIO()
        call_command("run_scheduler", once=True, stdout=out)
        self.assertIn("SLA", out.getvalue())
        self.assertIn("сануулга", out.getvalue())
