"""
Нэвтрэлт ба аюулгүй байдлын дүрмүүд (docs/rules.md — AUTH-*, SEC-*).

Эх сурвалж: NIST SP 800-63B (нууц үг), OWASP ASVS 4.0 V2 (нэвтрэлт), V3 (session),
V5 (redirect), V13/V14 (CSRF, HTTP header).
"""
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.test import Client, TestCase
from django.urls import reverse

from apps.tickets.tests.helpers import make_user


def password_errors(password, user=None):
    try:
        validate_password(password, user=user)
    except ValidationError as exc:
        return exc.messages
    return []


class PasswordPolicyTests(TestCase):
    """NIST SP 800-63B §5.1.1.2 — урт, нийтлэг нууц үгийн шалгалт; найрлагын дүрэм шаардахгүй."""

    def test_short_password_rejected(self):
        """[AUTH-01] Password shorter than 8 characters is rejected"""
        self.assertTrue(password_errors("Tq9#mZ4"))

    def test_eight_characters_accepted(self):
        """[AUTH-01] Strong password of exactly 8 characters is accepted"""
        self.assertEqual(password_errors("Tq9#mZ4p"), [])

    def test_common_password_rejected(self):
        """[AUTH-02] Common password is rejected"""
        self.assertTrue(password_errors("password123"))

    def test_numeric_only_rejected(self):
        """[AUTH-03] Numeric-only password is rejected"""
        self.assertTrue(password_errors("48151623429"))

    def test_similar_to_username_rejected(self):
        """[AUTH-04] Password similar to the username is rejected"""
        user = make_user("batbayar.dorj")
        self.assertTrue(password_errors("batbayar.dorj1", user=user))

    def test_long_passphrase_accepted(self):
        """[AUTH-05] Long passphrase (up to 64 characters) is accepted"""
        self.assertEqual(password_errors("миний нууц үг бол урт өгүүлбэр " * 2 + "Foxt"), [])

    def test_no_forced_composition_rules(self):
        """[AUTH-06] Long uncommon password is accepted without symbols/uppercase (NIST)"""
        self.assertEqual(password_errors("ногоон морь тэнгэрт нисэв"), [])

    def test_error_messages_are_in_mongolian(self):
        """[AUTH-07] Password validation messages are shown in Mongolian"""
        for message in password_errors("abc"):
            with self.subTest(message=message):
                self.assertNotRegex(message, r"[A-Za-z]{4,}")


class LoginRulesTests(TestCase):
    def setUp(self):
        self.user = make_user("bat", password="Tq9#mZ4pX")
        self.url = reverse("login")
        # Буруу оролдлогын тоолуур cache-д хадгалагддаг — тест хооронд цэвэрлэнэ.
        cache.clear()
        self.addCleanup(cache.clear)

    def _login(self, password, **extra):
        return self.client.post(self.url, {"username": "bat", "password": password, **extra})

    def test_repeated_failed_logins_are_throttled(self):
        """[AUTH-08] Login is temporarily locked after 5 failed attempts"""
        for _ in range(5):
            self._login("буруу")
        self._login("Tq9#mZ4pX")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_lockout_message_and_other_users_unaffected(self):
        """[AUTH-08] Locked-out user sees a wait message; other users can still log in"""
        for _ in range(5):
            self._login("буруу")
        response = self._login("Tq9#mZ4pX")
        self.assertContains(response, "минутын дараа дахин оролдоно уу")
        make_user("saraa", password="Tq9#mZ4pX")
        self.client.post(self.url, {"username": "saraa", "password": "Tq9#mZ4pX"})
        self.assertIn("_auth_user_id", self.client.session)

    def test_successful_login_resets_failure_count(self):
        """[AUTH-08] A successful login resets the failed-attempt counter"""
        for _ in range(4):
            self._login("буруу")
        self._login("Tq9#mZ4pX")
        self.client.logout()
        for _ in range(4):
            self._login("буруу")
        self._login("Tq9#mZ4pX")
        self.assertIn("_auth_user_id", self.client.session)

    def test_external_next_redirect_is_ignored(self):
        """[AUTH-09] No redirect to an external site after login (?next=https://evil.com)"""
        response = self._login("Tq9#mZ4pX", next="https://evil.example.com/")
        self.assertEqual(response.status_code, 302)
        self.assertFalse(response["Location"].startswith("https://evil.example.com"))

    def test_logout_ends_session(self):
        """[AUTH-10] Protected pages are inaccessible after logout"""
        self.client.force_login(self.user)
        self.client.post(reverse("logout"))
        response = self.client.get(reverse("tickets:ticket_list"))
        self.assertEqual(response.status_code, 302)


class SecurityBaselineTests(TestCase):
    def setUp(self):
        self.user = make_user("bat")

    def test_post_without_csrf_token_is_rejected(self):
        """[SEC-01] POST without CSRF token is rejected (403)"""
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(reverse("tickets:ticket_create"), {"title": "x"})
        self.assertEqual(response.status_code, 403)

    def test_nosniff_header(self):
        """[SEC-02] Browser MIME sniffing is disabled (X-Content-Type-Options: nosniff)"""
        response = self.client.get(reverse("login"))
        self.assertEqual(response.get("X-Content-Type-Options"), "nosniff")

    def test_clickjacking_header(self):
        """[SEC-03] Site cannot be framed by other sites (X-Frame-Options: DENY)"""
        response = self.client.get(reverse("login"))
        self.assertEqual(response.get("X-Frame-Options"), "DENY")

    def test_every_page_requires_login(self):
        """[SEC-05] Anonymous users cannot access any internal page"""
        names = [
            "tickets:ticket_list", "tickets:dashboard", "tickets:my_team", "tickets:ticket_create",
            "tickets:reports", "accounts:user_list", "categories:category_list",
            "categories:team_list", "projects:project_list",
        ]
        for name in names:
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response["Location"])
