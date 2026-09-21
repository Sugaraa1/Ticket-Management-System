from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.categories.models import Category
from apps.core.models import TimeStampedModel
from apps.projects.models import Module, Project

# ---------------------------------------------------------------------------
# Workflow: docs/workflow.md-тэй тааруулсан зөвшөөрөгдсөн status шилжилтүүд.
# ---------------------------------------------------------------------------
ALLOWED_TRANSITIONS = {
    "new": ["assigned"],
    "assigned": ["in_progress"],
    "in_progress": ["resolved", "rejected"],
    "resolved": ["qa_test"],
    "qa_test": ["closed", "reopened"],
    "reopened": ["in_progress"],
    "rejected": ["reopened"],
    "closed": [],
}


def can_transition(current_status: str, new_status: str) -> bool:
    """Ticket-ийг current_status-аас new_status рүү шилжүүлж болох эсэхийг шалгана."""
    if current_status == new_status:
        return True
    return new_status in ALLOWED_TRANSITIONS.get(current_status, [])


class Ticket(TimeStampedModel):
    class TicketType(models.TextChoices):
        BUG = "bug", "Bug"
        TASK = "task", "Task"
        CHANGE_REQUEST = "cr", "Change Request"

    class Status(models.TextChoices):
        NEW = "new", "New"
        ASSIGNED = "assigned", "Assigned"
        IN_PROGRESS = "in_progress", "In Progress"
        RESOLVED = "resolved", "Resolved"
        REJECTED = "rejected", "Rejected"
        QA_TEST = "qa_test", "QA Test"
        REOPENED = "reopened", "Reopened"
        CLOSED = "closed", "Closed"

    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        CRITICAL = "critical", "Critical"

    title = models.CharField(max_length=255)
    description = models.TextField()
    ticket_type = models.CharField(max_length=20, choices=TicketType.choices)

    category = models.ForeignKey(Category, related_name="tickets", on_delete=models.PROTECT)
    project = models.ForeignKey(Project, related_name="tickets", on_delete=models.PROTECT)
    module = models.ForeignKey(
        Module, related_name="tickets", on_delete=models.SET_NULL, null=True, blank=True
    )
    team = models.ForeignKey(
        "categories.Team",
        related_name="tickets",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Category-ийн CategoryTeamAssignment-аас автоматаар тохируулагдана.",
    )

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.NEW)
    priority = models.CharField(max_length=20, choices=Priority.choices, default=Priority.MEDIUM)

    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="reported_tickets", on_delete=models.PROTECT
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="assigned_tickets",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"#{self.pk} {self.title}"

    def _auto_route_team(self):
        """Category-д тохирсон Team-ийг олж, team талбарт байхгүй бол автоматаар тавина."""
        if self.category_id and not self.team_id:
            assignment = getattr(self.category, "team_assignment", None)
            if assignment:
                self.team_id = assignment.team_id

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        original_status = None

        if not is_new:
            original_status = (
                Ticket.objects.filter(pk=self.pk).values_list("status", flat=True).first()
            )
            if original_status and original_status != self.status:
                if not can_transition(original_status, self.status):
                    raise ValidationError(
                        f"'{original_status}' -> '{self.status}' төлөв шилжилт "
                        f"зөвшөөрөгдөөгүй байна (docs/workflow.md-г үзнэ үү)."
                    )

        self._auto_route_team()
        super().save(*args, **kwargs)

        changed_by = getattr(self, "_changed_by", None)
        if is_new:
            StatusHistory.objects.create(
                ticket=self, from_status="", to_status=self.status, changed_by=changed_by
            )
        elif original_status and original_status != self.status:
            StatusHistory.objects.create(
                ticket=self,
                from_status=original_status,
                to_status=self.status,
                changed_by=changed_by,
            )

    def transition_to(self, new_status: str, user=None, comment: str = ""):
        """
        Status-ийг зөв дараалалтай шилжүүлэх туслах метод.
        Жишээ: ticket.transition_to(Ticket.Status.QA_TEST, user=request.user)
        """
        if not can_transition(self.status, new_status):
            raise ValidationError(
                f"'{self.status}' -> '{new_status}' төлөв шилжилт зөвшөөрөгдөөгүй."
            )
        self.status = new_status
        self._changed_by = user
        self.save()

        if comment:
            Comment.objects.create(ticket=self, author=user, body=comment)


class Comment(TimeStampedModel):
    ticket = models.ForeignKey(Ticket, related_name="comments", on_delete=models.CASCADE)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    # QA reopen хийхэд comment заавал биш (сонголтоор) байх тул blank=True.
    body = models.TextField(blank=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Comment #{self.pk} on Ticket #{self.ticket_id}"


class Attachment(TimeStampedModel):
    ticket = models.ForeignKey(Ticket, related_name="attachments", on_delete=models.CASCADE)
    file = models.FileField(upload_to="attachments/%Y/%m/")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Attachment #{self.pk} on Ticket #{self.ticket_id}"


class StatusHistory(models.Model):
    """Ticket-ийн status шилжилт бүрийг хадгалах audit trail (зөвхөн уншихад зориулсан)."""

    ticket = models.ForeignKey(Ticket, related_name="history", on_delete=models.CASCADE)
    from_status = models.CharField(max_length=20, blank=True)
    to_status = models.CharField(max_length=20)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "Status histories"
        ordering = ["changed_at"]

    def __str__(self):
        return f"Ticket #{self.ticket_id}: {self.from_status or '—'} → {self.to_status}"
