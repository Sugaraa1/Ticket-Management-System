from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render

from apps.categories.models import Category

from .forms import AttachmentForm, CommentForm, TicketForm
from .models import ALLOWED_TRANSITIONS, Ticket


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

    context = {
        "tickets": tickets,
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
            messages.success(request, f"Ticket #{ticket.pk} амжилттай үүслээ.")
            return redirect("tickets:ticket_detail", pk=ticket.pk)
    else:
        form = TicketForm()
    return render(request, "tickets/ticket_form.html", {"form": form})


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
            try:
                ticket.transition_to(new_status, user=request.user, comment=comment_body)
                messages.success(request, "Status амжилттай шилжлээ.")
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
                messages.success(request, "Сэтгэгдэл нэмэгдлээ.")
                return redirect("tickets:ticket_detail", pk=pk)

        elif action == "attachment":
            attachment_form = AttachmentForm(request.POST, request.FILES)
            if attachment_form.is_valid():
                attachment = attachment_form.save(commit=False)
                attachment.ticket = ticket
                attachment.uploaded_by = request.user
                attachment.save()
                messages.success(request, "Файл амжилттай хавсаргалаа.")
                return redirect("tickets:ticket_detail", pk=pk)

    next_statuses = ALLOWED_TRANSITIONS.get(ticket.status, [])
    context = {
        "ticket": ticket,
        "comment_form": comment_form,
        "attachment_form": attachment_form,
        "next_statuses": [(value, Ticket.Status(value).label) for value in next_statuses],
        "history": ticket.history.select_related("changed_by"),
        "comments": ticket.comments.select_related("author"),
        "attachments": ticket.attachments.select_related("uploaded_by"),
    }
    return render(request, "tickets/ticket_detail.html", context)
