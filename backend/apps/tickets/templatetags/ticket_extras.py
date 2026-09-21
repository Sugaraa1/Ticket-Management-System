from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Template дотор {{ mydict|get_item:variable_key }} гэж динамик key-ээр dict-ээс утга авна."""
    if not dictionary:
        return 0
    return dictionary.get(key, 0)
