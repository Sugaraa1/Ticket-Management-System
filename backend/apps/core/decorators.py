from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect
from django.utils.translation import gettext as _


def roles_required(*roles):
    """
    Тухайн view-г зөвхөн заасан Group-уудын аль нэгэнд багтсан хэрэглэгч
    үзэх боломжтой болгоно. Жишээ: @roles_required(ROLE_PM, ROLE_ADMIN)
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("login")

            from apps.tickets.permissions import user_roles

            if not user_roles(request.user) & set(roles):
                messages.error(request, _("Танд энэ хуудсанд хандах эрх байхгүй."))
                return redirect("tickets:dashboard")
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator
