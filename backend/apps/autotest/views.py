import os

from django.conf import settings
from django.contrib import messages
from django.core.files.base import ContentFile
from django.db.models import Count
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
from apps.tickets.permissions import ROLE_ADMIN, ROLE_DEV, ROLE_PM, ROLE_QA, user_roles
from apps.tickets.views import _modules_by_project, _subcategories_by_category

from . import exports
from .datafiles import suggest_mapping
from .forms import (
    DataFileForm, DataFileReplaceForm, EnvironmentForm, RunForm, ScenarioForm, TestAppForm,
)
from .models import DataFile, Environment, PageScan, RunResult, Scenario, TestApp, TestRun

VIEW_ROLES = (ROLE_ADMIN, ROLE_PM, ROLE_QA, ROLE_DEV)
EDIT_ROLES = (ROLE_ADMIN, ROLE_PM, ROLE_QA)
APP_ROLES = (ROLE_ADMIN, ROLE_PM, ROLE_QA)
PREVIEW_ROWS = 10


def _can_edit(user):
    return bool(user_roles(user) & set(EDIT_ROLES))


def _flash_form_errors(request, form):
    for errors in form.errors.values():
        for error in errors:
            messages.error(request, error)


# --- Нүүр ---------------------------------------------------------------

@roles_required(*VIEW_ROLES)
def home(request):
    apps = TestApp.objects.select_related("project").annotate(
        scenario_count=Count("scenarios", distinct=True),
        env_count=Count("environments", distinct=True),
    )
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
    return render(request, "autotest/app_form.html", {"form": form})


@roles_required(*VIEW_ROLES)
def app_detail(request, pk):
    app = get_object_or_404(TestApp.objects.select_related("project"), pk=pk)
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
    scenarios = app.scenarios.annotate(run_count=Count("runs"))
    return render(request, "autotest/app_detail.html", {
        "app": app,
        "form": form,
        "env_form": EnvironmentForm(),
        "environments": app.environments.all(),
        "scenarios": scenarios,
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
    form = EnvironmentForm(request.POST, app=app)
    if form.is_valid():
        env = form.save(commit=False)
        env.app = app
        env.save()
        messages.success(request, _("'%(name)s' орчин нэмэгдлээ.") % {"name": env.name})
    else:
        _flash_form_errors(request, form)
    return redirect("autotest:app_detail", pk=pk)


@roles_required(*APP_ROLES)
@require_POST
def env_delete(request, pk, env_pk):
    env = get_object_or_404(Environment, pk=env_pk, app_id=pk)
    env.delete()
    messages.success(request, _("'%(name)s' орчин устгагдлаа.") % {"name": env.name})
    return redirect("autotest:app_detail", pk=pk)


# --- Өгөгдлийн файл -------------------------------------------------------

@roles_required(*VIEW_ROLES)
def datafile_list(request):
    files = DataFile.objects.select_related("project", "uploaded_by").annotate(run_count=Count("runs"))
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

    data_file = get_object_or_404(DataFile.objects.select_related("project"), pk=pk)
    preview, preview_error = [], ""
    try:
        with data_file.file.open("rb") as fh:
            _cols, rows = read_rows(fh, data_file.file.name)
        preview = [(line, [row.get(c, "") for c in data_file.columns]) for line, row in rows[:PREVIEW_ROWS]]
    except (DataFileError, FileNotFoundError) as exc:
        preview_error = str(exc) or _("Файл серверээс олдсонгүй.")

    scenarios = Scenario.objects.filter(app__project=data_file.project).select_related("app")
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
    data_file = get_object_or_404(DataFile, pk=pk)
    try:
        handle = data_file.file.open("rb")
    except FileNotFoundError:
        raise Http404(_("Файл олдсонгүй."))
    return FileResponse(handle, as_attachment=True, filename=os.path.basename(data_file.file.name))


@roles_required(*VIEW_ROLES)
def template_download(request):
    return exports.template_response()


# --- Сценари --------------------------------------------------------------

def _scenario_form_context(app, form, scenario=None):
    return {
        "app": app,
        "form": form,
        "scenario": scenario,
        "environments": app.environments.all(),
        "data_files": DataFile.objects.filter(project=app.project),
        "known_columns": sorted({c for cols in DataFile.objects.filter(project=app.project)
                                 .values_list("columns", flat=True) for c in cols}),
    }


@roles_required(*EDIT_ROLES)
def scenario_create(request, pk):
    app = get_object_or_404(TestApp.objects.select_related("project"), pk=pk)
    form = ScenarioForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        scenario = form.save(commit=False)
        scenario.app = app
        scenario.created_by = request.user
        scenario.save()
        messages.success(request, _("'%(name)s' сценари хадгалагдлаа. Одоо ажиллуулж болно.") % {"name": scenario.name})
        return redirect("autotest:scenario_detail", pk=scenario.pk)
    return render(request, "autotest/scenario_form.html", _scenario_form_context(app, form))


@roles_required(*EDIT_ROLES)
def scenario_edit(request, pk):
    scenario = get_object_or_404(Scenario.objects.select_related("app__project"), pk=pk)
    form = ScenarioForm(request.POST or None, instance=scenario)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, _("'%(name)s' сценари шинэчлэгдлээ.") % {"name": scenario.name})
        return redirect("autotest:scenario_detail", pk=pk)
    return render(request, "autotest/scenario_form.html", _scenario_form_context(scenario.app, form, scenario))


@roles_required(*VIEW_ROLES)
def scenario_detail(request, pk):
    scenario = get_object_or_404(Scenario.objects.select_related("app__project"), pk=pk)
    return render(request, "autotest/scenario_detail.html", {
        "scenario": scenario,
        "run_form": RunForm(scenario=scenario),
        "runs": scenario.runs.select_related("started_by")[:30],
        "used_fields": [f for f in scenario.fields if f.get("source") != "skip"],
        "can_edit": _can_edit(request.user),
    })


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
    path = request.POST.get("page_path", "").strip()
    if env is None or not path:
        return JsonResponse({"error": _("Орчин болон хуудасны замыг оруулна уу.")}, status=400)
    scan = PageScan.objects.create(url=env.url_for(path)[:600], requested_by=request.user)
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
        )
    return JsonResponse(data)


# --- Ажиллуулалт ----------------------------------------------------------

@roles_required(*EDIT_ROLES)
@require_POST
def run_create(request, pk):
    scenario = get_object_or_404(Scenario.objects.select_related("app"), pk=pk)
    form = RunForm(request.POST, scenario=scenario)
    if not form.is_valid():
        _flash_form_errors(request, form)
        return redirect("autotest:scenario_detail", pk=pk)
    run = _queue_run(scenario, form.cleaned_data["data_file"], form.cleaned_data["environment"], request.user)
    return redirect("autotest:run_detail", pk=run.pk)


def _queue_run(scenario, data_file, environment, user):
    return TestRun.objects.create(
        scenario=scenario,
        data_file=data_file,
        environment=environment,
        data_file_name=data_file.name,
        environment_name=environment.name,
        target_url=environment.url_for(scenario.page_path)[:600],
        total=data_file.row_count,
        started_by=user,
    )


def _run_results(request, run):
    results = run.results.select_related("ticket")
    show = request.GET.get("show", "")
    if show == "failed":
        results = results.filter(verdict__in=[RunResult.Verdict.FAIL, RunResult.Verdict.ERROR])
    return results, show


@roles_required(*VIEW_ROLES)
def run_detail(request, pk):
    run = get_object_or_404(TestRun.objects.select_related("scenario__app__project", "started_by"), pk=pk)
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
    if old.data_file is None or old.environment is None:
        messages.error(request, _("Өмнөх файл эсвэл орчин устгагдсан тул сценариас шинээр ажиллуулна уу."))
        return redirect("autotest:scenario_detail", pk=old.scenario_id)
    missing = old.scenario.missing_columns(old.data_file)
    if missing:
        messages.error(request, _("Энэ файлд сценарид хэрэгтэй багана алга: %(cols)s") % {"cols": ", ".join(missing)})
        return redirect("autotest:run_detail", pk=pk)
    run = _queue_run(old.scenario, old.data_file, old.environment, request.user)
    return redirect("autotest:run_detail", pk=run.pk)


@roles_required(*VIEW_ROLES)
def run_export(request, pk):
    run = get_object_or_404(TestRun, pk=pk)
    return exports.run_response(run, list(run.results.all()))


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
            "",
        ]
    return "\n".join(lines).strip()


@roles_required(*EDIT_ROLES)
def bug_ticket(request, pk):
    """Унасан мөрүүдээс ticket үүсгэнэ — ticket-ийн ердийн маягт урьдчилж бөглөгдсөн байна."""
    run = get_object_or_404(TestRun.objects.select_related("scenario__app__project"), pk=pk)
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
            "project": run.scenario.app.project_id,
            "description": _bug_description(run, results),
        })
    return render(request, "tickets/ticket_form.html", {
        "form": form,
        "modules_by_project": _modules_by_project(),
        "subcategories_by_category": _subcategories_by_category(),
        "autotest_run": run,
        "autotest_results": results,
    })
