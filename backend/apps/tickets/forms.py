from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Attachment, Comment, Ticket


class TicketForm(forms.ModelForm):
    class Meta:
        model = Ticket
        fields = [
            "title",
            "description",
            "ticket_type",
            "category",
            "project",
            "module",
            "priority",
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


class AttachmentForm(forms.ModelForm):
    class Meta:
        model = Attachment
        fields = ["file"]
        widgets = {
            "file": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }
