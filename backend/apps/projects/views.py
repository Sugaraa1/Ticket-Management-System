from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render

from apps.core.decorators import roles_required
from apps.tickets.permissions import ROLE_ADMIN, ROLE_PM

from .forms import ModuleForm, ProjectForm
from .models import Project


@roles_required(ROLE_PM, ROLE_ADMIN)
def project_list(request):
    projects = Project.objects.prefetch_related("modules")
    return render(request, "projects/project_list.html", {"projects": projects})


@roles_required(ROLE_PM, ROLE_ADMIN)
def project_create(request):
    if request.method == "POST":
        form = ProjectForm(request.POST)
        if form.is_valid():
            project = form.save()
            messages.success(request, f"'{project.name}' төсөл үүслээ. Одоо module нэмж болно.")
            return redirect("projects:project_edit", pk=project.pk)
    else:
        form = ProjectForm()
    return render(
        request, "projects/project_form.html", {"form": form, "page_title": "Шинэ төсөл"}
    )


@roles_required(ROLE_PM, ROLE_ADMIN)
def project_edit(request, pk):
    project = get_object_or_404(Project, pk=pk)

    if request.method == "POST":
        form = ProjectForm(request.POST, instance=project)
        if form.is_valid():
            form.save()
            messages.success(request, f"'{project.name}' төсөл шинэчлэгдлээ.")
            return redirect("projects:project_list")
    else:
        form = ProjectForm(instance=project)

    return render(
        request,
        "projects/project_form.html",
        {
            "form": form,
            "page_title": f"'{project.name}' засах",
            "project": project,
            "module_form": ModuleForm(),
            "modules": project.modules.all(),
        },
    )


@roles_required(ROLE_PM, ROLE_ADMIN)
def module_create(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if request.method == "POST":
        form = ModuleForm(request.POST)
        if form.is_valid():
            module = form.save(commit=False)
            module.project = project
            module.save()
            messages.success(request, f"'{module.name}' module нэмэгдлээ.")
    return redirect("projects:project_edit", pk=pk)
