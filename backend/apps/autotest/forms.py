import json
import os

from django import forms
from django.utils.translation import gettext_lazy as _

from apps.categories.models import Category, Subcategory

from .datafiles import DataFileError, read_rows
from .models import DataFile, Environment, Page, Scenario, TestAccount, TestApp

MAX_UPLOAD_MB = 5
FIELD_SOURCES = {"column", "constant", "check", "skip"}
FIELD_KINDS = {"text", "email", "password", "checkbox", "radio", "select"}


class TestAppForm(forms.ModelForm):
    LOGIN_FIELDS = ("login_page", "api_login_path", "api_login_body", "api_token_prefix")

    class Meta:
        model = TestApp
        fields = [
            "name", "category", "subcategory", "login_page", "api_login_path", "api_login_body", "api_token_prefix",
            "description",
        ]
        widgets = {
            "category": forms.Select(attrs={"class": "form-select"}),
            "subcategory": forms.Select(attrs={"class": "form-select"}),
            "login_page": forms.Select(attrs={"class": "form-select"}),
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": _("Жишээ: Дэлгүүрийн вэб")}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "api_login_path": forms.TextInput(attrs={"class": "form-control font-monospace", "placeholder": "/api/auth/login/"}),
            "api_login_body": forms.Textarea(attrs={"class": "form-control font-monospace small", "rows": 2}),
            "api_token_prefix": forms.TextInput(attrs={"class": "form-control font-monospace", "placeholder": "Bearer"}),
        }
        labels = {
            "category": _("Ангилал"), "subcategory": _("Дэд ангилал"),
            "api_login_path": _("Нэвтрэх зам"), "api_login_body": _("Нэвтрэх body"),
        }
        help_texts = {"api_login_path": ""}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.all()
        self.fields["subcategory"].queryset = Subcategory.objects.select_related("category")
        if self.instance.pk:  # шинэ апп-д хуудас хараахан байхгүй
            self.fields["login_page"].queryset = self.instance.pages.all()
        else:
            for name in self.LOGIN_FIELDS:
                del self.fields[name]

    @property
    def api_tab(self):
        """API нэвтрэлт л тохируулсан, эсвэл түүний талбарт алдаа гарсан бол API tab-ыг нээнэ."""
        if any(name in self.errors for name in self.LOGIN_FIELDS[1:]):
            return True
        return bool(self.instance.api_login_path and not self.instance.login_page_id)

    def clean_api_login_path(self):
        path = clean_page_path(self.cleaned_data.get("api_login_path"))
        return "/" + path if path and not path.startswith("/") else path

    def clean(self):
        cleaned = super().clean()
        category, subcategory, name = cleaned.get("category"), cleaned.get("subcategory"), cleaned.get("name")
        if subcategory and category and subcategory.category_id != category.id:
            self.add_error("subcategory", _("Сонгосон дэд ангилал сонгосон ангилалд харьяалагдахгүй байна."))
        if category and name:
            duplicate = TestApp.objects.filter(category=category, name__iexact=name).exclude(pk=self.instance.pk)
            if duplicate.exists():
                self.add_error("name", _("Энэ ангилалд ийм нэртэй апп бүртгэлтэй байна."))
        return cleaned


class EnvironmentForm(forms.ModelForm):
    class Meta:
        model = Environment
        fields = ["name", "base_url", "is_production"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "staging"}),
            "base_url": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://staging.shop.mn"}),
            "is_production": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, app=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.app = app

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if self.app and self.app.environments.filter(name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("'%(name)s' нэртэй орчин аль хэдийн байна.") % {"name": name})
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
        fields = ["category", "name", "file"]
        widgets = {
            "category": forms.Select(attrs={"class": "form-select"}),
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": _("Жишээ: Хэрэглэгчид v1")}),
            "file": forms.ClearableFileInput(attrs={"class": "form-control", "accept": ".xlsx,.csv"}),
        }
        labels = {"category": _("Ангилал"), "file": _("Файл (.xlsx / .csv)")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.all()
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


def clean_page_path(value):
    """Орчны хаягаас хойших зам л байна — бүтэн URL бичвэл орчны хязгаарлалтыг тойрно."""
    value = (value or "").strip()
    if "://" in value or value.startswith("//"):
        raise forms.ValidationError(_("Бүтэн хаяг биш, орчны хаягаас хойших замыг бичнэ үү (жишээ: /register)."))
    return value


class PageForm(forms.ModelForm):
    class Meta:
        model = Page
        fields = ["name", "path"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": _("Бүртгүүлэх")}),
            "path": forms.TextInput(attrs={"class": "form-control", "placeholder": "/register"}),
        }

    def __init__(self, *args, app=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.app = app

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if self.app and self.app.pages.filter(name__iexact=name).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("'%(name)s' нэртэй хуудас аль хэдийн байна.") % {"name": name})
        return name

    def clean_path(self):
        path = clean_page_path(self.cleaned_data.get("path"))
        if path and not path.startswith("/"):
            path = "/" + path
        duplicate = self.app and self.app.pages.filter(path=path).exclude(pk=self.instance.pk).first()
        if duplicate:
            raise forms.ValidationError(
                _("Энэ зам '%(name)s' хуудсанд бүртгэлтэй байна.") % {"name": duplicate.name}
            )
        return path


class TestAccountForm(forms.Form):
    """Ижил нэртэй хэрэглэгч байвал нэвтрэх нэр, нууц үгийг нь шинэчилнэ."""
    label = forms.CharField(
        max_length=50, widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "QA"})
    )
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": _("нэвтрэх нэр"), "autocomplete": "off"}),
    )
    password = forms.CharField(
        max_length=200,
        widget=forms.PasswordInput(attrs={"class": "form-control", "placeholder": _("нууц үг"), "autocomplete": "new-password"}),
    )

    def save(self, app):
        label = self.cleaned_data["label"].strip()
        account = app.accounts.filter(label__iexact=label).first() or TestAccount(app=app, label=label)
        account.username = self.cleaned_data["username"].strip()
        account.set_password(self.cleaned_data["password"])
        created = account.pk is None
        account.save()
        return account, created


class ScenarioForm(forms.ModelForm):
    fields_json = forms.CharField(widget=forms.HiddenInput, required=False)

    class Meta:
        model = Scenario
        fields = [
            "name", "page", "account", "submit_selector", "submit_label", "success_mode", "success_value",
            "error_selector", "expected_column", "expected_message_column",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "page": forms.Select(attrs={"class": "form-select"}),
            "account": forms.Select(attrs={"class": "form-select"}),
            "submit_selector": forms.HiddenInput,
            "submit_label": forms.HiddenInput,
            "success_mode": forms.Select(attrs={"class": "form-select"}),
            "success_value": forms.TextInput(attrs={"class": "form-control", "placeholder": _("Жишээ: /welcome эсвэл Амжилттай")}),
            "error_selector": forms.TextInput(attrs={"class": "form-control", "placeholder": ".error-message"}),
            "expected_column": forms.TextInput(attrs={"class": "form-control", "list": "column-options"}),
            "expected_message_column": forms.TextInput(attrs={"class": "form-control", "list": "column-options"}),
        }

    def __init__(self, *args, app, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["page"].queryset = app.pages.all()
        self.fields["page"].empty_label = None
        self.fields["page"].required = True
        self.fields["account"].queryset = app.accounts.all()
        self.fields["account"].empty_label = _("Нэвтрэхгүй")
        self.app = app
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
        if cleaned.get("account") and not self.app.login_page_id:
            self.add_error("account", _("Эхлээд апп-ын мэдээлэлд нэвтрэх хуудсаа сонгоно уу."))
        if cleaned.get("success_mode") in ("url_contains", "text_visible") and not cleaned.get("success_value"):
            self.add_error("success_value", _("Нөхцөлийн текстийг бичнэ үү."))
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.fields = self.cleaned_data["fields_json"]
        if commit:
            instance.save()
        return instance


class ApiScenarioForm(forms.ModelForm):
    api_method = forms.ChoiceField(
        label=_("Method"), choices=[(m, m) for m in ("GET", "POST", "PUT", "PATCH", "DELETE")],
        widget=forms.Select(attrs={"class": "form-select font-monospace"}),
    )

    class Meta:
        model = Scenario
        fields = [
            "name", "account", "api_method", "api_path", "api_headers", "api_body",
            "expected_column", "expected_message_column",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": _("Жишээ: Ticket үүсгэх")}),
            "account": forms.Select(attrs={"class": "form-select"}),
            "api_path": forms.TextInput(attrs={"class": "form-control font-monospace", "placeholder": "/api/tickets/{{id}}"}),
            "api_headers": forms.Textarea(attrs={"class": "form-control font-monospace small", "rows": 2,
                                                 "placeholder": "X-API-Key: …"}),
            "api_body": forms.Textarea(attrs={"class": "form-control font-monospace small", "rows": 8,
                                              "placeholder": '{"email": "{{email}}", "age": {{age}}}'}),
            "expected_column": forms.TextInput(attrs={"class": "form-control", "list": "column-options"}),
            "expected_message_column": forms.TextInput(attrs={"class": "form-control", "list": "column-options"}),
        }
        help_texts = {
            "expected_column": _("'201', '400: мессеж', 'амжилттай' эсвэл 'алдаа: мессеж' гэж бичсэн багана."),
        }

    def __init__(self, *args, app, **kwargs):
        super().__init__(*args, **kwargs)
        self.app = app
        self.fields["account"].queryset = app.accounts.all()
        self.fields["account"].empty_label = _("Нэвтрэхгүй")
        self.fields["api_path"].required = True

    def clean_api_path(self):
        path = clean_page_path(self.cleaned_data.get("api_path"))
        return "/" + path if path and not path.startswith("/") else path

    def clean(self):
        from .api import check_body_template, parse_headers

        cleaned = super().clean()
        try:
            headers = parse_headers(cleaned.get("api_headers"))
        except ValueError as exc:
            self.add_error("api_headers", str(exc))
            headers = []
        try:
            check_body_template(cleaned.get("api_body") or "", headers)
        except ValueError as exc:
            self.add_error("api_body", str(exc))
        if cleaned.get("account") and not self.app.api_login_path:
            self.add_error("account", _("Эхлээд апп-ын мэдээлэлд API нэвтрэх замаа бичнэ үү."))
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.kind = Scenario.Kind.API
        instance.page = None
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
        self.fields["data_file"].queryset = DataFile.objects.filter(category_id=scenario.app.category_id)
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
