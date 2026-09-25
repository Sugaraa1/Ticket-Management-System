from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Template дотор {{ mydict|get_item:variable_key }} гэж динамик key-ээр dict-ээс утга авна."""
    if not dictionary:
        return 0
    return dictionary.get(key, 0)


@register.filter
def status_label(value):
    """Status slug (жишээ нь 'in_progress')-ийг Монгол label ('Хийгдэж байгаа') болгож хөрвүүлнэ."""
    if not value:
        return "—"
    from apps.tickets.models import Ticket

    try:
        return Ticket.Status(value).label
    except ValueError:
        return value


@register.filter
def basename(path):
    """'attachments/2026/09/report.pdf' -> 'report.pdf'."""
    return str(path).rsplit("/", 1)[-1] if path else ""


@register.filter
def with_mentions(text):
    """Сэтгэгдлийг escape хийж, @username-ийг тодруулж, мөр шилжилтийг <br> болгоно."""
    from django.utils.html import escape
    from django.utils.safestring import mark_safe

    from apps.tickets.notifications import MENTION_RE

    html = MENTION_RE.sub(r'<span class="tms-mention">@\1</span>', escape(text or ""))
    return mark_safe(html.replace("\n", "<br>"))
