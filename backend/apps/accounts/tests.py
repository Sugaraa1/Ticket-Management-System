from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from apps.tickets.models import Ticket
from apps.tickets.permissions import ROLE_ADMIN, ROLE_DEV, ROLE_PM
from apps.tickets.tests.helpers import make_project, make_routed_category, make_user


class UserManagementTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin", ROLE_ADMIN)
        self.client.force_login(self.admin)

    def test_admin_creates_user_with_role(self):
        self.client.post(reverse("accounts:user_create"), {
            "username": "newdev", "email": "n@example.com", "role": ROLE_DEV,
            "password1": "Str0ng-pass-123", "password2": "Str0ng-pass-123",
        })
        user = User.objects.get(username="newdev")
        self.assertTrue(user.groups.filter(name=ROLE_DEV).exists())

    def test_delete_user_without_history(self):
        target = make_user("temp")
        self.client.post(reverse("accounts:user_delete", args=[target.pk]))
        self.assertFalse(User.objects.filter(pk=target.pk).exists())

    def test_user_with_tickets_is_deactivated_not_deleted(self):
        target = make_user("reporter")
        category, _ = make_routed_category()
        Ticket.objects.create(title="t", description="d", ticket_type="bug",
                              category=category, project=make_project(), reported_by=target)
        self.client.post(reverse("accounts:user_delete", args=[target.pk]))
        target.refresh_from_db()
        self.assertFalse(target.is_active)

    def test_non_admin_cannot_access(self):
        self.client.force_login(make_user("dev", ROLE_DEV))
        response = self.client.get(reverse("accounts:user_list"))
        self.assertEqual(response.status_code, 302)

    def test_password_change_page_renders(self):
        response = self.client.get(reverse("password_change"))
        self.assertEqual(response.status_code, 200)


class UserEditTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin", ROLE_ADMIN)
        self.target = make_user("dev", ROLE_DEV)
        self.target.email = "dev@example.com"
        self.target.save()
        self.client.force_login(self.admin)

    def _post(self, user, **overrides):
        data = {"username": user.username, "first_name": "Бат", "last_name": "Дорж",
                "email": user.email or "x@example.com", "role": ROLE_DEV,
                "new_password1": "", "new_password2": ""}
        data.update(overrides)
        return self.client.post(reverse("accounts:user_edit", args=[user.pk]), data)

    def test_admin_edits_info_and_role(self):
        self._post(self.target, role=ROLE_PM)
        self.target.refresh_from_db()
        self.assertEqual(self.target.first_name, "Бат")
        self.assertEqual(list(self.target.groups.values_list("name", flat=True)), [ROLE_PM])

    def test_blank_password_keeps_old_one(self):
        old_hash = self.target.password
        self._post(self.target)
        self.target.refresh_from_db()
        self.assertEqual(self.target.password, old_hash)

    def test_admin_resets_password(self):
        self._post(self.target, new_password1="N3w-strong-pass!", new_password2="N3w-strong-pass!")
        self.target.refresh_from_db()
        self.assertTrue(self.target.check_password("N3w-strong-pass!"))

    def test_duplicate_email_rejected(self):
        make_user("other").__class__.objects.filter(username="other").update(email="o@example.com")
        response = self._post(self.target, email="o@example.com")
        self.assertEqual(response.status_code, 200)
        self.target.refresh_from_db()
        self.assertEqual(self.target.email, "dev@example.com")

    def test_toggle_active_without_email(self):
        self.target.email = ""
        self.target.save()
        self._post(self.target, email="")  # is_active талбар илгээгдээгүй = идэвхгүй
        self.target.refresh_from_db()
        self.assertFalse(self.target.is_active)

    def test_admin_cannot_drop_own_admin_role(self):
        self.admin.email = "a@example.com"
        self.admin.save()
        self._post(self.admin, role=ROLE_DEV)
        self.assertTrue(self.admin.groups.filter(name=ROLE_ADMIN).exists())

    def test_non_superuser_admin_cannot_edit_superuser(self):
        root = User.objects.create_superuser("root", "r@example.com", "x")
        response = self.client.get(reverse("accounts:user_edit", args=[root.pk]))
        self.assertRedirects(response, reverse("accounts:user_list"))

    def test_non_admin_cannot_edit(self):
        self.client.force_login(self.target)
        response = self._post(self.target, role=ROLE_ADMIN)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(self.target.groups.filter(name=ROLE_ADMIN).exists())


class ActiveStatusTests(TestCase):
    def setUp(self):
        self.admin = make_user("admin", ROLE_ADMIN)
        self.client.force_login(self.admin)

    def test_deactivate_button_blocks_login_but_keeps_user(self):
        target = make_user("dev", ROLE_DEV)
        self.client.post(reverse("accounts:user_deactivate", args=[target.pk]))
        target.refresh_from_db()
        self.assertFalse(target.is_active)

    def test_cannot_deactivate_self(self):
        self.client.post(reverse("accounts:user_deactivate", args=[self.admin.pk]))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_inactive_member_not_assignable(self):
        from apps.tickets.permissions import team_members_with_workload

        active, inactive = make_user("a", ROLE_DEV), make_user("b", ROLE_DEV)
        inactive.is_active = False
        inactive.save()
        _category, team = make_routed_category(members=[active, inactive])
        self.assertEqual(list(team_members_with_workload(team)), [active])

    def test_inactive_project_hidden_from_ticket_form(self):
        from apps.projects.models import Project
        from apps.tickets.forms import TicketForm

        make_project("Live")
        Project.objects.create(name="Old", is_active=False)
        names = [p.name for p in TicketForm().fields["project"].queryset]
        self.assertEqual(names, ["Live"])


import shutil
import tempfile
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

_MEDIA = tempfile.mkdtemp()


def _png(size=(400, 300)):
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", size, "orange").save(buffer, format="PNG")
    return SimpleUploadedFile("me.png", buffer.getvalue(), content_type="image/png")


@override_settings(MEDIA_ROOT=_MEDIA)
class AvatarTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_MEDIA, ignore_errors=True)

    def setUp(self):
        self.user = make_user("dev", ROLE_DEV)
        self.client.force_login(self.user)
        self.url = reverse("accounts:avatar_update")

    def test_upload_crops_to_square_and_shows_on_profile(self):
        from PIL import Image

        self.client.post(self.url, {"avatar": _png()})
        self.user.refresh_from_db()
        with Image.open(self.user.profile.avatar.path) as image:
            self.assertEqual(image.size, (256, 256))
        response = self.client.get(reverse("tickets:dashboard"))
        self.assertContains(response, self.user.profile.avatar.url)

    def test_non_image_rejected(self):
        bogus = SimpleUploadedFile("x.png", b"not an image", content_type="image/png")
        self.client.post(self.url, {"avatar": bogus})
        self.user.refresh_from_db()
        self.assertFalse(hasattr(self.user, "profile") and self.user.profile.avatar)

    def test_remove_avatar(self):
        self.client.post(self.url, {"avatar": _png()})
        self.client.post(self.url, {"action": "remove"})
        self.user.refresh_from_db()
        self.assertFalse(self.user.profile.avatar)

    def test_requires_login(self):
        self.client.logout()
        response = self.client.post(self.url, {"avatar": _png()})
        self.assertEqual(response.status_code, 302)
        self.assertFalse(hasattr(User.objects.get(pk=self.user.pk), "profile"))


class PasswordResetTests(TestCase):
    def setUp(self):
        self.user = make_user("dev", ROLE_DEV)
        self.user.email = "dev@example.com"
        self.user.save()

    def test_full_reset_flow(self):
        import re

        from django.core import mail

        self.assertContains(self.client.get(reverse("login")), reverse("password_reset"))
        self.client.post(reverse("password_reset"), {"email": "dev@example.com"})
        self.assertEqual(len(mail.outbox), 1)
        link = re.search(r"https?://[^/]+(/\S+)", mail.outbox[0].body).group(1)
        response = self.client.get(link, follow=True)  # token-ийг session руу шилжүүлж redirect хийнэ
        self.assertTrue(response.context["validlink"])
        self.client.post(response.redirect_chain[-1][0], {
            "new_password1": "Br4nd-new-pass!", "new_password2": "Br4nd-new-pass!",
        })
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Br4nd-new-pass!"))

    def test_unknown_email_does_not_reveal_anything(self):
        from django.core import mail

        response = self.client.post(reverse("password_reset"), {"email": "nobody@example.com"})
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertEqual(len(mail.outbox), 0)

    def test_invalid_link_shows_message(self):
        response = self.client.get(reverse("password_reset_confirm", args=["MQ", "bad-token"]))
        self.assertFalse(response.context["validlink"])
        self.assertContains(response, reverse("password_reset"))


class CreateUserWithoutEmailTests(TestCase):
    def test_admin_creates_user_without_email(self):
        self.client.force_login(make_user("admin", ROLE_ADMIN))
        self.client.post(reverse("accounts:user_create"), {
            "username": "noemail", "email": "", "role": ROLE_DEV,
            "password1": "Str0ng-pass-123", "password2": "Str0ng-pass-123",
        })
        self.assertTrue(User.objects.filter(username="noemail", email="").exists())
