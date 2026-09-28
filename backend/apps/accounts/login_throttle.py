"""
Нэвтрэх оролдлогын хязгаар (docs/rules.md — AUTH-08, OWASP ASVS 2.2.1).

Нэг хэрэглэгчийн нэр + IP-ээс LOGIN_FAILURE_LIMIT удаа буруу оролдвол
LOGIN_LOCKOUT_MINUTES минут нэвтрүүлэхгүй (зөв нууц үгтэй байсан ч). IP-г түлхүүрт
оруулсан нь халдагч бусдын account-ыг санаатайгаар түгжихээс сэргийлнэ.
Тоолуурыг Django cache-д хадгална (production-д олон процесс хуваалцах cache хэрэгтэй).
"""
from django import forms
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm
from django.core.cache import cache
from django.utils.translation import gettext_lazy as _


def _limit():
    return getattr(settings, "LOGIN_FAILURE_LIMIT", 5)


def _lockout_seconds():
    return getattr(settings, "LOGIN_LOCKOUT_MINUTES", 15) * 60


def _key(request, username):
    ip = request.META.get("REMOTE_ADDR", "") if request else ""
    return f"login-failures:{(username or '').strip().lower()}:{ip}"


class ThrottledAuthenticationForm(AuthenticationForm):
    error_messages = {
        **AuthenticationForm.error_messages,
        "locked": _("Олон удаа буруу оролдсон тул %(minutes)s минутын дараа дахин оролдоно уу."),
    }

    locked_out = False

    def clean(self):
        key = _key(self.request, self.cleaned_data.get("username"))
        if cache.get(key, 0) >= _limit():
            self.locked_out = True
            raise forms.ValidationError(
                self.error_messages["locked"],
                code="locked",
                params={"minutes": getattr(settings, "LOGIN_LOCKOUT_MINUTES", 15)},
            )
        try:
            cleaned = super().clean()
        except forms.ValidationError:
            # Сүүлийн буруу оролдлогоос хойш хугацаа тоологдоно.
            cache.set(key, cache.get(key, 0) + 1, _lockout_seconds())
            raise
        cache.delete(key)
        return cleaned
