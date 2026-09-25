from django.contrib import messages
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.decorators import roles_required
from apps.core.listing import ListConfig, ListFilter, build_listing
from apps.tickets.permissions import ROLE_ADMIN, ROLE_PM

from .forms import ModuleForm, ProjectForm
from .models import Module, Project


@roles_required(ROLE_PM, ROLE_ADMIN)
def project_list(request):
    projects = Project.objects.annotate(
        module_count=Count("modules", distinct=True),
        ticket_count=Count("tickets", distinct=True),
    )
    config = ListConfig(
        search_fields=["name", "description", "modules__name"],
        search_placeholder=_("Төсөл эсвэл модулийн нэрээр хайх"),
        filters=[
            ListFilter(
                "status", _("Төлөв"),
                [("active", _("Идэвхтэй")), ("inactive", _("Идэвхгүй"))],
                lambda qs, v: qs.filter(is_active=(v == "active")),
            ),
        ],
        sorts={
            "name": (_("Нэрээр (А-Я)"), ("name",)),
            "-created_at": (_("Шинээр нэмэгдсэн"), ("-created_at",)),
            "-ticket_count": (_("Ticket ихтэй нь эхэнд"), ("-ticket_count", "name")),
            "-module_count": (_("Модуль ихтэй нь эхэнд"), ("-module_count", "name")),
        },
        default_sort="name",
    )
    listing = build_listing(request, projects, config)
    return render(request, "projects/project_list.html", {**listing, "projects": listing["object_list"]})


@roles_required(ROLE_PM, ROLE_ADMIN)
def project_create(request):
    if request.method == "POST":
        form = ProjectForm(request.POST)
        if form.is_valid():
            project = form.save()
            messages.success(
                request,
                _("'%(name)s' төсөл үүслээ. Одоо module нэмж болно.") % {"name": project.name},
            )
            return redirect("projects:project_edit", pk=project.pk)
    else:
        form = ProjectForm()
    return render(
        request, "projects/project_form.html", {"form": form, "page_title": _("Шинэ төсөл")}
    )


@roles_required(ROLE_PM, ROLE_ADMIN)
def project_edit(request, pk):
    project = get_object_or_404(
        Project.objects.annotate(ticket_count=Count("tickets")), pk=pk
    )

    if request.method == "POST":
        form = ProjectForm(request.POST, instance=project)
        if form.is_valid():
            form.save()
            messages.success(
                request, _("'%(name)s' төсөл шинэчлэгдлээ.") % {"name": project.name}
            )
            return redirect("projects:project_list")
    else:
        form = ProjectForm(instance=project)

    return render(
        request,
        "projects/project_form.html",
        {
            "form": form,
            "page_title": _("'%(name)s' засах") % {"name": project.name},
            "project": project,
            "module_form": ModuleForm(),
            "modules": project.modules.annotate(ticket_count=Count("tickets")),
        },
    )


@roles_required(ROLE_PM, ROLE_ADMIN)
def module_create(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if request.method == "POST":
        form = ModuleForm(request.POST, project=project)
        if form.is_valid():
            module = form.save(commit=False)
            module.project = project
            module.save()
            messages.success(
                request, _("'%(name)s' module нэмэгдлээ.") % {"name": module.name}
            )
        else:
            _flash_form_errors(request, form)
    return redirect("projects:project_edit", pk=pk)


@roles_required(ROLE_PM, ROLE_ADMIN)
@require_POST
def module_edit(request, pk, module_pk):
    module = get_object_or_404(Module, pk=module_pk, project_id=pk)
    form = ModuleForm(request.POST, instance=module)
    if form.is_valid():
        form.save()
        messages.success(request, _("Модуль '%(name)s' болж шинэчлэгдлээ.") % {"name": module.name})
    else:
        _flash_form_errors(request, form)
    return redirect("projects:project_edit", pk=pk)


@roles_required(ROLE_PM, ROLE_ADMIN)
@require_POST
def module_delete(request, pk, module_pk):
    """Модулийг устгана — холбоотой ticket-үүд устахгүй, зөвхөн модуль нь хоосорно."""
    module = get_object_or_404(Module, pk=module_pk, project_id=pk)
    name = module.name
    module.delete()
    messages.success(request, _("'%(name)s' модуль устгагдлаа.") % {"name": name})
    return redirect("projects:project_edit", pk=pk)


@roles_required(ROLE_PM, ROLE_ADMIN)
@require_POST
def project_delete(request, pk):
    """
    Ticket-гүй төслийг модулиудтай нь устгана. Ticket-тэй бол түүх алдагдахгүйн
    тулд (Ticket.project = PROTECT) устгахын оронд идэвхгүй болгоно.
    """
    project = get_object_or_404(Project, pk=pk)
    name = project.name
    if project.tickets.exists():
        project.is_active = False
        project.save(update_fields=["is_active", "updated_at"])
        messages.warning(
            request,
            _("'%(name)s' төсөл ticket-тэй тул устгах боломжгүй — оронд нь идэвхгүй болголоо.")
            % {"name": name},
        )
    else:
        project.delete()
        messages.success(request, _("'%(name)s' төсөл устгагдлаа.") % {"name": name})
    return redirect("projects:project_list")


def _flash_form_errors(request, form):
    for errors in form.errors.values():
        for error in errors:
            messages.error(request, error)


@roles_required(ROLE_PM, ROLE_ADMIN)
@require_POST
def project_toggle_active(request, pk):
    """Жагсаалтын on/off toggle — идэвхгүй төсөлд шинэ ticket үүсгэхгүй."""
    project = get_object_or_404(Project, pk=pk)
    project.is_active = not project.is_active
    project.save(update_fields=["is_active", "updated_at"])
    if project.is_active:
        messages.success(request, _("'%(name)s' төсөл идэвхжлээ.") % {"name": project.name})
    else:
        messages.success(
            request,
            _("'%(name)s' төсөл идэвхгүй боллоо — шинэ ticket үүсгэх сонголтод гарахгүй.")
            % {"name": project.name},
        )
    return redirect("projects:project_list")
