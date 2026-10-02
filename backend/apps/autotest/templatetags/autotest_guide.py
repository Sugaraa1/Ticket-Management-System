from django import template

register = template.Library()


@register.inclusion_tag("autotest/_workflow_panel.html")
def workflow_panel(flow):
    """guide.py-ийн flow-г баруун талын самбараар харуулна (товч нь _workflow_button.html)."""
    return {"flow": flow}
