import json
import os

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.projects.models import Project

from .datafiles import DataFileError, read_rows
from .models import DataFile, Environment, Scenario, TestApp

MAX_UPLOAD_MB = 5
FIELD_SOURCES = {"column", "constant", "check", "skip"}
FIELD_KINDS = {"text", "email", "password", "checkbox", "radio", "select"}


class TestAppForm(forms.ModelForm):
    class Meta:
        model = TestApp
        fields = ["project", "name", "description"]
        widgets = {
            "project": forms.Select(attrs={"class": "form-select"}),
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": _("Жишээ: Дэлгүүрийн вэб")}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }
        labels = {"project": _("Төсөл")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = Project.objects.filter(is_active=True)

    def clean(self):
        cleaned = super().clean()
        project, name = cleaned.get("project"), cleaned.get("name")
        if project and name:
            duplicate = TestApp.objects.filter(project=project, name__iexact=name).exclude(pk=self.instance.pk)
            if duplicate.exists():
                self.add_error("name", _("Энэ төсөлд ийм нэртэй апп бүртгэлтэй байна."))
        return cleaned


class EnvironmentForm(forms.ModelForm):
    class Meta:
        model = Environment
        fields = ["name", "base_url"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "staging"}),
            "base_url": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://staging.shop.mn"}),
        }

    def __init__(self, *args, app=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.app = app

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if self.app and self.app.environments.filter(name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("Ийм нэртэй орчин бүртгэлтэй байна."))
        return name


def _read_upload(uploaded):
    if uploaded.size > MAX_UPLOAD_MB * 1024 * 1024:
        raise forms.ValidationError(_("Файлын хэмжээ %(max)sMB-аас хэтэрсэн байна.") % {"max": MAX_UPLOAD_MB})
    try:
        return read_rows(uploaded, uploaded.name)
    except DataFileError as exc:
        raise forms.ValidationError(str(exc))


class DataFileForm(forms.ModelForm):
    class Meta:
        model = DataFile
        fields = ["project", "name", "file"]
        widgets = {
            "project": forms.Select(attrs={"class": "form-select"}),
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": _("Жишээ: Хэрэглэгчид v1")}),
            "file": forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".xlsx,.csv"}),
        }
        labels = {"project": _("Төсөл"), "file": _("Файл (.xlsx / .csv)")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["project"].queryset = Project.objects.filter(is_active=True)
        self.fields["name"].required = False
        self.fields["name"].help_text = _("Хоосон орхивол файлын нэрийг авна.")

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        self.columns, rows = _read_upload(uploaded)
        self.row_count = len(rows)
        return uploaded

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.columns, instance.row_count = self.columns, self.row_count
        if not instance.name:
            instance.name = os.path.splitext(os.path.basename(instance.file.name))[0][:150]
        if commit:
            instance.save()
        return instance


class DataFileReplaceForm(forms.Form):
    file = forms.FileField(
        label=_("Шинэ файл"),
        widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".xlsx,.csv"}),
    )

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        self.columns, rows = _read_upload(uploaded)
        self.row_count = len(rows)
        return uploaded


class ScenarioForm(forms.ModelForm):
    fields_json = forms.CharField(widget=forms.HiddenInput, required=False)

    class Meta:
        model = Scenario
        fields = [
            "name", "page_path", "submit_selector", "submit_label", "success_mode", "success_value",
            "error_selector", "expected_column", "expected_message_column",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "page_path": forms.TextInput(attrs={"class": "form-control", "placeholder": "/register"}),
            "submit_selector": forms.HiddenInput,
            "submit_label": forms.HiddenInput,
            "success_mode": forms.Select(attrs={"class": "form-select"}),
            "success_value": forms.TextInput(attrs={"class": "form-control", "placeholder": _("Жишээ: /welcome эсвэл Амжилттай")}),
            "error_selector": forms.TextInput(attrs={"class": "form-control", "placeholder": ".error-message"}),
            "expected_column": forms.TextInput(attrs={"class": "form-control", "list": "column-options"}),
            "expected_message_column": forms.TextInput(attrs={"class": "form-control", "list": "column-options"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.is_bound:
            self.initial["fields_json"] = json.dumps(self.instance.fields or [], ensure_ascii=False)

    def clean_fields_json(self):
        try:
            fields = json.loads(self.cleaned_data.get("fields_json") or "[]")
        except ValueError:
            raise forms.ValidationError(_("Талбарын тохиргоо буруу байна. Хуудсыг дахин шалгана уу."))
        if not isinstance(fields, list) or not all(isinstance(f, dict) for f in fields):
            raise forms.ValidationError(_("Талбарын тохиргоо буруу байна. Хуудсыг дахин шалгана уу."))
        cleaned = []
        for field in fields:
            source = field.get("source", "skip")
            selector = str(field.get("selector", "")).strip()
            if source not in FIELD_SOURCES or not selector:
                raise forms.ValidationError(_("Талбарын тохиргоо буруу байна. Хуудсыг дахин шалгана уу."))
            value = str(field.get("value", "")).strip()
            if source == "column" and not value:
                raise forms.ValidationError(
                    _("'%(label)s' талбарт багана сонгоогүй байна.") % {"label": field.get("label") or selector}
                )
            cleaned.append({
                "label": str(field.get("label", ""))[:120],
                "selector": selector[:500],
                "kind": field.get("kind") if field.get("kind") in FIELD_KINDS else "text",
                "source": source,
                "value": value[:500],
                "name": str(field.get("name", ""))[:150],
                "id": str(field.get("id", ""))[:150],
                "placeholder": str(field.get("placeholder", ""))[:150],
                "required": bool(field.get("required")),
                "options": [str(o)[:120] for o in field.get("options", [])][:50],
            })
        if not any(f["source"] != "skip" for f in cleaned):
            raise forms.ValidationError(_("Дор хаяж нэг талбарыг бөглөхөөр тохируулна уу."))
        return cleaned

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("success_mode") in ("url_contains", "text_visible") and not cleaned.get("success_value"):
            self.add_error("success_value", _("Нөхцөлийн текстийг бичнэ үү."))
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.fields = self.cleaned_data["fields_json"]
        if commit:
            instance.save()
        return instance


class RunForm(forms.Form):
    data_file = forms.ModelChoiceField(
        queryset=DataFile.objects.none(), label=_("Өгөгдлийн файл"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    environment = forms.ModelChoiceField(
        queryset=Environment.objects.none(), label=_("Орчин"),
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, scenario, **kwargs):
        super().__init__(*args, **kwargs)
        self.scenario = scenario
        self.fields["data_file"].queryset = DataFile.objects.filter(project_id=scenario.app.project_id)
        self.fields["environment"].queryset = scenario.app.environments.all()
        self.fields["data_file"].label_from_instance = lambda f: f"{f.name} ({f.row_count})"
        self.fields["environment"].label_from_instance = lambda e: f"{e.name} — {e.base_url}"

    def clean_data_file(self):
        data_file = self.cleaned_data["data_file"]
        missing = self.scenario.missing_columns(data_file)
        if missing:
            raise forms.ValidationError(
                _("Энэ файлд сценарид хэрэгтэй багана алга: %(cols)s") % {"cols": ", ".join(missing)}
            )
        return data_file
