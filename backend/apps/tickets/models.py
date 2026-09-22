from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

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
        BUG = "bug", "Алдаа (Bug)"
        TASK = "task", "Даалгавар (Task)"
        CHANGE_REQUEST = "cr", "Өөрчлөлтийн хүсэлт (CR)"

    class Status(models.TextChoices):
        NEW = "new", "Шинэ"
        ASSIGNED = "assigned", "Оноогдсон"
        IN_PROGRESS = "in_progress", "Хийгдэж байгаа"
        RESOLVED = "resolved", "Шийдэгдсэн"
        REJECTED = "rejected", "Татгалзсан"
        QA_TEST = "qa_test", "Чанарын шалгалтад"
        REOPENED = "reopened", "Дахин нээгдсэн"
        CLOSED = "closed", "Хаагдсан"

    class Priority(models.TextChoices):
        LOW = "low", "Бага"
        MEDIUM = "medium", "Дунд"
        HIGH = "high", "Өндөр"
        CRITICAL = "critical", "Яаралтай"

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
    sla_due_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Priority-с хамаарсан хариу үйлдэл хийх дээд хугацаа "
            "(settings.SLA_HOURS_BY_PRIORITY-ээс ticket үүсэх мөчид автоматаар тооцоологдоно)."
        ),
    )

    # Эдгээр статустай ticket цаашид SLA хугацаанд хамаарахгүй гэж үзнэ
    # (ажил дууссан/хаагдсан тул хугацаа хэтэрсэн эсэхийг тооцох шаардлагагүй).
    _SLA_EXEMPT_STATUSES = {"closed", "rejected"}

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"#{self.pk} {self.title}"

    @property
    def is_overdue(self):
        """SLA хугацаа хэтэрсэн эсэх (хаагдсан/татгалзсан ticket-д хамаарахгүй)."""
        if self.status in self._SLA_EXEMPT_STATUSES:
            return False
        if not self.sla_due_at:
            return False
        return timezone.now() > self.sla_due_at

    def _calculate_sla_due_at(self):
        """Priority-с хамаарсан SLA хугацааг тооцоолж буцаана (settings.SLA_HOURS_BY_PRIORITY)."""
        hours = settings.SLA_HOURS_BY_PRIORITY.get(self.priority, 72)
        return timezone.now() + timedelta(hours=hours)

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
        if is_new and self.sla_due_at is None:
            self.sla_due_at = self._calculate_sla_due_at()
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
    is_internal = models.BooleanField(
        default=False,
        help_text="Тэмдэглэгдсэн бол зөвхөн дотоод багийн гишүүд харна (Zendesk/Freshdesk-ийн 'Internal note' шиг).",
    )

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        marker = " [internal]" if self.is_internal else ""
        return f"Comment #{self.pk} on Ticket #{self.ticket_id}{marker}"


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
