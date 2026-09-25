from django import forms
from django.utils.translation import gettext_lazy as _

from .models import Module, Project


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "description", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input", "role": "switch"}),
        }
        labels = {"name": _("Нэр"), "description": _("Тайлбар"), "is_active": _("Идэвхтэй")}


class ModuleForm(forms.ModelForm):
    class Meta:
        model = Module
        fields = ["name"]
        widgets = {"name": forms.TextInput(attrs={"class": "form-control"})}
        labels = {"name": _("Модулийн нэр")}

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.project = project or getattr(self.instance, "project", None)

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        duplicate = Module.objects.filter(project=self.project, name__iexact=name).exclude(
            pk=self.instance.pk
        )
        if duplicate.exists():
            raise forms.ValidationError(_("Энэ төсөлд ийм нэртэй модуль аль хэдийн байна."))
        return name
