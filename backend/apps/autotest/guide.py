"""
Autotest-ийн хуудас бүрийн "Workflow" самбар: тухайн хуудсан дээр юу хийхийг зураг маягаар (дугаартай алхам,
богино нэр, бодит жишээ) харуулна. Апп, сценари г.м. бодит объектоос жишээгээ авдаг тул шинэ сценари үүсгэхэд
workflow нь өөрөө үүснэ.
"""
from django.utils.translation import gettext as _


def _s(icon, label, example="", current=False, optional=False, key=""):
    return {"icon": icon, "label": label, "example": example, "current": current, "optional": optional, "key": key}


def overview(app=None, current=()):
    """Бүх процесс: апп бүртгэхээс bug ticket хүртэл."""
    env = app.environments.first() if app else None
    pages = list(app.pages.all()[:2]) if app else []
    account = app.accounts.first() if app else None
    return {
        "title": _("Автомат тест"),
        "steps": [
            _s("bi-app-indicator", _("Апп бүртгэх"), app.name if app else "TMS", "app" in current),
            _s("bi-hdd-network", _("Орчин нэмэх"), env.base_url if env else "http://web:8000", "env" in current),
            _s("bi-file-earmark", _("Хуудас нэмэх"), ", ".join(p.path for p in pages) or "/accounts/login/", "page" in current),
            _s("bi-person-badge", _("Тестийн хэрэглэгч"), f"{account.label} · {account.username}" if account else "QA · qa_test",
               "account" in current, optional=True),
            _s("bi-file-earmark-spreadsheet", _("Өгөгдлийн файл"), "Excel / CSV", "file" in current),
            _s("bi-ui-checks", _("Сценари үүсгэх"), _("Веб форм / API"), "scenario" in current),
            _s("bi-play-fill", _("Ажиллуулах"), "", "run" in current),
            _s("bi-check2-circle", _("Үр дүн"), "✅ ❌", "result" in current),
            _s("bi-bug", _("Bug ticket"), "", "bug" in current),
        ],
    }


def scenario_form(app, page=None):
    """Веб сценари үүсгэх: key-тэй алхмуудыг scenario_form-ын JS сонголт, scan-ы үр дүнгээр шинэчилнэ."""
    return {
        "title": _("Шинэ сценари"),
        "steps": [
            _s("bi-file-earmark", _("Хуудас сонгох"), f"{page.name} — {page.path}" if page else "", True, key="page"),
            _s("bi-search", _("Хуудсыг шалгах"), "", key="fields"),
            _s("bi-arrow-left-right", _("Талбар ↔ багана"), _("Имэйл ← email")),
            _s("bi-magic", _("Тест өгөгдөл үүсгэх"), "", key="rows"),
            _s("bi-flag", _("Хүлээгдэх үр дүн"), _("амжилттай / алдаа")),
            _s("bi-save", _("Хадгалах"), ""),
        ],
    }


def api_scenario_form(app):
    return {
        "title": _("Шинэ API сценари"),
        "steps": [
            _s("bi-signpost", _("Method + зам"), "POST /api/users", True),
            _s("bi-braces", _("Body"), '{"email": "{{email}}"}'),
            _s("bi-key", _("Хэн болж шалгах"), "QA → token", optional=True),
            _s("bi-flag", _("Хүлээгдэх үр дүн"), "201 · 400: …"),
            _s("bi-save", _("Хадгалах"), ""),
        ],
    }


def scenario_detail(scenario, last_run=None):
    target = f"{scenario.api_method} {scenario.api_path}" if scenario.is_api else (scenario.page.path if scenario.page else "")
    picked = " · ".join(filter(None, [last_run.data_file_name, last_run.environment_name])) if last_run else ""
    steps = []
    if scenario.account_id:
        steps.append(_s("bi-key", _("Нэвтрэх"), f"{scenario.account.label} · {scenario.account.username}"))
    steps += [
        _s("bi-sliders", _("Файл + орчин сонгох"), picked, True),
        _s("bi-play-fill", _("Ажиллуулах"), target, True),
        _s("bi-list-ol", _("Тестийн алхмууд"), _("мөр бүр"), key="steps"),
        _s("bi-check2-circle", _("Үр дүн"), f"{last_run.pass_rate}%" if last_run and last_run.pass_rate is not None else "✅ ❌"),
        _s("bi-bug", _("Bug ticket"), _("унасан мөрөөс")),
    ]
    if not scenario.is_api:
        steps.append(_s("bi-shield-lock", _("Эрх шалгах"), _("хэн нээж болох"), optional=True))
    return {"title": scenario.name, "steps": steps}


def run_detail(run):
    return {
        "title": f"{run.scenario.name} #{run.pk}",
        "steps": [
            _s("bi-hourglass-split", _("Явц"), f"{run.environment_name} · {run.data_file_name}" if run.data_file_name else run.environment_name),
            _s("bi-check2-circle", _("Мөр бүрийн үр дүн"), "✅ ❌ 👁", True),
            _s("bi-image", _("Дэлгэцийн зураг"), _("унасан мөр")),
            _s("bi-check2-square", _("Унасан мөр сонгох"), ""),
            _s("bi-bug", _("Bug ticket"), ""),
            _s("bi-arrow-repeat", _("Дахин ажиллуулах"), _("засварын дараа"), optional=True),
        ],
    }


def datafile(data_file=None, current=()):
    columns = " | ".join(data_file.columns[:4]) if data_file else "Тайлбар | email | хүлээгдэх"
    return {
        "title": _("Өгөгдлийн файл"),
        "steps": [
            _s("bi-download", _("Загвар татах"), "Excel / CSV", "template" in current),
            _s("bi-pencil-square", _("Бөглөх"), columns, "fill" in current),
            _s("bi-upload", _("Оруулах"), "", "upload" in current),
            _s("bi-table", _("Browser-т засах"), "", "edit" in current, optional=True),
            _s("bi-ui-checks", _("Сценарид ашиглах"), "", "use" in current),
        ],
    }
