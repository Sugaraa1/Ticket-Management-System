from django.contrib import admin

from .models import Attachment, Comment, StatusHistory, Ticket


class CommentInline(admin.TabularInline):
    model = Comment
    extra = 0
    fields = ("author", "body", "is_internal", "created_at")
    readonly_fields = ("author", "created_at")


class AttachmentInline(admin.TabularInline):
    model = Attachment
    extra = 0
    readonly_fields = ("uploaded_by", "created_at")


class StatusHistoryInline(admin.TabularInline):
    model = StatusHistory
    extra = 0
    readonly_fields = ("from_status", "to_status", "changed_by", "changed_at")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "ticket_type",
        "category",
        "team",
        "status",
        "priority",
        "assigned_to",
        "sla_due_at",
        "overdue_marker",
        "created_at",
    )
    list_filter = ("status", "priority", "ticket_type", "category", "team")
    search_fields = ("title", "description")
    autocomplete_fields = ("category", "project", "module", "assigned_to", "reported_by")
    inlines = [CommentInline, AttachmentInline, StatusHistoryInline]

    @admin.display(description="SLA", boolean=True)
    def overdue_marker(self, obj):
        """Жагсаалтад хугацаа хэтэрсэн ticket-ийг улаан ✗ тэмдгээр тодруулна."""
        return not obj.is_overdue

    def save_model(self, request, obj, form, change):
        obj._changed_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("id", "ticket", "author", "is_internal", "short_body", "created_at")
    list_filter = ("is_internal",)
    search_fields = ("body",)

    @admin.display(description="Сэтгэгдэл")
    def short_body(self, obj):
        return (obj.body[:60] + "…") if len(obj.body) > 60 else (obj.body or "—")
