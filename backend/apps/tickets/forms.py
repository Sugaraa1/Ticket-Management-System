import os

from django import forms
from django.conf import settings
from django.utils.translation import gettext_lazy as _

from .models import Attachment, Comment, Ticket


def validate_attachment(uploaded):
    """Файлын хэмжээ, өргөтгөлийг settings-ийн хязгаартай тулгана."""
    if not uploaded:
        return uploaded
    max_mb = settings.ATTACHMENT_MAX_SIZE_MB
    if uploaded.size > max_mb * 1024 * 1024:
        raise forms.ValidationError(
            _("Файлын хэмжээ %(max)sMB-аас хэтэрсэн байна.") % {"max": max_mb}
        )
    ext = os.path.splitext(uploaded.name)[1].lower().lstrip(".")
    if ext not in settings.ATTACHMENT_ALLOWED_EXTENSIONS:
        raise forms.ValidationError(
            _("'.%(ext)s' төрлийн файл зөвшөөрөгдөхгүй. Зөвшөөрөгдөх: %(allowed)s")
            % {"ext": ext, "allowed": ", ".join(settings.ATTACHMENT_ALLOWED_EXTENSIONS)}
        )
    return uploaded


def attachment_help_text():
    return _("Хамгийн ихдээ %(max)sMB. Зөвшөөрөгдөх төрөл: %(allowed)s") % {
        "max": settings.ATTACHMENT_MAX_SIZE_MB,
        "allowed": ", ".join(settings.ATTACHMENT_ALLOWED_EXTENSIONS),
    }


class TicketForm(forms.ModelForm):
    attachment = forms.FileField(
        required=False,
        label=_("Хавсралт"),
        widget=forms.ClearableFileInput(attrs={"class": "form-control"}),
    )

    class Meta:
        model = Ticket
        fields = [
            "title",
            "ticket_type",
            "priority",
            "category",
            "project",
            "module",
            "description",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "ticket_type": forms.Select(attrs={"class": "form-select"}),
            "category": forms.Select(attrs={"class": "form-select"}),
            "project": forms.Select(attrs={"class": "form-select"}),
            "module": forms.Select(attrs={"class": "form-select"}),
            "priority": forms.Select(attrs={"class": "form-select"}),
        }
        labels = {
            "title": _("Гарчиг"),
            "description": _("Тайлбар"),
            "ticket_type": _("Төрөл"),
            "category": _("Ангилал"),
            "project": _("Төсөл"),
            "module": _("Модуль"),
            "priority": _("Чухлын зэрэг"),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["priority"].choices = Ticket.priority_choices_with_sla()
        # Идэвхгүй (дууссан/хаагдсан) төсөлд шинэ ticket үүсгэхгүй.
        self.fields["project"].queryset = self.fields["project"].queryset.filter(is_active=True)
        self.fields["attachment"].help_text = attachment_help_text()
        self.fields["description"].widget.attrs["placeholder"] = _(
            "Алдааны хувьд: давтах алхам, хүлээгдэж буй үр дүн, бодит үр дүн, орчин (browser/төхөөрөмж)."
        )

    def clean_attachment(self):
        return validate_attachment(self.cleaned_data.get("attachment"))

    def clean(self):
        cleaned_data = super().clean()
        project = cleaned_data.get("project")
        module = cleaned_data.get("module")
        if module and project and module.project_id != project.id:
            self.add_error(
                "module",
                _("Сонгосон модуль сонгосон төсөлд харьяалагдахгүй байна."),
            )
        return cleaned_data


class TicketEditForm(forms.ModelForm):
    """Үүссэн ticket-ийн үндсэн мэдээллийг засах. Чухлын зэрэг (SLA дахин тооцоолно),
    төлөв, хариуцагч нь ticket-ийн хуудсан дээр тусдаа өөрчлөгдөнө."""

    class Meta:
        model = Ticket
        fields = ["title", "ticket_type", "category", "project", "module", "description"]
        widgets = {
            key: widget
            for key, widget in TicketForm.Meta.widgets.items()
            if key in ("title", "ticket_type", "category", "project", "module", "description")
        }
        labels = TicketForm.Meta.labels

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from django.db.models import Q

        ticket = self.instance
        # Идэвхгүй төсөл сонголтод гарахгүй, гэхдээ одоо сонгогдсоныг нь үлдээнэ.
        self.fields["project"].queryset = self.fields["project"].queryset.filter(
            Q(is_active=True) | Q(pk=ticket.project_id)
        )
        if ticket.status != Ticket.Status.NEW:
            # Ангилал солигдвол баг солигдоно — оноогдсоны дараа хариуцагч буруу болох тул түгжинэ.
            self.fields["category"].disabled = True
            self.fields["category"].help_text = _(
                "Ticket оноогдсоны дараа ангиллыг солих боломжгүй (баг нь өөрчлөгдөнө)."
            )

    def clean(self):
        cleaned_data = super().clean()
        project, module = cleaned_data.get("project"), cleaned_data.get("module")
        if module and project and module.project_id != project.id:
            self.add_error("module", _("Сонгосон модуль сонгосон төсөлд харьяалагдахгүй байна."))
        return cleaned_data


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ["body", "is_internal"]
        widgets = {
            "body": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 2,
                    "placeholder": _("Сэтгэгдэл бичих (сонголтоор)..."),
                }
            ),
            "is_internal": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {
            "body": _("Сэтгэгдэл"),
            "is_internal": _("Зөвхөн дотоод багт харагдах (Internal note)"),
        }

    def __init__(self, *args, allow_internal=True, **kwargs):
        super().__init__(*args, **kwargs)
        if not allow_internal:
            # Дотоод тэмдэглэл харах эрхгүй хүн бичиж ч чадахгүй.
            del self.fields["is_internal"]
        # Model дээр blank=True (status шилжилтийн тайлбар хоосон байж болно), харин
        # гараар бичих сэтгэгдэл хоосон байж болохгүй.
        self.fields["body"].required = True
        self.fields["body"].widget.attrs["placeholder"] = _("Сэтгэгдэл бичих... (@нэр гэж бичээд хүн дурдана)")


class AttachmentForm(forms.ModelForm):
    class Meta:
        model = Attachment
        fields = ["file"]
        widgets = {
            "file": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["file"].help_text = attachment_help_text()

    def clean_file(self):
        return validate_attachment(self.cleaned_data.get("file"))
