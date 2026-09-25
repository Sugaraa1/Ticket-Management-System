def user_roles_context(request):
    """
    Бүх template-д 'can_manage_catalog' хувьсагчийг дамжуулна:
    Category/Team/Project удирдах цэсийг зөвхөн PM/Admin-д харуулахад ашиглана.
    """
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}

    from apps.tickets.permissions import ROLE_ADMIN, ROLE_PM, has_global_reports, user_roles

    roles = user_roles(request.user)
    return {
        "can_manage_catalog": bool(roles & {ROLE_PM, ROLE_ADMIN}),
        "is_admin": ROLE_ADMIN in roles,
        "can_view_dashboard": has_global_reports(request.user),
    }


def quick_ticket_context(request):
    """Navbar/жагсаалтын "+" товчоор нээгддэг хажуугийн (offcanvas) ticket үүсгэх маягт."""
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}

    from apps.tickets.forms import TicketForm
    from apps.tickets.views import _modules_by_project

    from apps.tickets.queues import action_count

    return {
        "my_action_count": action_count(request.user),
        "quick_ticket_form": TicketForm(auto_id="qt_%s"),
        "quick_modules_by_project": _modules_by_project(),
    }
