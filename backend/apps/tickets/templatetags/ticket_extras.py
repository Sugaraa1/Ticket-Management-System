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
