from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.core.decorators import roles_required
from apps.core.listing import ListConfig, ListFilter, build_listing
from apps.tickets.permissions import ROLE_ADMIN, ROLE_PM

from .forms import CategoryForm, CategoryTeamsForm, TeamForm, TeamMembersForm
from .models import Category, CategoryTeamAssignment, Team


@roles_required(ROLE_PM, ROLE_ADMIN)
def category_list(request):
    categories = Category.objects.prefetch_related(
        "team_assignments__team__team_lead", "team_assignments__team__qa_tester",
    ).annotate(ticket_count=Count("tickets", distinct=True))
    team_choices = list(Team.objects.order_by("name").values_list("id", "name"))
    config = ListConfig(
        search_fields=["name", "description", "team_assignments__team__name"],
        search_placeholder=_("Ангилал эсвэл багийн нэрээр хайх"),
        filters=[
            ListFilter(
                "team", _("Баг"), [("none", _("Баг тохируулаагүй"))] + team_choices,
                _filter_category_team,
            ),
        ],
        sorts={
            "name": (_("Нэрээр (А-Я)"), ("name",)),
            "-created_at": (_("Шинээр нэмэгдсэн"), ("-created_at",)),
            "-ticket_count": (_("Ticket ихтэй нь эхэнд"), ("-ticket_count", "name")),
        },
        default_sort="name",
    )
    listing = build_listing(request, categories, config)
    return render(
        request, "categories/category_list.html", {**listing, "categories": listing["object_list"]}
    )


def _filter_category_team(queryset, value):
    if value == "none":
        return queryset.filter(team_assignments__isnull=True)
    return queryset.filter(team_assignments__team_id=value)


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
    current_teams = Team.objects.filter(category_assignments__category=category)

    if request.method == "POST":
        form = CategoryForm(request.POST, instance=category)
        teams_form = CategoryTeamsForm(request.POST)
        if form.is_valid() and teams_form.is_valid():
            form.save()
            selected = set(teams_form.cleaned_data["teams"])
            CategoryTeamAssignment.objects.filter(category=category).exclude(
                team__in=selected
            ).delete()
            for team in selected:
                CategoryTeamAssignment.objects.get_or_create(category=category, team=team)
            routed = _route_orphan_tickets(category) if selected else 0
            if routed:
                messages.info(
                    request,
                    _("Баггүй байсан %(n)s нээлттэй ticket шинэ багт хуваарилагдлаа.") % {"n": routed},
                )
            messages.success(
                request, _("'%(name)s' ангилал шинэчлэгдлээ.") % {"name": category.name}
            )
            return redirect("categories:category_list")
    else:
        form = CategoryForm(instance=category)
        teams_form = CategoryTeamsForm(initial={"teams": current_teams})

    return render(
        request,
        "categories/category_form.html",
        {
            "form": form,
            "teams_form": teams_form,
            "page_title": _("'%(name)s' засах") % {"name": category.name},
            "category": category,
        },
    )


def _route_orphan_tickets(category):
    """
    Ангилалд баг тохируулаагүй үед үүссэн (team хоосон) нээлттэй ticket-үүдийг
    одоо тохируулсан багт хуваарилж, Team Lead-д нь мэдэгдэнэ.
    """
    from apps.tickets.models import Ticket
    from apps.tickets.notifications import notify_ticket_routed

    orphans = Ticket.objects.filter(category=category, team__isnull=True).exclude(
        status__in=[Ticket.Status.CLOSED, Ticket.Status.REJECTED]
    )
    count = 0
    for ticket in orphans:
        ticket.save(update_fields=["team", "updated_at"])  # save() багийг автоматаар сонгоно
        if ticket.team_id:
            notify_ticket_routed(ticket)
            count += 1
    return count


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

    teams = Team.objects.select_related("team_lead", "qa_tester").annotate(
        member_count=Count("members", distinct=True),
        open_ticket_count=Count(
            "tickets", filter=~Q(tickets__status__in=["closed", "rejected"]), distinct=True
        ),
    )
    config = ListConfig(
        search_fields=["name", "team_lead__username", "team_lead__first_name", "qa_tester__username"],
        search_placeholder=_("Баг, Team Lead эсвэл QA-гаар хайх"),
        filters=[
            ListFilter(
                "missing", _("Дутуу"),
                [("lead", _("Team Lead-гүй")), ("qa", _("QA Tester-гүй")), ("members", _("Гишүүнгүй"))],
                _filter_team_missing,
            ),
        ],
        sorts={
            "name": (_("Нэрээр (А-Я)"), ("name",)),
            "-member_count": (_("Гишүүн ихтэй нь эхэнд"), ("-member_count", "name")),
            "-open_ticket_count": (_("Нээлттэй ticket ихтэй нь эхэнд"), ("-open_ticket_count", "name")),
        },
        default_sort="name",
    )
    listing = build_listing(request, teams, config)
    return render(
        request, "categories/team_list.html",
        {**listing, "teams": listing["object_list"], "form": form},
    )


def _filter_team_missing(queryset, value):
    if value == "lead":
        return queryset.filter(team_lead__isnull=True)
    if value == "qa":
        return queryset.filter(qa_tester__isnull=True)
    return queryset.filter(member_count=0)


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

    from apps.tickets.permissions import _ACTIVE_TICKET_STATUSES, team_members_with_workload

    # Сонгох жагсаалт: сонгогдсон нь эхэнд, хүн бүрийн нийт идэвхтэй ачааллын хамт.
    selected_ids = {int(v) for v in (members_form["members"].value() or []) if str(v).isdigit()}
    candidates = members_form.fields["members"].queryset.select_related("profile").annotate(
        active_ticket_count=Count(
            "assigned_tickets",
            filter=Q(assigned_tickets__status__in=_ACTIVE_TICKET_STATUSES),
            distinct=True,
        )
    )
    member_choices = sorted(
        ({"user": u, "checked": u.id in selected_ids} for u in candidates),
        key=lambda c: (not c["checked"], c["user"].username.lower()),
    )
    workload = list(team_members_with_workload(team).select_related("profile"))
    max_load = max([m.active_ticket_count for m in workload] or [0])

    return render(
        request,
        "categories/team_detail.html",
        {
            "team": team,
            "team_form": team_form,
            "form": members_form,
            "member_choices": member_choices,
            "selected_count": sum(1 for c in member_choices if c["checked"]),
            "members_workload": workload,
            "max_load": max_load or 1,
        },
    )
