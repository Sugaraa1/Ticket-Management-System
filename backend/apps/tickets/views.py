from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.categories.models import Category
from apps.projects.models import Module

from . import actions, exports, queues
from .forms import AttachmentForm, CommentForm, TicketEditForm, TicketForm
from .models import (
    ALLOWED_TRANSITIONS,
    Attachment,
    Comment,
    Ticket,
    parse_ticket_code,
)
from .notifications import notify_comment, notify_ticket_routed
from .permissions import (
    assignable_developers,
    can_use_bulk_actions,
    can_user_assign,
    can_user_edit_ticket,
    can_user_reassign,
    can_see_internal_notes,
    can_user_transition,
    can_view_team_report,
    export_ticket_scope,
    has_global_reports,
    team_members_with_workload,
    user_roles,
)
from .reports import build_report, clean_period

TICKET_LIST_PAGE_SIZE = 25


def _modules_by_project():
    """Project.id -> [{id, name}] — ticket_form.html-д Module dropdown-ыг сонгосон
    Project-оор нь клиент талд шүүхэд ашиглагдана."""
    grouped = {}
    for module in Module.objects.select_related("project").order_by("name"):
        grouped.setdefault(str(module.project_id), []).append(
            {"id": module.id, "name": module.name}
        )
    return grouped


@login_required
def dashboard(request):
    """Хэрэглэгчийн профайл/ажлын талбар: өөрийн мэдээлэл + өөрөөс үйлдэл хүлээж буй ticket-үүд."""
    user = request.user
    assigned = queues.assigned_to_me(user)
    qa = queues.qa_queue(user)
    lead = queues.lead_queue(user)
    reported_open = (
        Ticket.objects.select_related("category", "assigned_to")
        .filter(reported_by=user)
        .exclude(status__in=queues.CLOSED_STATUSES)
    )
    overdue = sum(1 for t in list(assigned) + list(qa) if t.is_overdue or t.is_first_response_overdue)

    context = {
        "profile_user": user,
        "roles": sorted(user_roles(user)),
        "teams": list(user.teams.all()),
        "led_teams": list(user.led_teams.all()),
        "qa_teams": list(user.qa_teams.all()),
        "assigned_active": assigned.order_by("sla_due_at")[:15],
        "qa_queue": qa.order_by("sla_due_at")[:15],
        "lead_queue": lead.order_by("sla_due_at")[:15],
        "reported_open": reported_open.order_by("-created_at")[:10],
        "stats": {
            "assigned_active": assigned.count(),
            "qa_waiting": qa.count(),
            "lead_unassigned": lead.count(),
            "overdue": overdue,
            "reported_open": reported_open.count(),
            "closed_by_me": Ticket.objects.filter(assigned_to=user, status=Ticket.Status.CLOSED).count(),
        },
    }
    return render(request, "tickets/dashboard.html", context)


@login_required
def my_team(request):
    """Хэрэглэгчийн харьяалагдах (гишүүн / Team Lead / QA) багуудын мэдээлэл."""
    from django.db.models import Q

    from apps.categories.models import Team

    user = request.user
    teams = (
        Team.objects.filter(Q(members=user) | Q(team_lead=user) | Q(qa_tester=user))
        .select_related("team_lead", "qa_tester")
        .prefetch_related("category_assignments__category")
        .distinct()
        .order_by("name")
    )
    team_blocks = []
    for team in teams:
        active = (
            Ticket.objects.select_related("category", "assigned_to", "reported_by")
            .filter(team=team)
            .exclude(status__in=queues.CLOSED_STATUSES)
        )
        active_list = list(active.order_by("sla_due_at"))
        team_blocks.append({
            "team": team,
            "members": team_members_with_workload(team),
            "categories": [a.category for a in team.category_assignments.all()],
            "tickets": active_list[:20],
            "can_view_report": can_view_team_report(user, team),
            "stats": {
                "open": len(active_list),
                "unassigned": sum(1 for t in active_list if t.assigned_to_id is None),
                "qa": sum(1 for t in active_list if t.status == Ticket.Status.QA_TEST),
                "overdue": sum(1 for t in active_list if t.is_overdue),
            },
        })
    return render(request, "tickets/my_team.html", {"team_blocks": team_blocks})


@login_required
def ticket_list(request):
    from django.contrib.auth import get_user_model
    from django.db.models import Case, IntegerField, Q, Value, When

    User = get_user_model()
    tickets = Ticket.objects.select_related("category", "project", "assigned_to", "reported_by").all()

    status = request.GET.get("status", "")
    priority = request.GET.get("priority", "")
    category = request.GET.get("category", "")
    assignee = request.GET.get("assignee", "")
    reporter = request.GET.get("reporter", "")
    title = request.GET.get("title", "").strip()
    q = request.GET.get("q", "")

    if status:
        tickets = tickets.filter(status=status)
    if priority:
        tickets = tickets.filter(priority=priority)
    if category.isdigit():
        tickets = tickets.filter(category_id=category)
    if assignee == "none":
        tickets = tickets.filter(assigned_to__isnull=True)
    elif assignee.isdigit():
        tickets = tickets.filter(assigned_to_id=assignee)
    if reporter.isdigit():
        tickets = tickets.filter(reported_by_id=reporter)
    if title:
        tickets = tickets.filter(title__icontains=title)
    if q:
        # "FXT000012" гэж бичвэл тухайн ticket-ийг дугаараар нь олно.
        code_pk = parse_ticket_code(q)
        # "a" гэж бичихэд "a"-гаар эхэлсэн гарчиг эхэнд, агуулсан нь дараа нь гарна.
        tickets = (
            tickets.filter(Q(title__icontains=q) | Q(pk=code_pk) if code_pk else Q(title__icontains=q))
            .annotate(
                starts=Case(
                    When(title__istartswith=q, then=Value(0)),
                    default=Value(1),
                    output_field=IntegerField(),
                )
            )
            .order_by("starts", "-created_at")
        )

    export_format = request.GET.get("export")
    if export_format in exports.EXPORT_FORMATS:
        scope = export_ticket_scope(request.user)
        if scope is False:
            messages.error(request, _("Танд ticket жагсаалт татах эрх байхгүй."))
            return redirect("tickets:ticket_list")
        if scope is not None:
            tickets = tickets.filter(team_id__in=scope)
        tickets = tickets.select_related("module", "team")
        filename = exports.export_filename("tickets", export_format)
        if export_format == "csv":
            return exports.tickets_csv(tickets, filename)
        return exports.tickets_xlsx(tickets, filename)

    paginator = Paginator(tickets, TICKET_LIST_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    querystring = request.GET.copy()
    querystring.pop("page", None)
    querystring.pop("export", None)

    users = list(User.objects.filter(is_active=True).order_by("username"))
    user_names = {str(u.id): u.username for u in users}
    labels = {
        "title": title or None,
        "status": dict(Ticket.Status.choices).get(status),
        "priority": dict(Ticket.Priority.choices).get(priority),
        "category": Category.objects.filter(pk=category).values_list("name", flat=True).first()
        if category.isdigit() else None,
        "assignee": _("Оноогдоогүй") if assignee == "none" else user_names.get(assignee),
        "reporter": user_names.get(reporter),
    }
    titles = {
        "title": _("Гарчиг"),
        "status": _("Төлөв"),
        "priority": _("Чухлын зэрэг"),
        "category": _("Ангилал"),
        "assignee": _("Хариуцагч"),
        "reporter": _("Мэдээлсэн"),
    }
    active_filters = []
    for key, label in labels.items():
        if label:
            remaining = querystring.copy()
            remaining.pop(key, None)
            active_filters.append({
                "title": titles[key],
                "label": label,
                "remove_url": "?" + remaining.urlencode() if remaining else request.path,
            })

    context = {
        "tickets": page_obj,
        "page_obj": page_obj,
        "querystring": querystring.urlencode(),
        "active_filters": active_filters,
        "status_choices": Ticket.Status.choices,
        "priority_choices": Ticket.Priority.choices,
        "categories": Category.objects.all(),
        "users": users,
        "current_status": status,
        "current_priority": priority,
        "current_category": category,
        "current_assignee": assignee,
        "current_reporter": reporter,
        "current_title": title,
        "q": q,
        "can_export": export_ticket_scope(request.user) is not False,
        "can_bulk": can_use_bulk_actions(request.user),
        "bulk_assignees": assignable_developers().order_by("username"),
        "bulk_statuses": [
            (value, label) for value, label in Ticket.Status.choices
            if value not in (Ticket.Status.NEW, Ticket.Status.ASSIGNED)
        ],
    }
    return render(request, "tickets/ticket_list.html", context)


@login_required
def ticket_create(request):
    if request.method == "POST":
        form = TicketForm(request.POST, request.FILES)
        if form.is_valid():
            ticket = form.save(commit=False)
            ticket.reported_by = request.user
            ticket._changed_by = request.user
            ticket.save()
            if form.cleaned_data.get("attachment"):
                Attachment.objects.create(
                    ticket=ticket, file=form.cleaned_data["attachment"], uploaded_by=request.user
                )
            notify_ticket_routed(ticket)
            messages.success(request, _("Ticket %(code)s амжилттай үүслээ.") % {"code": ticket.code})
            _warn_if_unrouted(request, ticket)
            return redirect("tickets:ticket_detail", pk=ticket.pk)
    else:
        form = TicketForm()
    return render(
        request,
        "tickets/ticket_form.html",
        {"form": form, "modules_by_project": _modules_by_project()},
    )


@login_required
def ticket_edit(request, pk):
    ticket = get_object_or_404(Ticket.objects.select_related("team", "category", "project", "module"), pk=pk)
    if not can_user_edit_ticket(ticket, request.user):
        messages.error(request, _("Танд энэ ticket-ийг засах эрх байхгүй."))
        return redirect("tickets:ticket_detail", pk=pk)

    form = TicketEditForm(request.POST or None, instance=ticket)
    if request.method == "POST" and form.is_valid():
        if not form.has_changed():
            return redirect("tickets:ticket_detail", pk=pk)
        before = {name: getattr(Ticket.objects.get(pk=pk), name) for name in form.changed_data}
        ticket = form.save(commit=False)
        if "category" in form.changed_data:
            ticket.team = None  # save() шинэ ангиллын багийг автоматаар сонгоно
        ticket.save()
        Comment.objects.create(
            ticket=ticket, author=request.user, body=_describe_changes(form, before, ticket)
        )
        ticket.mark_activity()
        if "category" in form.changed_data:
            notify_ticket_routed(ticket)
        messages.success(request, _("Ticket шинэчлэгдлээ."))
        _warn_if_unrouted(request, ticket)
        return redirect("tickets:ticket_detail", pk=pk)

    return render(
        request,
        "tickets/ticket_form.html",
        {"form": form, "ticket": ticket, "modules_by_project": _modules_by_project()},
    )


def _warn_if_unrouted(request, ticket):
    if ticket.team_id is None:
        messages.warning(
            request,
            _("'%(category)s' ангилалд баг тохируулаагүй тул ticket одоогоор аль ч багт "
              "хуваарилагдаагүй. PM/Admin ангилалд баг тохируулахад автоматаар хуваарилагдана.")
            % {"category": ticket.category.name},
        )


def _describe_changes(form, before, ticket):
    """Юу өөрчлөгдсөнийг түүхэнд үлдээх сэтгэгдэл: "Гарчиг: хуучин → шинэ" гэх мэт."""
    lines = [_("Ticket засварлагдлаа:")]
    for name in form.changed_data:
        label = form.fields[name].label
        if name == "description":
            lines.append(_("• %(field)s шинэчлэгдсэн") % {"field": label})
            continue
        old, new = before[name], getattr(ticket, name)
        if name == "ticket_type":
            choices = dict(Ticket.TicketType.choices)
            old, new = choices.get(old, old), choices.get(new, new)
        lines.append("• %s: %s → %s" % (label, old or "—", new or "—"))
    if "category" in form.changed_data:
        lines.append(_("• Баг: %(team)s (автоматаар)") % {"team": ticket.team or "—"})
    return "\n".join(lines)




@login_required
def ticket_detail(request, pk):
    ticket = get_object_or_404(
        Ticket.objects.select_related(
            "category", "project", "module", "team", "assigned_to", "reported_by"
        ),
        pk=pk,
    )
    sees_internal = can_see_internal_notes(ticket, request.user)
    comment_form = CommentForm(allow_internal=sees_internal)
    attachment_form = AttachmentForm()

    if request.method == "POST":
        action = request.POST.get("action")

        if action in ("transition", "reassign", "priority"):
            try:
                if action == "transition":
                    actions.transition(
                        ticket, request.POST.get("new_status"), request.user,
                        comment=request.POST.get("comment", "").strip(),
                        assignee_id=request.POST.get("assigned_to"),
                    )
                    messages.success(request, _("Status амжилттай шилжлээ."))
                elif action == "reassign":
                    if actions.reassign(ticket, request.POST.get("assigned_to"), request.user):
                        messages.success(request, _("Хариуцагч солигдлоо."))
                elif actions.change_priority(ticket, request.POST.get("priority"), request.user):
                    messages.success(request, _("Чухлын зэрэг шинэчлэгдэж, SLA хугацаа дахин тооцоологдлоо."))
            except actions.ActionError as exc:
                messages.error(request, str(exc))
            return redirect("tickets:ticket_detail", pk=pk)

        elif action == "comment":
            comment_form = CommentForm(request.POST, allow_internal=sees_internal)
            if comment_form.is_valid():
                comment = comment_form.save(commit=False)
                comment.ticket = ticket
                comment.author = request.user
                comment.save()
                if request.user.id != ticket.reported_by_id:
                    # Мэдээлэгчээс өөр хүн анх удаа хариу бичсэн бол
                    # Time to First Response SLA-г зогсооно.
                    ticket.mark_first_response()
                ticket.mark_activity()
                notify_comment(ticket, comment)
                messages.success(request, _("Сэтгэгдэл нэмэгдлээ."))
                return redirect("tickets:ticket_detail", pk=pk)

        elif action == "attachment":
            attachment_form = AttachmentForm(request.POST, request.FILES)
            if attachment_form.is_valid():
                attachment = attachment_form.save(commit=False)
                attachment.ticket = ticket
                attachment.uploaded_by = request.user
                attachment.save()
                ticket.mark_activity()
                messages.success(request, _("Файл амжилттай хавсаргалаа."))
                return redirect("tickets:ticket_detail", pk=pk)

    candidate_statuses = ALLOWED_TRANSITIONS.get(ticket.status, [])
    permitted_statuses = [
        s for s in candidate_statuses if can_user_transition(ticket, s, request.user)[0]
    ]
    next_statuses = [(value, Ticket.Status(value).label) for value in permitted_statuses]

    developers = None
    assign_blocked_reason = ""
    if Ticket.Status.ASSIGNED in permitted_statuses:
        if ticket.team is None:
            assign_blocked_reason = _(
                "Энэ ticket-ийн Category-д Баг (Team) тохируулаагүй тул assign хийх "
                "боломжгүй. Эхлээд 'Удирдлага → Ангилал' хэсэгт баг тохируулна уу."
            )
        else:
            developers = team_members_with_workload(ticket.team)
            if not developers:
                assign_blocked_reason = _(
                    "'%(team)s' багт одоогоор гишүүн алга байна. "
                    "Эхлээд 'Удирдлага → Баг' хэсэгт ажилчид нэмнэ үү."
                ) % {"team": ticket.team.name}

    context = {
        "ticket": ticket,
        "comment_form": comment_form,
        "attachment_form": attachment_form,
        "next_statuses": next_statuses,
        "developers": developers,
        "assign_blocked_reason": assign_blocked_reason,
        "history": ticket.history.select_related("changed_by"),
        "comments": (
            ticket.comments.select_related("author")
            if sees_internal
            else ticket.comments.select_related("author").filter(is_internal=False)
        ),
        "attachments": ticket.attachments.select_related("uploaded_by"),
        "can_change_priority": can_user_assign(request.user, ticket),
        "can_edit": can_user_edit_ticket(ticket, request.user),
        "mention_users": [
            {"u": u.username, "n": u.get_full_name()}
            for u in get_user_model().objects.filter(is_active=True).order_by("username")
        ],
        "reassign_members": (
            team_members_with_workload(ticket.team)
            if ticket.team_id and can_user_reassign(ticket, request.user)
            else None
        ),
        "priority_choices": Ticket.priority_choices_with_sla(),
    }
    return render(request, "tickets/ticket_detail.html", context)


@login_required
def reports(request):
    """
    Agent гүйцэтгэл, SLA compliance %, ticket volume trend зэргийг харуулах
    тайлангийн dashboard (Zendesk/Jira Service Management-ийн "Reports" таб-тай адил).
    Бүх багийн нийт dashboard-ийг Admin болон баг ахлаагүй PM харна; Team Lead
    өөрийн багийн dashboard руу (Миний баг) шилжинэ.
    """
    if not has_global_reports(request.user):
        if request.user.led_teams.exists():
            return redirect("tickets:my_team")
        messages.error(request, _("Танд энэ хуудсанд хандах эрх байхгүй."))
        return redirect("tickets:ticket_list")
    return _render_report(request)


@login_required
def team_report(request, pk):
    """Нэг багийн dashboard — тухайн багийн Team Lead (эсвэл нийт эрхтэй хэрэглэгч) харна."""
    from apps.categories.models import Team

    team = get_object_or_404(Team, pk=pk)
    if not can_view_team_report(request.user, team):
        messages.error(request, _("Танд энэ багийн тайланг харах эрх байхгүй."))
        return redirect("tickets:my_team")
    return _render_report(request, team)


def _render_report(request, team=None):
    days = clean_period(request.GET.get("days"))
    context = build_report(days, team=team)
    if has_global_reports(request.user):
        from apps.categories.models import Team

        context["team_choices"] = Team.objects.order_by("name")
    export_format = request.GET.get("export")
    if export_format in exports.EXPORT_FORMATS:
        prefix = f"report_team{team.pk}" if team else "report"
        filename = exports.export_filename(f"{prefix}_{days}d", export_format)
        if export_format == "csv":
            return exports.report_csv(context, request.user, filename)
        tickets = exports.report_period_tickets(context["since"], team)
        return exports.report_xlsx(context, tickets, request.user, filename)
    return render(request, "tickets/reports.html", context)


# Хөтөч дотор шууд нээж болох аюулгүй төрлүүд; бусад нь (html, office, zip...) татагдана.
INLINE_ATTACHMENT_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "pdf", "txt", "log"}


@login_required
def attachment_download(request, pk):
    """Хавсралтыг зөвхөн нэвтэрсэн хэрэглэгчид өгнө (ticket-ийг харах эрхтэй адил)."""
    import os

    from django.http import FileResponse, Http404

    attachment = get_object_or_404(Attachment, pk=pk)
    try:
        handle = attachment.file.open("rb")
    except FileNotFoundError:
        raise Http404(_("Файл олдсонгүй."))
    name = os.path.basename(attachment.file.name)
    inline = name.rsplit(".", 1)[-1].lower() in INLINE_ATTACHMENT_EXTENSIONS
    return FileResponse(handle, as_attachment=not inline, filename=name)


BULK_LIMIT = 100


@login_required
def ticket_bulk(request):
    """
    Жагсаалтаас сонгосон олон ticket дээр нэг үйлдэл (оноох, чухлын зэрэг, төлөв).
    Ticket бүр дээр ticket-ийн хуудастай ижил эрхийн шалгалт (actions.py) хийгдэнэ;
    эрхгүй / боломжгүйг нь алгасаад шалтгааныг нь мэдэгдэнэ.
    """
    from django.urls import reverse
    from django.utils.http import url_has_allowed_host_and_scheme

    # Шүүлтүүр, хуудсаа алдалгүй жагсаалт руу буцна (зөвхөн энэ сайтын хаяг).
    back = request.POST.get("next") or ""
    if not url_has_allowed_host_and_scheme(back, allowed_hosts={request.get_host()}):
        back = reverse("tickets:ticket_list")
    if request.method != "POST":
        return redirect(back)
    if not can_use_bulk_actions(request.user):
        messages.error(request, _("Бөөн үйлдлийг зөвхөн PM / Admin хийнэ."))
        return redirect(back)

    ids = [int(i) for i in request.POST.getlist("ids") if i.isdigit()][:BULK_LIMIT]
    action, value = request.POST.get("bulk_action"), request.POST.get("value", "")
    if not ids or action not in ("assign", "priority", "status") or not value:
        messages.error(request, _("Ticket болон үйлдлээ сонгоно уу."))
        return redirect(back)

    done, skipped = 0, []
    tickets = Ticket.objects.select_related("team", "assigned_to").filter(pk__in=ids)
    for ticket in tickets:
        try:
            if action == "assign":
                changed = actions.assign(ticket, value, request.user)
            elif action == "priority":
                changed = actions.change_priority(ticket, value, request.user)
            else:
                if value == Ticket.Status.ASSIGNED:
                    raise actions.ActionError(_("Оноохдоо \"Оноох\" үйлдлийг ашиглана уу."))
                if value == ticket.status:
                    changed = False
                else:
                    actions.transition(ticket, value, request.user)
                    changed = True
            done += 1 if changed else 0
        except actions.ActionError as exc:
            skipped.append(f"{ticket.code}: {exc}")

    if done:
        messages.success(request, _("%(n)s ticket шинэчлэгдлээ.") % {"n": done})
    if skipped:
        shown = "; ".join(skipped[:5]) + (" …" if len(skipped) > 5 else "")
        messages.warning(
            request, _("%(n)s ticket алгасагдлаа — %(list)s") % {"n": len(skipped), "list": shown}
        )
    if not done and not skipped:
        messages.info(request, _("Өөрчлөгдөх зүйл алга."))
    return redirect(back)


