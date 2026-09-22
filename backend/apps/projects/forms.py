from django import forms

from .models import Module, Project


class ProjectForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["name", "description", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }
        labels = {"name": "Нэр", "description": "Тайлбар", "is_active": "Идэвхтэй"}


class ModuleForm(forms.ModelForm):
    class Meta:
        model = Module
        fields = ["name"]
        widgets = {"name": forms.TextInput(attrs={"class": "form-control"})}
        labels = {"name": "Модулийн нэр"}
