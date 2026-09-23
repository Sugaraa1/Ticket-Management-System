from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.core.decorators import roles_required
from apps.tickets.permissions import ROLE_ADMIN, ROLE_PM

from .forms import CategoryForm, CategoryTeamAssignmentForm, TeamForm, TeamMembersForm
from .models import Category, Team


@roles_required(ROLE_PM, ROLE_ADMIN)
def category_list(request):
    categories = Category.objects.select_related(
        "team_assignment", "team_assignment__team",
        "team_assignment__team__team_lead", "team_assignment__team__qa_tester",
    )
    return render(request, "categories/category_list.html", {"categories": categories})


@roles_required(ROLE_PM, ROLE_ADMIN)
def category_create(request):
    if request.method == "POST":
        form = CategoryForm(request.POST)
        if form.is_valid():
            category = form.save()
            messages.success(
                request,
                _("'%(name)s' ангилал үүслээ. Одоо баг/хариуцагчийг нь тохируулна уу.")
                % {"name": category.name},
            )
            return redirect("categories:category_edit", pk=category.pk)
    else:
        form = CategoryForm()
    return render(
        request, "categories/category_form.html", {"form": form, "page_title": _("Шинэ ангилал")}
    )


@roles_required(ROLE_PM, ROLE_ADMIN)
def category_edit(request, pk):
    category = get_object_or_404(Category, pk=pk)
    assignment = getattr(category, "team_assignment", None)

    if request.method == "POST":
        form = CategoryForm(request.POST, instance=category)
        team_selected = request.POST.get("team")

        if team_selected:
            assignment_form = CategoryTeamAssignmentForm(request.POST, instance=assignment)
            assignment_valid = assignment_form.is_valid()
        else:
            assignment_form = CategoryTeamAssignmentForm(instance=assignment)
            assignment_valid = True  # баг сонгоогүй бол routing тохиргоог алгасна

        if form.is_valid() and assignment_valid:
            form.save()
            if team_selected:
                obj = assignment_form.save(commit=False)
                obj.category = category
                obj.save()
            messages.success(
                request, _("'%(name)s' ангилал шинэчлэгдлээ.") % {"name": category.name}
            )
            return redirect("categories:category_list")
    else:
        form = CategoryForm(instance=category)
        assignment_form = CategoryTeamAssignmentForm(instance=assignment)

    return render(
        request,
        "categories/category_form.html",
        {
            "form": form,
            "assignment_form": assignment_form,
            "page_title": _("'%(name)s' засах") % {"name": category.name},
            "category": category,
        },
    )


@roles_required(ROLE_PM, ROLE_ADMIN)
def team_list(request):
    if request.method == "POST":
        form = TeamForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, _("Баг амжилттай үүслээ."))
            return redirect("categories:team_list")
    else:
        form = TeamForm()

    teams = Team.objects.all()
    return render(request, "categories/team_list.html", {"teams": teams, "form": form})


@roles_required(ROLE_PM, ROLE_ADMIN)
def team_detail(request, pk):
    team = get_object_or_404(Team, pk=pk)

    if request.method == "POST" and request.POST.get("form_type") == "team_info":
        team_form = TeamForm(request.POST, instance=team)
        if team_form.is_valid():
            team_form.save()
            messages.success(
                request, _("'%(name)s' багийн мэдээлэл шинэчлэгдлээ.") % {"name": team.name}
            )
            return redirect("categories:team_detail", pk=team.pk)
        members_form = TeamMembersForm(initial={"members": team.members.all()})
    elif request.method == "POST":
        members_form = TeamMembersForm(request.POST)
        if members_form.is_valid():
            team.members.set(members_form.cleaned_data["members"])
            messages.success(
                request, _("'%(name)s' багийн гишүүд шинэчлэгдлээ.") % {"name": team.name}
            )
            return redirect("categories:team_detail", pk=team.pk)
        team_form = TeamForm(instance=team)
    else:
        team_form = TeamForm(instance=team)
        members_form = TeamMembersForm(initial={"members": team.members.all()})

    from apps.tickets.permissions import team_members_with_workload

    return render(
        request,
        "categories/team_detail.html",
        {
            "team": team,
            "team_form": team_form,
            "form": members_form,
            "members_workload": team_members_with_workload(team),
        },
    )
