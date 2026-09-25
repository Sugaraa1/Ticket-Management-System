import re
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.categories.models import Category
from apps.core.models import TimeStampedModel
from apps.projects.models import Module, Project

from .storage import private_storage

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


def format_ticket_code(pk):
    return f"{settings.TICKET_CODE_PREFIX}{pk or 0:06d}"


def parse_ticket_code(text):
    """'FXT000012' / 'fxt12' -> 12; тохирохгүй бол None."""
    prefix = settings.TICKET_CODE_PREFIX
    match = re.fullmatch(rf"(?i){re.escape(prefix)}0*(\d+)", (text or "").strip())
    return int(match.group(1)) if match else None


class Ticket(TimeStampedModel):
    class TicketType(models.TextChoices):
        BUG = "bug", _("Алдаа (Bug)")
        TASK = "task", _("Даалгавар (Task)")
        CHANGE_REQUEST = "cr", _("Өөрчлөлтийн хүсэлт (CR)")

    class Status(models.TextChoices):
        NEW = "new", _("Шинэ")
        ASSIGNED = "assigned", _("Оноогдсон")
        IN_PROGRESS = "in_progress", _("Хийгдэж байгаа")
        RESOLVED = "resolved", _("Шийдэгдсэн")
        REJECTED = "rejected", _("Татгалзсан")
        QA_TEST = "qa_test", _("Чанарын шалгалтад")
        REOPENED = "reopened", _("Дахин нээгдсэн")
        CLOSED = "closed", _("Хаагдсан")

    class Priority(models.TextChoices):
        LOW = "low", _("Бага")
        MEDIUM = "medium", _("Дунд")
        HIGH = "high", _("Өндөр")
        CRITICAL = "critical", _("Яаралтай")

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
        help_text=_("Category-ийн CategoryTeamAssignment-аас автоматаар тохируулагдана."),
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
        help_text=_(
            "Priority-с хамаарсан хариу үйлдэл хийх дээд хугацаа "
            "(settings.SLA_HOURS_BY_PRIORITY-ээс ticket үүсэх мөчид автоматаар тооцоологдоно)."
        ),
    )
    sla_warning_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_(
            "SLA хугацаа дуусахад ойртсон тухай анхааруулга илгээсэн огноо "
            "(check_sla_deadlines командаар бичигдэнэ, давхар мэдэгдэл илгээхээс сэргийлнэ)."
        ),
    )
    sla_breach_notified_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_(
            "SLA хугацаа хэтэрсэн тухай escalation мэдэгдэл илгээсэн огноо "
            "(check_sla_deadlines командаар бичигдэнэ, давхар мэдэгдэл илгээхээс сэргийлнэ)."
        ),
    )
    first_response_due_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_(
            "'Time to First Response' SLA — эхний хариу өгөх дээд хугацаа "
            "(settings.SLA_FIRST_RESPONSE_HOURS_BY_PRIORITY-ээс автоматаар тооцоологдоно)."
        ),
    )
    first_responded_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_(
            "Ticket-д анх удаа хариу өгсөн (NEW-аас шилжсэн эсвэл мэдээлэгчээс бусад "
            "хүн comment бичсэн) огноо."
        ),
    )
    first_response_warning_sent_at = models.DateTimeField(null=True, blank=True)
    first_response_breach_notified_at = models.DateTimeField(null=True, blank=True)
    last_activity_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_(
            "Ticket дээр сүүлд ямар нэгэн идэвх (status шилжилт, comment, "
            "attachment) гарсан огноо — 'идэвхгүй ticket' automation-д ашиглагдана."
        ),
    )
    stale_reminder_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text=_(
            "Идэвхгүй байдлын тухай сүүлд сануулга илгээсэн огноо "
            "(check_stale_tickets командаар бичигдэнэ). Шинэ идэвх гарахад "
            "цэвэрлэгдэж, дараагийн удаа дахин сануулах боломжтой болно."
        ),
    )

    # Эдгээр статустай ticket цаашид SLA хугацаанд хамаарахгүй гэж үзнэ
    # (ажил дууссан/хаагдсан тул хугацаа хэтэрсэн эсэхийг тооцох шаардлагагүй).
    _SLA_EXEMPT_STATUSES = {"closed", "rejected"}

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.code} {self.title}"

    @property
    def code(self):
        """Хэрэглэгчид харагдах 9 оронтой дугаар: 3 үсэг + 6 цифр (жишээ: FXT000001)."""
        return format_ticket_code(self.pk)

    @classmethod
    def priority_choices_with_sla(cls):
        """
        Priority сонголт бүрд харгалзах Time to First Response / Time to
        Resolution хугацааг (цагаар) хамт харуулна — priority сонгох мөчид
        SLA-ийн үр дагаврыг шууд ойлгомжтой болгох зорилготой (ticket
        үүсгэх/засах маягт, ticket жагсаалтын шүүлтүүрт ашиглагдана).
        """
        return [
            (
                value,
                _("%(label)s — хариу: %(first_response)sц, шийдвэрлэлт: %(resolution)sц")
                % {
                    "label": label,
                    "first_response": settings.SLA_FIRST_RESPONSE_HOURS_BY_PRIORITY.get(value),
                    "resolution": settings.SLA_HOURS_BY_PRIORITY.get(value),
                },
            )
            for value, label in cls.Priority.choices
        ]

    @property
    def is_overdue(self):
        """SLA хугацаа хэтэрсэн эсэх (хаагдсан/татгалзсан ticket-д хамаарахгүй)."""
        if self.status in self._SLA_EXEMPT_STATUSES:
            return False
        if not self.sla_due_at:
            return False
        return timezone.now() > self.sla_due_at

    @property
    def sla_warning_at(self):
        """
        Resolution SLA "анхааруулга" мэдэгдэл илгээх ёстой цаг хугацаа
        (settings.SLA_WARNING_THRESHOLD хувиар тооцоологдоно, жишээ нь эцсийн
        хугацааны 80%-д хүрэхэд). sla_due_at байхгүй бол None буцаана.
        """
        return self._warning_at(self.sla_due_at)

    @property
    def is_first_response_overdue(self):
        """Time to First Response SLA хэтэрсэн эсэх (аль хэдийн хариу өгсөн бол False)."""
        if self.first_responded_at is not None:
            return False
        if self.status in self._SLA_EXEMPT_STATUSES:
            return False
        if not self.first_response_due_at:
            return False
        return timezone.now() > self.first_response_due_at

    @property
    def first_response_warning_at(self):
        """Time to First Response SLA-ийн "анхааруулга" мэдэгдэл илгээх цаг хугацаа."""
        return self._warning_at(self.first_response_due_at)

    def _warning_at(self, due_at):
        if not due_at:
            return None
        total_duration = due_at - self.created_at
        return self.created_at + total_duration * settings.SLA_WARNING_THRESHOLD

    def _calculate_sla_due_at(self):
        """Priority-с хамаарсан Resolution SLA хугацааг тооцоолж буцаана."""
        hours = settings.SLA_HOURS_BY_PRIORITY.get(self.priority, 72)
        return timezone.now() + timedelta(hours=hours)

    def _calculate_first_response_due_at(self):
        """Priority-с хамаарсан First Response SLA хугацааг тооцоолж буцаана."""
        hours = settings.SLA_FIRST_RESPONSE_HOURS_BY_PRIORITY.get(self.priority, 24)
        return timezone.now() + timedelta(hours=hours)

    def mark_first_response(self, when=None):
        """
        Ticket-д анх удаа хариу өгснийг тэмдэглэнэ (Time to First Response SLA-г зогсооно).
        Аль хэдийн тэмдэглэгдсэн бол дахин бичихгүй.
        """
        if self.first_responded_at is not None or self.pk is None:
            return
        when = when or timezone.now()
        updated = Ticket.objects.filter(pk=self.pk, first_responded_at__isnull=True).update(
            first_responded_at=when
        )
        if updated:
            self.first_responded_at = when

    def mark_activity(self, when=None):
        """
        Ticket дээр идэвх (comment, attachment гэх мэт) гарсныг тэмдэглэж,
        'идэвхгүй ticket' automation-ий хугацааг шинэчилнэ (stale reminder
        clock-ыг тэглэж, дараагийн удаа дахин сануулах боломжтой болгоно).
        """
        if self.pk is None:
            return
        when = when or timezone.now()
        Ticket.objects.filter(pk=self.pk).update(
            last_activity_at=when, stale_reminder_sent_at=None
        )
        self.last_activity_at = when
        self.stale_reminder_sent_at = None

    def change_priority(self, new_priority, user=None):
        """
        Priority-г сольж, SLA хугацааг ticket үүссэн мөчөөс эхлэн шинэ priority-оор
        дахин тооцоолно (Jira SM-ийн адил). Анхааруулга/escalation тэмдэглэгээг
        цэвэрлэж, шинэ хугацаанд дахин шалгагдах боломжтой болгоно.
        """
        if new_priority == self.priority:
            return False
        old_label = self.get_priority_display()
        self.priority = new_priority
        start = self.created_at or timezone.now()
        self.sla_due_at = start + timedelta(
            hours=settings.SLA_HOURS_BY_PRIORITY.get(new_priority, 72)
        )
        self.sla_warning_sent_at = None
        self.sla_breach_notified_at = None
        update_fields = [
            "priority", "sla_due_at", "sla_warning_sent_at", "sla_breach_notified_at", "updated_at",
        ]
        if self.first_responded_at is None:
            self.first_response_due_at = start + timedelta(
                hours=settings.SLA_FIRST_RESPONSE_HOURS_BY_PRIORITY.get(new_priority, 24)
            )
            self.first_response_warning_sent_at = None
            self.first_response_breach_notified_at = None
            update_fields += [
                "first_response_due_at",
                "first_response_warning_sent_at",
                "first_response_breach_notified_at",
            ]
        self.save(update_fields=update_fields)
        Comment.objects.create(
            ticket=self,
            author=user,
            body=_("Чухлын зэрэг өөрчлөгдлөө: %(old)s → %(new)s") % {
                "old": old_label, "new": self.get_priority_display(),
            },
        )
        self.mark_activity()
        return True

    def _auto_route_team(self):
        """Category-ийн багуудаас хамгийн бага ачаалалтайг team талбарт автоматаар тавина."""
        if self.category_id and not self.team_id:
            from apps.categories.models import route_team_for_category

            team = route_team_for_category(self.category_id)
            if team:
                self.team_id = team.id

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
                        _(
                            "'%(from_status)s' -> '%(to_status)s' төлөв шилжилт "
                            "зөвшөөрөгдөөгүй байна (docs/workflow.md-г үзнэ үү)."
                        )
                        % {"from_status": original_status, "to_status": self.status}
                    )
                if original_status == self.Status.NEW and self.first_responded_at is None:
                    # NEW-аас гарсан мөч бол баг анхны хариугаа өгсөн гэж үзнэ
                    # (Time to First Response SLA зогсоно).
                    self.first_responded_at = timezone.now()
                # Status шилжилт бол идэвх гэж тооцоод "идэвхгүй ticket" сануулгын
                # цагийг шинэчилнэ (дараагийн сануулга дахин N цагийн дараа очно).
                self.last_activity_at = timezone.now()
                self.stale_reminder_sent_at = None

        self._auto_route_team()
        if is_new and self.sla_due_at is None:
            self.sla_due_at = self._calculate_sla_due_at()
        if is_new and self.first_response_due_at is None:
            self.first_response_due_at = self._calculate_first_response_due_at()
        if is_new and self.last_activity_at is None:
            self.last_activity_at = timezone.now()
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
                _("'%(from_status)s' -> '%(to_status)s' төлөв шилжилт зөвшөөрөгдөөгүй.")
                % {"from_status": self.status, "to_status": new_status}
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
        help_text=_(
            "Тэмдэглэгдсэн бол зөвхөн дотоод багийн гишүүд харна "
            "(Zendesk/Freshdesk-ийн 'Internal note' шиг)."
        ),
    )

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        marker = " [internal]" if self.is_internal else ""
        return f"Comment #{self.pk} on {format_ticket_code(self.ticket_id)}{marker}"


class Attachment(TimeStampedModel):
    ticket = models.ForeignKey(Ticket, related_name="attachments", on_delete=models.CASCADE)
    file = models.FileField(upload_to="attachments/%Y/%m/", storage=private_storage)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Attachment #{self.pk} on {format_ticket_code(self.ticket_id)}"


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
        return f"{format_ticket_code(self.ticket_id)}: {self.from_status or '—'} → {self.to_status}"
