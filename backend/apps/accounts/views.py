from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.decorators import roles_required
from apps.core.listing import ListConfig, ListFilter, build_listing
from apps.tickets.permissions import ROLE_ADMIN

from .forms import ROLE_CHOICES, AvatarForm, UserCreateForm, UserEditForm, square_avatar


@roles_required(ROLE_ADMIN)
def user_list(request):
    config = ListConfig(
        search_fields=["username", "first_name", "last_name", "email"],
        search_placeholder=_("Нэр, username эсвэл и-мэйлээр хайх"),
        filters=[
            ListFilter("role", _("Эрх"), ROLE_CHOICES + [("superuser", "Superuser")], _filter_role),
            ListFilter(
                "status", _("Төлөв"),
                [("active", _("Идэвхтэй")), ("inactive", _("Идэвхгүй"))],
                lambda qs, v: qs.filter(is_active=(v == "active")),
            ),
        ],
        sorts={
            "name": (_("Нэрээр (А-Я)"), ("-is_active", "username")),
            "-date_joined": (_("Шинээр бүртгэгдсэн"), ("-date_joined",)),
            "-last_login": (_("Сүүлд нэвтэрсэн"), ("-last_login",)),
        },
        default_sort="name",
    )
    listing = build_listing(
        request, User.objects.select_related("profile").prefetch_related("groups"), config
    )
    return render(request, "accounts/user_list.html", {**listing, "users": listing["object_list"]})


def _filter_role(queryset, value):
    if value == "superuser":
        return queryset.filter(is_superuser=True)
    return queryset.filter(groups__name=value)


@roles_required(ROLE_ADMIN)
def user_create(request):
    form = UserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        messages.success(request, _("'%(name)s' хэрэглэгч бүртгэгдлээ.") % {"name": user.username})
        return redirect("accounts:user_list")
    return render(request, "accounts/user_form.html", {"form": form})


@roles_required(ROLE_ADMIN)
def user_edit(request, pk):
    target = get_object_or_404(User, pk=pk)
    if target.is_superuser and not request.user.is_superuser:
        messages.error(request, _("Superuser-ийг зөвхөн superuser засна."))
        return redirect("accounts:user_list")
    form = UserEditForm(request.POST or None, instance=target, editor=request.user)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        if "is_active" in form.changed_data and not user.is_active:
            _warn_open_assignments(request, user)
        if user == request.user and form.cleaned_data.get("new_password1"):
            # Өөрийн нууц үгээ сольсон ч session-оос гаргахгүй.
            from django.contrib.auth import update_session_auth_hash

            update_session_auth_hash(request, user)
        messages.success(request, _("'%(name)s' хэрэглэгчийн мэдээлэл шинэчлэгдлээ.") % {"name": user.username})
        return redirect("accounts:user_list")
    return render(request, "accounts/user_form.html", {"form": form, "target": target})


@roles_required(ROLE_ADMIN)
@require_POST
def user_delete(request, pk):
    target = get_object_or_404(User, pk=pk)
    if target == request.user:
        messages.error(request, _("Өөрийгөө устгах боломжгүй."))
    elif target.is_superuser and not request.user.is_superuser:
        messages.error(request, _("Superuser-ийг зөвхөн superuser устгана."))
    else:
        name = target.username
        try:
            target.delete()
            messages.success(request, _("'%(name)s' хэрэглэгч устгагдлаа.") % {"name": name})
        except ProtectedError:
            # Ticket мэдээлсэн түүхтэй хэрэглэгчийг устгавал түүх алдагдана —
            # Jira/Zendesk-ийн адил идэвхгүй болгож, нэвтрэх эрхийг хаана.
            target.is_active = False
            target.save(update_fields=["is_active"])
            _warn_open_assignments(request, target)
            messages.warning(
                request,
                _("'%(name)s' ticket-ийн түүхтэй тул устгах боломжгүй — оронд нь идэвхгүй болгож, нэвтрэх эрхийг хаалаа.")
                % {"name": name},
            )
    return redirect("accounts:user_list")


@roles_required(ROLE_ADMIN)
@require_POST
def user_deactivate(request, pk):
    target = get_object_or_404(User, pk=pk)
    if target == request.user:
        messages.error(request, _("Өөрийгөө идэвхгүй болгох боломжгүй."))
    elif target.is_superuser and not request.user.is_superuser:
        messages.error(request, _("Superuser-ийг зөвхөн superuser идэвхгүй болгоно."))
    else:
        target.is_active = False
        target.save(update_fields=["is_active"])
        messages.success(request, _("'%(name)s' идэвхгүй боллоо — нэвтрэх эрх хаагдлаа.") % {"name": target.username})
        _warn_open_assignments(request, target)
    return redirect("accounts:user_list")


def _warn_open_assignments(request, target):
    from apps.tickets.models import Ticket

    count = Ticket.objects.filter(assigned_to=target).exclude(status__in=["closed", "rejected"]).count()
    if count:
        messages.warning(
            request,
            _("'%(name)s'-д %(n)s нээлттэй ticket оноогдсон байна — ticket бүрийн \"Хариуцагч солих\" хэсгээс өөр хүнд шилжүүлнэ үү.")
            % {"name": target.username, "n": count},
        )


@roles_required(ROLE_ADMIN)
@require_POST
def user_activate(request, pk):
    target = get_object_or_404(User, pk=pk)
    target.is_active = True
    target.save(update_fields=["is_active"])
    messages.success(request, _("'%(name)s' дахин идэвхжлээ.") % {"name": target.username})
    return redirect("accounts:user_list")


@login_required
@require_POST
def avatar_update(request):
    """Өөрийн профайлын зургийг солих / устгах ("Миний ажил" хуудасны зураг дээр дарж)."""
    from .models import Profile

    profile, _created = Profile.objects.get_or_create(user=request.user)
    if request.POST.get("action") == "remove":
        profile.avatar.delete(save=True)
        messages.success(request, _("Профайлын зураг устгагдлаа."))
        return redirect("tickets:dashboard")

    form = AvatarForm(request.POST, request.FILES)
    if form.is_valid():
        profile.avatar.delete(save=False)
        profile.avatar.save("avatar.png", square_avatar(form.cleaned_data["avatar"]), save=True)
        messages.success(request, _("Профайлын зураг шинэчлэгдлээ."))
    else:
        for error in form.errors.get("avatar", []):
            messages.error(request, error)
    return redirect("tickets:dashboard")
