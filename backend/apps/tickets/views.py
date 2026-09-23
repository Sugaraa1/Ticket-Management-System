import io

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.paginator import Paginator
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import gettext as _

from apps.categories.models import Category
from apps.core.decorators import roles_required
from apps.projects.models import Module

from .forms import AttachmentForm, CommentForm, TicketForm
from .models import ALLOWED_TRANSITIONS, Ticket
from .notifications import (
    notify_status_changed,
    notify_ticket_assigned,
    notify_ticket_routed,
)
from .permissions import (
    ROLE_ADMIN,
    ROLE_PM,
    can_user_assign,
    can_user_transition,
    team_members_with_workload,
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
    status_counts = Ticket.objects.values("status").annotate(total=Count("id"))
    status_map = {row["status"]: row["total"] for row in status_counts}

    context = {
        "status_choices": Ticket.Status.choices,
        "status_map": status_map,
        "total_tickets": Ticket.objects.count(),
        "my_tickets": Ticket.objects.filter(assigned_to=request.user).order_by("-created_at")[:5],
        "recent_tickets": Ticket.objects.order_by("-created_at")[:5],
    }
    return render(request, "tickets/dashboard.html", context)


@login_required
def ticket_list(request):
    tickets = Ticket.objects.select_related("category", "project", "assigned_to").all()

    status = request.GET.get("status", "")
    priority = request.GET.get("priority", "")
    category = request.GET.get("category", "")
    q = request.GET.get("q", "")

    if status:
        tickets = tickets.filter(status=status)
    if priority:
        tickets = tickets.filter(priority=priority)
    if category:
        tickets = tickets.filter(category_id=category)
    if q:
        tickets = tickets.filter(title__icontains=q)

    paginator = Paginator(tickets, TICKET_LIST_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    querystring = request.GET.copy()
    querystring.pop("page", None)

    context = {
        "tickets": page_obj,
        "page_obj": page_obj,
        "querystring": querystring.urlencode(),
        "status_choices": Ticket.Status.choices,
        "priority_choices": Ticket.Priority.choices,
        "categories": Category.objects.all(),
        "current_status": status,
        "current_priority": priority,
        "current_category": category,
        "q": q,
    }
    return render(request, "tickets/ticket_list.html", context)


@login_required
def ticket_create(request):
    if request.method == "POST":
        form = TicketForm(request.POST)
        if form.is_valid():
            ticket = form.save(commit=False)
            ticket.reported_by = request.user
            ticket._changed_by = request.user
            ticket.save()
            notify_ticket_routed(ticket)
            messages.success(request, _("Ticket #%(pk)s амжилттай үүслээ.") % {"pk": ticket.pk})
            return redirect("tickets:ticket_detail", pk=ticket.pk)
    else:
        form = TicketForm()
    return render(
        request,
        "tickets/ticket_form.html",
        {"form": form, "modules_by_project": _modules_by_project()},
    )


@login_required
def ticket_detail(request, pk):
    ticket = get_object_or_404(
        Ticket.objects.select_related(
            "category", "project", "module", "team", "assigned_to", "reported_by"
        ),
        pk=pk,
    )
    comment_form = CommentForm()
    attachment_form = AttachmentForm()

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "transition":
            new_status = request.POST.get("new_status")
            comment_body = request.POST.get("comment", "").strip()

            allowed, error_msg = can_user_transition(ticket, new_status, request.user)
            if not allowed:
                messages.error(request, error_msg)
                return redirect("tickets:ticket_detail", pk=pk)

            if new_status == Ticket.Status.ASSIGNED:
                if not can_user_assign(request.user):
                    messages.error(
                        request,
                        _("Танд ticket оноох эрх байхгүй (PM/Admin эрхтэй байх шаардлагатай)."),
                    )
                    return redirect("tickets:ticket_detail", pk=pk)
                assignee_id = request.POST.get("assigned_to")
                if not assignee_id:
                    messages.error(request, _("Хариуцах хэрэглэгчийг сонгоно уу."))
                    return redirect("tickets:ticket_detail", pk=pk)

                valid_member_ids = {
                    str(u.id) for u in team_members_with_workload(ticket.team)
                }
                if assignee_id not in valid_member_ids:
                    messages.error(
                        request,
                        _("Сонгосон хэрэглэгч энэ ticket-ийн багийн гишүүн биш тул assign хийх боломжгүй."),
                    )
                    return redirect("tickets:ticket_detail", pk=pk)
                ticket.assigned_to_id = assignee_id

            previous_status = ticket.status
            try:
                ticket.transition_to(new_status, user=request.user, comment=comment_body)
                messages.success(request, _("Status амжилттай шилжлээ."))
                if new_status == Ticket.Status.ASSIGNED and ticket.assigned_to_id:
                    notify_ticket_assigned(ticket, changed_by=request.user)
                notify_status_changed(ticket, previous_status, new_status, changed_by=request.user)
            except ValidationError as exc:
                messages.error(request, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
            return redirect("tickets:ticket_detail", pk=pk)

        elif action == "comment":
            comment_form = CommentForm(request.POST)
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
        "comments": ticket.comments.select_related("author"),
        "attachments": ticket.attachments.select_related("uploaded_by"),
    }
    return render(request, "tickets/ticket_detail.html", context)


@roles_required(ROLE_PM, ROLE_ADMIN)
def run_sla_check(request):
    """
    'check_sla_deadlines' management command-ыг вебээс гараар нэг удаа
    ажиллуулж, SLA анхааруулга/escalation мэдэгдлийг шууд шалгах боломж олгоно
    (Cron/scheduler хүлээхгүйгээр тестлэхэд зориулагдсан).
    """
    if request.method == "POST":
        output = io.StringIO()
        call_command("check_sla_deadlines", stdout=output)
        messages.success(request, output.getvalue().strip())
    return redirect("tickets:dashboard")


@roles_required(ROLE_PM, ROLE_ADMIN)
def run_stale_check(request):
    """
    'check_stale_tickets' management command-ыг вебээс гараар нэг удаа
    ажиллуулж, идэвхгүй ticket-үүдийн сануулгыг шууд шалгах боломж олгоно.
    """
    if request.method == "POST":
        output = io.StringIO()
        call_command("check_stale_tickets", stdout=output)
        messages.success(request, output.getvalue().strip())
    return redirect("tickets:dashboard")


@roles_required(ROLE_PM, ROLE_ADMIN)
def reports(request):
    """
    Agent гүйцэтгэл, SLA compliance %, ticket volume trend зэргийг харуулах
    тайлангийн dashboard (Zendesk/Jira Service Management-ийн "Reports" таб-тай адил).
    """
    days = clean_period(request.GET.get("days"))
    context = build_report(days)
    return render(request, "tickets/reports.html", context)
