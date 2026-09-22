def user_roles_context(request):
    """
    Бүх template-д 'can_manage_catalog' хувьсагчийг дамжуулна:
    Category/Team/Project удирдах цэсийг зөвхөн PM/Admin-д харуулахад ашиглана.
    """
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}

    from apps.tickets.permissions import ROLE_ADMIN, ROLE_PM, user_roles

    roles = user_roles(request.user)
    return {"can_manage_catalog": bool(roles & {ROLE_PM, ROLE_ADMIN})}
