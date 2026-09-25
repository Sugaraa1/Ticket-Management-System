from django import template
from django.utils.html import format_html

register = template.Library()


def avatar_url(user):
    profile = getattr(user, "profile", None) if user else None
    try:
        return profile.avatar.url if profile and profile.avatar else ""
    except ValueError:
        return ""


@register.simple_tag
def user_avatar(user, css_class="tms-avatar"):
    """Профайлын зураг байвал <img>, үгүй бол нэрийн эхний 2 үсэг."""
    if not user:
        return ""
    url = avatar_url(user)
    if url:
        return format_html(
            '<span class="{} has-image"><img src="{}" alt="{}"></span>', css_class, url, user.username
        )
    return format_html('<span class="{}">{}</span>', css_class, user.username[:2].upper())
