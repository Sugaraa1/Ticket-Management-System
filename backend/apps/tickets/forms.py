from django import forms

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
            "title": "Гарчиг",
            "description": "Тайлбар",
            "ticket_type": "Төрөл",
            "category": "Ангилал",
            "project": "Төсөл",
            "module": "Модуль",
            "priority": "Чухлын зэрэг",
        }


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ["body"]
        widgets = {
            "body": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 2,
                    "placeholder": "Сэтгэгдэл бичих (сонголтоор)...",
                }
            ),
        }


class AttachmentForm(forms.ModelForm):
    class Meta:
        model = Attachment
        fields = ["file"]
        widgets = {
            "file": forms.ClearableFileInput(attrs={"class": "form-control"}),
        }
