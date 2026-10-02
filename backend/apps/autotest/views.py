import json
import os
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib import messages
from django.core.files.base import ContentFile
from django.db.models import Count, OuterRef, Subquery
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.core.decorators import roles_required
from apps.tickets.forms import TicketForm
from apps.tickets.models import Attachment, Ticket
from apps.tickets.notifications import notify_ticket_routed
from apps.tickets.permissions import AUTOTEST_ROLES, user_roles
from apps.tickets.views import _modules_by_project, _subcategories_by_category

from . import exports, generator
from .datafiles import suggest_mapping
from .forms import (
    ApiScenarioForm, AppLoginForm, DataFileForm, DataFileReplaceForm, EnvironmentForm, PageForm, RunForm, ScenarioForm, TestAccountForm,
    TestAppForm,
)
from . import workflow
from .models import DataFile, Environment, Page, PageScan, RunResult, Scenario, TestAccount, TestApp, TestRun

# Автомат тестийг зөвхөн QA, Admin ашиглана (Dev bug ticket-ээр үр дүнг, зургийг авна).
VIEW_ROLES = EDIT_ROLES = APP_ROLES = AUTOTEST_ROLES
PREVIEW_ROWS = 10
PREVIEW_MODAL_ROWS = 50


def _can_edit(user):
    return bool(user_roles(user) & set(EDIT_ROLES))


def _attach_last_runs(objects, run_filter):
    """objects бүрт `last_run` (хамгийн сүүлийн TestRun эсвэл None) онооно — нэг нэмэлт query."""
    objects = list(objects.annotate(last_run_id=Subquery(
        TestRun.objects.filter(**{run_filter: OuterRef("pk")}).order_by("-created_at").values("pk")[:1]
    )))
    runs = TestRun.objects.in_bulk([o.last_run_id for o in objects if o.last_run_id])
    for obj in objects:
        obj.last_run = runs.get(obj.last_run_id)
    return objects


def _flash_form_errors(request, form):
    for errors in form.errors.values():
        for error in errors:
            messages.error(request, error)


# --- Нүүр ---------------------------------------------------------------

@roles_required(*VIEW_ROLES)
def home(request):
    apps = _attach_last_runs(TestApp.objects.select_related("category", "subcategory").annotate(
        scenario_count=Count("scenarios", distinct=True),
        env_count=Count("environments", distinct=True),
    ), "scenario__app")
    runs = TestRun.objects.select_related("scenario__app", "started_by")[:15]
    return render(request, "autotest/home.html", {
        "apps": apps,
        "runs": runs,
        "data_file_count": DataFile.objects.count(),
        "can_edit": _can_edit(request.user),
        "can_manage_apps": bool(user_roles(request.user) & set(APP_ROLES)),
    })


# --- Апп, орчин -----------------------------------------------------------

@roles_required(*APP_ROLES)
def app_create(request):
    form = TestAppForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        app = form.save(commit=False)
        app.created_by = request.user
        app.save()
        messages.success(request, _("'%(name)s' апп бүртгэгдлээ. Одоо орчны хаягаа нэмнэ үү.") % {"name": app.name})
        return redirect("autotest:app_detail", pk=app.pk)
    return render(request, "autotest/app_form.html", {
        "form": form, "subcategories_by_category": _subcategories_by_category(),
    })


@roles_required(*VIEW_ROLES)
def app_detail(request, pk):
    app = get_object_or_404(TestApp.objects.select_related("category", "subcategory"), pk=pk)
    can_manage = bool(user_roles(request.user) & set(APP_ROLES))
    form = TestAppForm(request.POST or None, instance=app)
    if request.method == "POST":
        if not can_manage:
            messages.error(request, _("Танд энэ хуудсанд хандах эрх байхгүй."))
            return redirect("autotest:app_detail", pk=pk)
        if form.is_valid():
            form.save()
            messages.success(request, _("'%(name)s' шинэчлэгдлээ.") % {"name": app.name})
            return redirect("autotest:app_detail", pk=pk)
    return _render_app_detail(request, app, form=form)


def _render_app_detail(request, app, form=None, env_form=None, page_form=None, account_form=None, login_form=None):
    scenarios = _attach_last_runs(
        app.scenarios.select_related("page", "account").annotate(run_count=Count("runs")), "scenario"
    )
    can_manage = bool(user_roles(request.user) & set(APP_ROLES))
    form = form or TestAppForm(instance=app)
    login_form = login_form or AppLoginForm(instance=app)
    return render(request, "autotest/app_detail.html", {
        "app": app,
        "form": form,
        "login_form": login_form,
        "env_form": env_form or EnvironmentForm(prefix="env"),
        "environments": app.environments.all(),
        "page_form": page_form or PageForm(prefix="page"),
        "pages": app.pages.annotate(scenario_count=Count("scenarios")),
        "account_form": account_form or TestAccountForm(prefix="account"),
        "accounts": app.accounts.annotate(scenario_count=Count("scenarios")),
        "scenarios": scenarios,
        "subcategories_by_category": _subcategories_by_category(),
        "can_manage": can_manage,
        "can_edit": _can_edit(request.user),
    })


@roles_required(*APP_ROLES)
@require_POST
def app_delete(request, pk):
    app = get_object_or_404(TestApp, pk=pk)
    name = app.name
    app.delete()
    messages.success(request, _("'%(name)s' апп тест, үр дүнгийн хамт устгагдлаа.") % {"name": name})
    return redirect("autotest:home")


@roles_required(*APP_ROLES)
@require_POST
def env_create(request, pk):
    app = get_object_or_404(TestApp, pk=pk)
    form = EnvironmentForm(request.POST, app=app, prefix="env")
    if not form.is_valid():
        # Бичсэн утгыг хадгалж, алдааг талбарын дор харуулна.
        return _render_app_detail(request, app, env_form=form)
    env = form.save(commit=False)
    env.app = app
    env.save()
    messages.success(request, _("'%(name)s' орчин нэмэгдлээ.") % {"name": env.name})
    return redirect("autotest:app_detail", pk=pk)


@roles_required(*APP_ROLES)
@require_POST
def env_delete(request, pk, env_pk):
    env = get_object_or_404(Environment, pk=env_pk, app_id=pk)
    env.delete()
    messages.success(request, _("'%(name)s' орчин устгагдлаа.") % {"name": env.name})
    return redirect("autotest:app_detail", pk=pk)


@roles_required(*APP_ROLES)
@require_POST
def env_toggle_production(request, pk, env_pk):
    env = get_object_or_404(Environment, pk=env_pk, app_id=pk)
    env.is_production = not env.is_production
    env.save(update_fields=["is_production"])
    if env.is_production:
        messages.warning(request, _("'%(name)s' production орчин боллоо — энд тест ажиллуулах бүрт баталгаажуулалт асууна.") % {"name": env.name})
    else:
        messages.success(request, _("'%(name)s' production биш боллоо.") % {"name": env.name})
    return redirect("autotest:app_detail", pk=pk)


@roles_required(*EDIT_ROLES)
@require_POST
def page_create(request, pk):
    app = get_object_or_404(TestApp, pk=pk)
    form = PageForm(request.POST, app=app, prefix="page")
    if not form.is_valid():
        return _render_app_detail(request, app, page_form=form)
    page = form.save(commit=False)
    page.app = app
    page.save()
    messages.success(request, _("'%(name)s' хуудас нэмэгдлээ.") % {"name": page.name})
    return redirect("autotest:app_detail", pk=pk)


@roles_required(*EDIT_ROLES)
@require_POST
def page_delete(request, pk, page_pk):
    page = get_object_or_404(Page.objects.select_related("app"), pk=page_pk, app_id=pk)
    if page.scenarios.exists():
        messages.error(request, _("'%(name)s' хуудсыг сценари ашиглаж байгаа тул устгах боломжгүй.") % {"name": page.name})
    elif page.app.login_page_id == page.pk and page.app.accounts.exists():
        messages.error(request, _("'%(name)s' нь нэвтрэх хуудас тул устгах боломжгүй.") % {"name": page.name})
    else:
        page.delete()
        messages.success(request, _("'%(name)s' хуудас устгагдлаа.") % {"name": page.name})
    return redirect("autotest:app_detail", pk=pk)


@roles_required(*EDIT_ROLES)
@require_POST
def account_save(request, pk):
    app = get_object_or_404(TestApp, pk=pk)
    form = TestAccountForm(request.POST, prefix="account")
    if not form.is_valid():
        return _render_app_detail(request, app, account_form=form)
    account, created = form.save(app)
    if created:
        messages.success(request, _("'%(name)s' тестийн хэрэглэгч нэмэгдлээ.") % {"name": account.label})
    else:
        messages.success(request, _("'%(name)s' тестийн хэрэглэгч шинэчлэгдлээ.") % {"name": account.label})
    return redirect("autotest:app_detail", pk=pk)


@roles_required(*EDIT_ROLES)
@require_POST
def app_login_save(request, pk):
    app = get_object_or_404(TestApp, pk=pk)
    form = AppLoginForm(request.POST, instance=app)
    if not form.is_valid():
        return _render_app_detail(request, app, login_form=form)
    form.save()
    messages.success(request, _("Нэвтрэлт хадгалагдлаа."))
    return redirect("autotest:app_detail", pk=pk)


@roles_required(*EDIT_ROLES)
@require_POST
def account_delete(request, pk, account_pk):
    account = get_object_or_404(TestAccount, pk=account_pk, app_id=pk)
    if account.scenarios.exists():
        messages.error(request, _("'%(name)s' хэрэглэгчийг сценари ашиглаж байгаа тул устгах боломжгүй.") % {"name": account.label})
    else:
        account.delete()
        messages.success(request, _("'%(name)s' тестийн хэрэглэгч устгагдлаа.") % {"name": account.label})
    return redirect("autotest:app_detail", pk=pk)


def _login_url(app, environment, account):
    """Нэвтрэх хуудасны бүтэн хаяг; нэвтрэхгүй бол ''. Нэвтрэх хуудас сонгоогүй бол ValueError."""
    if account is None:
        return ""
    if app.login_page is None:
        raise ValueError(_("Тестийн хэрэглэгчид хэсэгт нэвтрэх хуудсаа сонгоно уу."))
    return environment.url_for(app.login_page.path)[:600]


# --- Өгөгдлийн файл -------------------------------------------------------

@roles_required(*VIEW_ROLES)
def datafile_list(request):
    files = DataFile.objects.select_related("category", "uploaded_by").annotate(run_count=Count("runs"))
    return render(request, "autotest/datafile_list.html", {"files": files, "can_edit": _can_edit(request.user)})


@roles_required(*EDIT_ROLES)
def datafile_create(request):
    form = DataFileForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        data_file = form.save(commit=False)
        data_file.uploaded_by = request.user
        data_file.save()
        messages.success(
            request,
            _("'%(name)s' файл орлоо: %(rows)s мөр, %(cols)s багана.")
            % {"name": data_file.name, "rows": data_file.row_count, "cols": len(data_file.columns)},
        )
        return redirect("autotest:datafile_detail", pk=data_file.pk)
    return render(request, "autotest/datafile_form.html", {"form": form})


@roles_required(*VIEW_ROLES)
def datafile_detail(request, pk):
    from .datafiles import DataFileError, read_rows

    data_file = get_object_or_404(DataFile.objects.select_related("category"), pk=pk)
    preview, preview_error = [], ""
    try:
        with data_file.file.open("rb") as fh:
            _cols, rows = read_rows(fh, data_file.file.name)
        preview = [(line, [row.get(c, "") for c in data_file.columns]) for line, row in rows[:PREVIEW_ROWS]]
    except (DataFileError, FileNotFoundError) as exc:
        preview_error = str(exc) or _("Файл серверээс олдсонгүй.")

    scenarios = Scenario.objects.filter(app__category=data_file.category).select_related("app")
    compatible = [(s, s.missing_columns(data_file)) for s in scenarios]
    return render(request, "autotest/datafile_detail.html", {
        "data_file": data_file,
        "preview": preview,
        "preview_error": preview_error,
        "compatible": compatible,
        "replace_form": DataFileReplaceForm(),
        "can_edit": _can_edit(request.user),
        "run_count": data_file.runs.count(),
    })


@roles_required(*EDIT_ROLES)
@require_POST
def datafile_replace(request, pk):
    """Файлыг шинэчилнэ — өмнөх ажиллуулалтууд өөрсдийн хуулбар өгөгдөлтэй тул түүх хэвээр."""
    data_file = get_object_or_404(DataFile, pk=pk)
    form = DataFileReplaceForm(request.POST, request.FILES)
    if form.is_valid():
        storage, old_name = data_file.file.storage, data_file.file.name
        data_file.file = form.cleaned_data["file"]
        data_file.columns, data_file.row_count = form.columns, form.row_count
        data_file.uploaded_by = request.user
        data_file.save()
        storage.delete(old_name)
        messages.success(request, _("Файл шинэчлэгдлээ: %(rows)s мөр.") % {"rows": data_file.row_count})
    else:
        _flash_form_errors(request, form)
    return redirect("autotest:datafile_detail", pk=pk)


@roles_required(*EDIT_ROLES)
@require_POST
def datafile_delete(request, pk):
    data_file = get_object_or_404(DataFile, pk=pk)
    name = data_file.name
    data_file.file.delete(save=False)
    data_file.delete()
    messages.success(request, _("'%(name)s' файл устгагдлаа.") % {"name": name})
    return redirect("autotest:datafile_list")


@roles_required(*VIEW_ROLES)
def datafile_download(request, pk):
    """Хадгалсан форматаас үл хамааран ?format=xlsx|csv-ээр татна."""
    from .datafiles import DataFileError, read_rows, write_table

    data_file = get_object_or_404(DataFile, pk=pk)
    fmt = exports.requested_format(request)
    filename = data_file.name.replace("/", "_").replace("\\", "_") or "data"
    try:
        if _file_format(data_file.file.name) == fmt:
            return FileResponse(data_file.file.open("rb"), as_attachment=True, filename=f"{filename}.{fmt}")
        with data_file.file.open("rb") as fh:
            columns, rows = read_rows(fh, data_file.file.name)
    except (FileNotFoundError, DataFileError):
        raise Http404(_("Файл олдсонгүй."))
    content = write_table(columns, [[row.get(c, "") for c in columns] for _line, row in rows], fmt)
    return exports.file_response(content, filename, fmt)


def _file_format(name):
    return "csv" if name.lower().endswith(".csv") else "xlsx"


def _column_roles(data_file):
    """
    Ангиллын сценариуд файлын баганыг юунд ашигладаг вэ: {багана: {"used_by": [нэр], "expected": bool,
    "secret": bool}}. Ашиглагдаж буй баганын нэрийг засах цонхонд солих/устгахыг хориглоно.
    """
    from .api import is_secret_column

    roles = {c: {"used_by": [], "expected": c == generator.EXPECTED_COLUMN, "secret": is_secret_column(c)}
             for c in data_file.columns}
    for scenario in Scenario.objects.filter(app__category_id=data_file.category_id).select_related("app"):
        for column in scenario.required_columns():
            if column in roles:
                roles[column]["used_by"].append(str(scenario))
        if scenario.expected_column in roles:
            roles[scenario.expected_column]["expected"] = True
        for column in scenario.secret_columns():
            if column in roles:
                roles[column]["secret"] = True
    return roles


@roles_required(*VIEW_ROLES)
def datafile_preview(request, pk):
    """Сценари тохируулж байх үед файлыг хуудсаа орхилгүй (цонхонд) харуулах JSON."""
    from .datafiles import ERROR_WORDS, SUCCESS_WORDS, DataFileError, read_rows

    data_file = get_object_or_404(DataFile, pk=pk)
    roles = _column_roles(data_file)
    try:
        with data_file.file.open("rb") as fh:
            _cols, rows = read_rows(fh, data_file.file.name)
    except (DataFileError, FileNotFoundError) as exc:
        return JsonResponse({"error": str(exc) or _("Файл серверээс олдсонгүй.")}, status=400)
    limit = None if request.GET.get("all") else PREVIEW_MODAL_ROWS  # засахад бүх мөр хэрэгтэй
    return JsonResponse({
        "name": data_file.name,
        "columns": data_file.columns,
        "rows": [[line, [row.get(c, "") for c in data_file.columns]] for line, row in rows[:limit]],
        "total": len(rows),
        "roles": roles,
        "outcome_words": sorted(SUCCESS_WORDS | ERROR_WORDS),
        "download_url": reverse("autotest:datafile_download", args=[data_file.pk]),
    })


MAX_CELL_LENGTH = 2000


@roles_required(*EDIT_ROLES)
@require_POST
def datafile_save_rows(request, pk):
    """
    Хүснэгтээр зассан баганууд, мөрүүдийг хадгална. Сценарид ашиглагдаж буй багана нэрээрээ
    үлдэх ёстой (сценариудын холбоос эвдрэхгүй); бусад баганыг нэмж, солих, устгаж болно.
    """
    from .datafiles import max_rows, update_xlsx, write_table

    data_file = get_object_or_404(DataFile, pk=pk)
    try:
        payload = json.loads(request.body or b"{}")
        rows, columns = payload.get("rows"), payload.get("columns", data_file.columns)
    except (ValueError, AttributeError):
        rows = columns = None
    invalid = JsonResponse({"error": _("Өгөгдөл буруу байна. Хуудсаа refresh хийгээд дахин оролдоно уу.")}, status=400)
    if not isinstance(columns, list) or not all(isinstance(c, str) for c in columns):
        return invalid
    columns = [c.strip()[:150] for c in columns]
    if not columns or "" in columns:
        return JsonResponse({"error": _("Баганын нэр хоосон байж болохгүй.")}, status=400)
    duplicates = sorted({c for c in columns if columns.count(c) > 1})
    if duplicates:
        return JsonResponse({"error": _("Давхардсан баганын нэр: %(cols)s") % {"cols": ", ".join(duplicates)}}, status=400)
    removed = [c for c, role in _column_roles(data_file).items() if role["used_by"] and c not in columns]
    if removed:
        return JsonResponse({"error": _("Сценарид ашиглагдаж буй баганыг устгах, нэрийг солих боломжгүй: %(cols)s")
                             % {"cols": ", ".join(removed)}}, status=400)
    width = len(columns)
    if not isinstance(rows, list) or not all(isinstance(r, list) and len(r) == width for r in rows):
        return invalid
    rows = [[str(v if v is not None else "")[:MAX_CELL_LENGTH] for v in r] for r in rows]
    rows = [r for r in rows if any(v.strip() for v in r)]  # хоосон мөрийг хасна
    if not rows:
        return JsonResponse({"error": _("Дор хаяж нэг мөр өгөгдөл байх ёстой.")}, status=400)
    if len(rows) > max_rows():
        return JsonResponse({"error": _("Хамгийн ихдээ %(max)s мөр байна.") % {"max": max_rows()}}, status=400)

    storage, old_name = data_file.file.storage, data_file.file.name
    base, fmt = os.path.splitext(os.path.basename(old_name))[0], _file_format(old_name)  # форматаа хадгална
    content = None
    if fmt == "xlsx":  # бусад sheet, өнгө, баганын өргөнийг хадгална
        try:
            with storage.open(old_name, "rb") as fh:
                content = update_xlsx(fh, columns, rows)
        except Exception:
            content = None  # эвдэрсэн / олдоогүй бол шинээр бичнэ
    if content is None:
        content = write_table(columns, rows, fmt)
    data_file.file.save(f"{base}.{fmt}", ContentFile(content), save=False)
    data_file.columns, data_file.row_count = columns, len(rows)
    data_file.save()
    if old_name != data_file.file.name:
        storage.delete(old_name)
    return JsonResponse({"rows": data_file.row_count, "name": data_file.name, "columns": data_file.columns})


@roles_required(*EDIT_ROLES)
@require_POST
def datafile_mapping(request, pk):
    """Сценарийн талбаруудыг сонгосон файлын баганатай дахин тааруулна (файл солиход)."""
    data_file = get_object_or_404(DataFile, pk=pk)
    try:
        fields = json.loads(request.POST.get("fields_json") or "[]")
    except ValueError:
        fields = []
    fields = [f for f in fields if isinstance(f, dict)][:100] if isinstance(fields, list) else []
    return JsonResponse({"columns": data_file.columns, "fields": suggest_mapping(fields, data_file.columns)})


@roles_required(*VIEW_ROLES)
def template_download(request):
    return exports.template_response(exports.requested_format(request))


# --- Сценари --------------------------------------------------------------

def _scenario_form(app, kind, *args, **kwargs):
    form_class = ApiScenarioForm if kind == Scenario.Kind.API else ScenarioForm
    return form_class(*args, app=app, **kwargs)


def _render_scenario_form(request, app, form, scenario=None):
    template = "autotest/api_scenario_form.html" if isinstance(form, ApiScenarioForm) else "autotest/scenario_form.html"
    return render(request, template, _scenario_form_context(app, form, scenario))


def _scenario_form_context(app, form, scenario=None):
    data_files = DataFile.objects.filter(category=app.category)
    return {
        "app": app,
        "form": form,
        "scenario": scenario,
        "environments": app.environments.all(),
        "pages": app.pages.all(),
        "data_files": data_files,
        "data_files_meta": [
            {"id": f.pk, "name": f.name, "columns": f.columns, "rows": f.row_count} for f in data_files
        ],
        "known_columns": sorted({c for cols in DataFile.objects.filter(category=app.category)
                                 .values_list("columns", flat=True) for c in cols}),
    }


@roles_required(*EDIT_ROLES)
def scenario_create(request, pk):
    app = get_object_or_404(TestApp.objects.select_related("category"), pk=pk)
    kind = Scenario.Kind.API if request.GET.get("kind") == Scenario.Kind.API else Scenario.Kind.WEB
    if kind == Scenario.Kind.WEB and not app.pages.exists():
        messages.error(request, _("Эхлээд апп-даа шалгах хуудсаа нэмнэ үү."))
        return redirect("autotest:app_detail", pk=pk)
    form = _scenario_form(app, kind, request.POST or None)
    if request.method == "POST" and form.is_valid():
        scenario = form.save(commit=False)
        scenario.app = app
        scenario.created_by = request.user
        scenario.save()
        messages.success(request, _("'%(name)s' сценари хадгалагдлаа. Одоо ажиллуулж болно.") % {"name": scenario.name})
        return redirect("autotest:scenario_detail", pk=scenario.pk)
    return _render_scenario_form(request, app, form)


@roles_required(*EDIT_ROLES)
def scenario_edit(request, pk):
    scenario = get_object_or_404(Scenario.objects.select_related("app__category"), pk=pk)
    form = _scenario_form(scenario.app, scenario.kind, request.POST or None, instance=scenario)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("'%(name)s' сценари шинэчлэгдлээ.") % {"name": scenario.name})
        return redirect("autotest:scenario_detail", pk=pk)
    return _render_scenario_form(request, scenario.app, form, scenario)


@roles_required(*VIEW_ROLES)
def scenario_workflow(request, pk):
    scenario = get_object_or_404(Scenario.objects.select_related("app", "page", "account"), pk=pk)
    return render(request, "autotest/_workflow.html", {
        "scenario": scenario, **workflow.context(scenario, request.GET.get("file"), request.GET.get("row")),
    })


@roles_required(*VIEW_ROLES)
def scenario_detail(request, pk):
    scenario = get_object_or_404(Scenario.objects.select_related("app__category", "page", "account"), pk=pk)
    runs = scenario.runs.select_related("started_by")[:30]
    last_run = runs[0] if runs else None
    # Ажиллуулах формыг сүүлд ашигласан файл, орчноор бөглөнө.
    last_data_run = next((r for r in runs if r.kind == TestRun.Kind.DATA), None)
    initial = {"data_file": last_data_run.data_file_id, "environment": last_data_run.environment_id} if last_data_run else {}
    # Сценарийн хэрэглэгч формыг бөглөдөг тул түүнд хуудас нээлттэй байх ёстой — анхны сонголт.
    rules = scenario.access_rules or ({str(scenario.account_id): "open"} if scenario.account_id else {})
    access_rows = [("anon", _("Нэвтрэхгүй"), "", rules.get("anon", ""))] + [
        (str(a.pk), a.label, a.username, rules.get(str(a.pk), "")) for a in scenario.app.accounts.all()
    ]
    return render(request, "autotest/scenario_detail.html", {
        "scenario": scenario,
        "run_form": RunForm(scenario=scenario, initial=initial),
        "last_run": last_run,
        "runs": runs,
        "used_fields": [f for f in scenario.fields if f.get("source") != "skip"],
        "access_rows": access_rows,
        "environments": scenario.app.environments.all(),
        "access_environment": last_run.environment_id if last_run else None,
        "production_envs": {e.pk: e.name for e in scenario.app.environments.filter(is_production=True)},
        **workflow.context(scenario, last_data_run.data_file_id if last_data_run else None),
        "can_edit": _can_edit(request.user),
    })


ACCESS_EXPECTS = ("open", "denied")


@roles_required(*EDIT_ROLES)
@require_POST
def access_run_create(request, pk):
    """Сонгосон хэрэглэгч бүрээр хуудас нээлттэй/хаалттай эсэхийг шалгах ажиллуулалт."""
    scenario = get_object_or_404(Scenario.objects.select_related("app__login_page"), pk=pk)
    if scenario.is_api:
        raise Http404
    environment = scenario.app.environments.filter(pk=request.POST.get("environment") or None).first()
    if environment is None:
        messages.error(request, _("Орчноо сонгоно уу."))
        return redirect("autotest:scenario_detail", pk=pk)
    saved = {}
    for key in ["anon"] + [str(a) for a in scenario.app.accounts.values_list("pk", flat=True)]:
        value = request.POST.get(f"expect_{key}", "")
        if value in ACCESS_EXPECTS:
            saved[key] = value
    if not saved:
        messages.error(request, _("Дор хаяж нэг хэрэглэгчид нээлттэй эсвэл хаалттай гэж сонгоно уу."))
        return redirect("autotest:scenario_detail", pk=pk)
    scenario.access_rules = saved
    scenario.save(update_fields=["access_rules", "updated_at"])
    try:
        run = _queue_access_run(scenario, environment, request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("autotest:scenario_detail", pk=pk)
    return redirect("autotest:run_detail", pk=run.pk)


def _queue_access_run(scenario, environment, user):
    accounts = scenario.app.accounts.in_bulk()
    rules = []
    for key, expect in scenario.access_rules.items():
        if key == "anon":
            rules.append({"account": None, "label": _("Нэвтрэхгүй"), "expect": expect})
        elif int(key) in accounts:
            rules.append({"account": int(key), "label": accounts[int(key)].label, "expect": expect})
    if not rules:
        raise ValueError(_("Дор хаяж нэг хэрэглэгчид нээлттэй эсвэл хаалттай гэж сонгоно уу."))
    needs_login = any(r["account"] for r in rules)
    login_page = scenario.app.login_page
    if needs_login and login_page is None:
        raise ValueError(_("Тестийн хэрэглэгчид хэсэгт нэвтрэх хуудсаа сонгоно уу."))
    return TestRun.objects.create(
        scenario=scenario,
        kind=TestRun.Kind.ACCESS,
        access_rules=rules,
        environment=environment,
        data_file_name=_("Эрх шалгах"),
        environment_name=environment.name,
        target_url=environment.url_for(scenario.page.path)[:600],
        # Нэвтрэхгүй хэрэглэгчийг нэвтрэх хуудас руу шилжүүлснийг таних ч хэрэгтэй.
        login_url=environment.url_for(login_page.path)[:600] if login_page else "",
        total=len(rules),
        started_by=user,
    )


@roles_required(*EDIT_ROLES)
@require_POST
def scenario_delete(request, pk):
    scenario = get_object_or_404(Scenario, pk=pk)
    app_pk, name = scenario.app_id, scenario.name
    scenario.delete()
    messages.success(request, _("'%(name)s' сценари устгагдлаа.") % {"name": name})
    return redirect("autotest:app_detail", pk=app_pk)


# --- Хуудас шалгах (JSON) ------------------------------------------------

@roles_required(*EDIT_ROLES)
@require_POST
def scan_create(request, pk):
    app = get_object_or_404(TestApp, pk=pk)
    env = app.environments.filter(pk=request.POST.get("environment")).first()
    if env is None:
        return JsonResponse({"error": _("Орчноо сонгоно уу.")}, status=400)
    page = app.pages.filter(pk=request.POST.get("page") or None).first()
    if page is None:
        return JsonResponse({"error": _("Хуудсаа сонгоно уу.")}, status=400)
    account = app.accounts.filter(pk=request.POST.get("account") or None).first()
    try:
        login_url = _login_url(app, env, account)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    scan = PageScan.objects.create(
        url=env.url_for(page.path)[:600], account=account, login_url=login_url, requested_by=request.user,
    )
    return JsonResponse({"id": scan.pk, "url": scan.url})


@roles_required(*EDIT_ROLES)
def scan_status(request, pk):
    scan = get_object_or_404(PageScan, pk=pk, requested_by=request.user)
    data = {"status": scan.status, "error": scan.error_message, "url": scan.url}
    if scan.status == PageScan.Status.DONE:
        data_file = DataFile.objects.filter(pk=request.GET.get("data_file") or None).first()
        columns = data_file.columns if data_file else []
        data.update(
            title=scan.result.get("title", ""),
            fields=suggest_mapping(scan.result.get("fields", []), columns),
            buttons=scan.result.get("buttons", []),
            generate=generator.generate_form(scan.result.get("fields", [])),
        )
    return JsonResponse(data)


@roles_required(*EDIT_ROLES)
@require_POST
def scan_generate(request, pk, scan_pk):
    """
    Шалгасан хуудасны талбаруудаас тестийн өгөгдлийн файл үүсгэж, багана ↔ талбарын холбоосыг буцаана.
    values — {selector: QA-н оруулсан зөв утга}, login — нэвтрэх форм эсэх.
    """
    app = get_object_or_404(TestApp, pk=pk)
    scan = get_object_or_404(PageScan, pk=scan_pk, requested_by=request.user, status=PageScan.Status.DONE)
    try:
        values = json.loads(request.POST.get("values") or "{}")
    except ValueError:
        values = None
    if not isinstance(values, dict):
        return JsonResponse({"error": _("Утгууд буруу байна.")}, status=400)
    login = request.POST["login"] == "1" if "login" in request.POST else None
    try:
        columns, rows, mapping = generator.generate(scan.result.get("fields", []), values, login)
    except generator.GenerateError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    if not mapping:
        return JsonResponse({"error": _("Өгөгдөл үүсгэх талбар олдсонгүй.")}, status=400)
    base = (request.POST.get("name") or "").strip() or urlsplit(scan.url).path or scan.url
    name = _("%(name)s — автомат өгөгдөл") % {"name": base[:100]}
    data_file = DataFile(category=app.category, name=name[:150], columns=columns, row_count=len(rows),
                         uploaded_by=request.user)
    data_file.file.save("generated.xlsx", ContentFile(generator.to_xlsx(columns, rows)), save=True)
    return JsonResponse({
        "id": data_file.pk,
        "name": data_file.name,
        "columns": columns,
        "rows": len(rows),
        "mapping": mapping,
        "expected_column": generator.EXPECTED_COLUMN,
        "url": reverse("autotest:datafile_detail", args=[data_file.pk]),
    })


# --- Ажиллуулалт ----------------------------------------------------------

@roles_required(*EDIT_ROLES)
@require_POST
def run_create(request, pk):
    scenario = get_object_or_404(Scenario.objects.select_related("app"), pk=pk)
    form = RunForm(request.POST, scenario=scenario)
    if not form.is_valid():
        _flash_form_errors(request, form)
        return redirect("autotest:scenario_detail", pk=pk)
    try:
        run = _queue_run(scenario, form.cleaned_data["data_file"], form.cleaned_data["environment"], request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("autotest:scenario_detail", pk=pk)
    return redirect("autotest:run_detail", pk=run.pk)


def _queue_run(scenario, data_file, environment, user):
    account = scenario.account
    if scenario.is_api:
        target_url = environment.url_for(scenario.api_path)
        if account and not scenario.app.api_login_path:
            raise ValueError(_("Тестийн хэрэглэгчид хэсэгт API нэвтрэх замаа бичнэ үү."))
        login_url = environment.url_for(scenario.app.api_login_path) if account else ""
    else:
        target_url = environment.url_for(scenario.page.path)
        login_url = _login_url(scenario.app, environment, account)
    return TestRun.objects.create(
        scenario=scenario,
        data_file=data_file,
        environment=environment,
        data_file_name=data_file.name,
        environment_name=environment.name,
        target_url=target_url[:600],
        account=account,
        account_label=account.label if account else "",
        login_url=login_url[:600],
        total=data_file.row_count,
        started_by=user,
    )


def _run_results(request, run):
    results = run.results.select_related("ticket")
    show = request.GET.get("show", "")
    if show == "failed":
        results = results.filter(verdict__in=[RunResult.Verdict.FAIL, RunResult.Verdict.ERROR])
    elif show == "review":
        results = results.filter(verdict=RunResult.Verdict.RECORDED)
    return results, show


@roles_required(*VIEW_ROLES)
def run_detail(request, pk):
    run = get_object_or_404(TestRun.objects.select_related("scenario__app", "started_by"), pk=pk)
    results, show = _run_results(request, run)
    return render(request, "autotest/run_detail.html", {
        "run": run,
        "results": results,
        "show": show,
        "can_edit": _can_edit(request.user),
    })


@roles_required(*VIEW_ROLES)
def run_status(request, pk):
    """Ажиллаж буй run-ийн явцыг хуудас 2 секунд тутам шинэчлэхэд ашиглана."""
    run = get_object_or_404(TestRun, pk=pk)
    results, show = _run_results(request, run)
    return JsonResponse({
        "status": run.status,
        "active": run.is_active,
        "done": run.done_count,
        "total": run.total,
        "passed": run.passed,
        "failed": run.failed,
        "errored": run.errored,
        "recorded": run.recorded,
        "html": render_to_string(
            "autotest/_results_table.html",
            {"run": run, "results": results, "can_edit": _can_edit(request.user)},
            request=request,
        ),
    })


@roles_required(*EDIT_ROLES)
@require_POST
def run_cancel(request, pk):
    updated = TestRun.objects.filter(pk=pk, status__in=TestRun.ACTIVE_STATUSES).update(
        status=TestRun.Status.CANCELLED
    )
    if updated:
        messages.info(request, _("Ажиллуулалтыг цуцаллаа."))
    return redirect("autotest:run_detail", pk=pk)


@roles_required(*EDIT_ROLES)
@require_POST
def run_rerun(request, pk):
    old = get_object_or_404(TestRun.objects.select_related("scenario"), pk=pk)
    if old.kind == TestRun.Kind.ACCESS:
        if old.environment is None:
            messages.error(request, _("Өмнөх файл эсвэл орчин устгагдсан тул сценариас шинээр ажиллуулна уу."))
            return redirect("autotest:scenario_detail", pk=old.scenario_id)
        try:
            run = _queue_access_run(old.scenario, old.environment, request.user)
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect("autotest:run_detail", pk=pk)
        return redirect("autotest:run_detail", pk=run.pk)
    if old.data_file is None or old.environment is None:
        messages.error(request, _("Өмнөх файл эсвэл орчин устгагдсан тул сценариас шинээр ажиллуулна уу."))
        return redirect("autotest:scenario_detail", pk=old.scenario_id)
    missing = old.scenario.missing_columns(old.data_file)
    if missing:
        messages.error(request, _("Энэ файлд сценарид хэрэгтэй багана алга: %(cols)s") % {"cols": ", ".join(missing)})
        return redirect("autotest:run_detail", pk=pk)
    try:
        run = _queue_run(old.scenario, old.data_file, old.environment, request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("autotest:run_detail", pk=pk)
    return redirect("autotest:run_detail", pk=run.pk)


@roles_required(*VIEW_ROLES)
def run_export(request, pk):
    run = get_object_or_404(TestRun, pk=pk)
    return exports.run_response(run, list(run.results.all()), exports.requested_format(request))


@roles_required(*VIEW_ROLES)
def result_screenshot(request, pk):
    result = get_object_or_404(RunResult, pk=pk)
    if not result.screenshot:
        raise Http404
    try:
        handle = result.screenshot.open("rb")
    except FileNotFoundError:
        raise Http404(_("Файл олдсонгүй."))
    return FileResponse(handle, content_type="image/png")


# --- Bug ticket -----------------------------------------------------------

def _bug_description(run, results):
    lines = [
        _("Автомат тестээр илэрсэн алдаа."),
        _("Сценари: %(s)s") % {"s": run.scenario},
        _("Орчин: %(env)s — %(url)s") % {"env": run.environment_name, "url": run.target_url},
        _("Ажиллуулалт: #%(id)s — %(url)s")
        % {"id": run.pk, "url": settings.SITE_URL.rstrip("/") + reverse("autotest:run_detail", args=[run.pk])},
        "",
    ]
    for result in results:
        title = _("Мөр %(n)s") % {"n": result.row_number}
        if result.description:
            title += f" — {result.description}"
        expected = result.get_expected_outcome_display() if result.expected_outcome else ""
        if result.expected_message:
            expected = f"{expected} ({result.expected_message})".strip()
        actual = result.get_actual_outcome_display() if result.actual_outcome else result.get_verdict_display()
        if result.actual_message:
            actual += f" — {result.actual_message}"
        inputs = ", ".join(f"{k}={v}" for k, v in result.input_data.items())
        lines += [
            title,
            "  " + _("Оролт: %(v)s") % {"v": inputs},
            "  " + _("Хүлээгдэж байсан: %(v)s") % {"v": expected or "—"},
            "  " + _("Бодит үр дүн: %(v)s") % {"v": actual},
        ]
        if result.response_detail:  # API: хөгжүүлэгч шууд давтаж ажиллуулах curl + хариу
            lines += ["", result.response_detail[:4000]]
        lines.append("")
    return "\n".join(lines).strip()


@roles_required(*EDIT_ROLES)
def bug_ticket(request, pk):
    """Унасан мөрүүдээс ticket үүсгэнэ — ticket-ийн ердийн маягт урьдчилж бөглөгдсөн байна."""
    run = get_object_or_404(TestRun.objects.select_related("scenario__app"), pk=pk)
    ids = [int(i) for i in request.GET.get("ids", "").split(",") if i.strip().isdigit()]
    results = list(run.results.filter(pk__in=ids, verdict__in=[RunResult.Verdict.FAIL, RunResult.Verdict.ERROR]))
    if not results:
        messages.error(request, _("Ticket үүсгэх унасан мөрөө сонгоно уу."))
        return redirect("autotest:run_detail", pk=pk)

    if request.method == "POST":
        form = TicketForm(request.POST, request.FILES)
        if form.is_valid():
            ticket = form.save(commit=False)
            ticket.reported_by = request.user
            ticket._changed_by = request.user
            ticket.save()
            if form.cleaned_data.get("attachment"):
                Attachment.objects.create(ticket=ticket, file=form.cleaned_data["attachment"], uploaded_by=request.user)
            for result in results:
                if result.screenshot:
                    with result.screenshot.open("rb") as fh:
                        attachment = Attachment(ticket=ticket, uploaded_by=request.user)
                        attachment.file.save(f"autotest_row{result.row_number}.png", ContentFile(fh.read()))
            RunResult.objects.filter(pk__in=[r.pk for r in results]).update(ticket=ticket)
            notify_ticket_routed(ticket)
            messages.success(request, _("Ticket %(code)s амжилттай үүслээ.") % {"code": ticket.code})
            return redirect("tickets:ticket_detail", pk=ticket.pk)
    else:
        first = results[0]
        title = _("[Автомат тест] %(scenario)s: %(case)s") % {
            "scenario": run.scenario.name,
            "case": first.description or _("мөр %(n)s") % {"n": first.row_number},
        }
        if len(results) > 1:
            title += _(" (+%(n)s мөр)") % {"n": len(results) - 1}
        form = TicketForm(initial={
            "title": title[:255],
            "ticket_type": Ticket.TicketType.BUG,
            # Апп-ын ангиллаар ticket зөв баг руу чиглэнэ; төслийг QA маягт дээр сонгоно.
            "category": run.scenario.app.category_id,
            "subcategory": run.scenario.app.subcategory_id,
            "description": _bug_description(run, results),
        })
    return render(request, "tickets/ticket_form.html", {
        "form": form,
        "modules_by_project": _modules_by_project(),
        "subcategories_by_category": _subcategories_by_category(),
        "autotest_run": run,
        "autotest_results": results,
    })
