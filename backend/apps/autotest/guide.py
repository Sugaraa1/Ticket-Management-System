"""
Autotest-ийн хуудас бүрийн "Workflow" самбар: тухайн хуудсан дээр юу хийхийг зураг маягаар (дугаартай алхам,
богино нэр, бодит жишээ) харуулна. Апп, сценари г.м. бодит объектоос жишээгээ авдаг тул шинэ сценари үүсгэхэд
workflow нь өөрөө үүснэ.
"""
from django.utils.translation import gettext as _


def _s(icon, label, example="", current=False, optional=False, key="", desc=""):
    return {
        "icon": icon, "label": label, "desc": desc, "example": example, "current": current, "optional": optional,
        "key": key,
    }


def overview(app=None, current=()):
    """Бүх процесс: апп бүртгэхээс bug ticket хүртэл."""
    env = app.environments.first() if app else None
    pages = list(app.pages.all()[:2]) if app else []
    account = app.accounts.first() if app else None
    return {
        "title": _("Автомат тест"),
        "steps": [
            _s("bi-app-indicator", _("Апп бүртгэх"), app.name if app else "", "app" in current, desc=_("Шалгах системээ нэр, ангиллаар нэмнэ")),
            _s("bi-hdd-network", _("Орчин нэмэх"), env.base_url if env else "", "env" in current, desc=_("Тест аль хаяг дээр ажиллахыг заана")),
            _s("bi-file-earmark", _("Хуудас нэмэх"), ", ".join(p.path for p in pages), "page" in current, desc=_("Шалгах хуудсуудын замыг бүртгэнэ")),
            _s("bi-person-badge", _("Тестийн хэрэглэгч"), f"{account.label} · {account.username}" if account else "",
               "account" in current, optional=True, desc=_("Нэвтэрч ордог хуудсанд л хэрэгтэй")),
            _s("bi-file-earmark-spreadsheet", _("Өгөгдлийн файл"), "Excel / CSV", "file" in current, desc=_("Мөр бүр нэг тест болно")),
            _s("bi-ui-checks", _("Сценари үүсгэх"), _("Веб форм / API"), "scenario" in current, desc=_("Хуудас, талбар, хүлээгдэх үр дүнг тохируулна")),
            _s("bi-play-fill", _("Ажиллуулах"), "", "run" in current, desc=_("Мөр бүрийг автоматаар бөглөж илгээнэ")),
            _s("bi-check2-circle", _("Үр дүн"), "✅ ❌", "result" in current, desc=_("Мөр бүр тэнцсэн, унасан эсэх")),
            _s("bi-bug", _("Bug ticket"), "", "bug" in current, desc=_("Унасан мөрөөс нэг товчоор ticket үүснэ")),
        ],
    }


def scenario_form(app, page=None, scenario=None):
    """Веб сценари үүсгэх: key-тэй алхмуудыг scenario_form-ын JS сонголт, scan-ы үр дүнгээр шинэчилнэ."""
    return {
        "title": _("Сценари засах") if scenario else _("Шинэ сценари"),
        "steps": [
            _s("bi-file-earmark", _("Хуудас сонгох"), f"{page.name} — {page.path}" if page else "", key="page", desc=_("Аль хуудсыг шалгахаа dropdown-оос сонгоно")),
            _s("bi-search", _("Хуудсыг шалгах"), "", key="fields", desc=_("Систем хуудсыг нээж талбаруудыг олно")),
            _s("bi-arrow-left-right", _("Талбар ↔ багана"), "", desc=_("Талбар бүрт файлын аль баганыг бичихийг холбоно")),
            _s("bi-magic", _("Тест өгөгдөл үүсгэх"), "", key="rows", desc=_("Тестэд тохирох зөв, буруу өгөгдөл автоматаар үүснэ")),
            _s("bi-flag", _("Хүлээгдэх үр дүн"), _("амжилттай / алдаа"), desc=_("Мөр бүрт ямар хариу гарах ёстойг заана")),
            _s("bi-save", _("Хадгалах"), "", desc=_("Сценари бэлэн болж ажиллуулж болно")),
        ],
    }


def api_scenario_form(app, scenario=None):
    """Засах үед сценарийн бодит утга, шинээр үүсгэхэд жишээ."""
    path = f"{scenario.api_method} {scenario.api_path}" if scenario and scenario.api_path else "POST /api/users"
    body = scenario.api_body.strip()[:80] if scenario and scenario.api_body.strip() else '{"email": "{{email}}"}'
    return {
        "title": _("API сценари засах") if scenario else _("Шинэ API сценари"),
        "steps": [
            _s("bi-signpost", _("Method + зам"), path, desc=_("Ямар хаяг руу ямар хүсэлт илгээхийг")),
            _s("bi-braces", _("Body"), body, desc=_("{{багана}} нь файлын утгаар солигдоно")),
            _s("bi-key", _("Хэн болж шалгах"), "QA → token", optional=True, desc=_("Нэвтэрч token авсны дараа хүсэлт илгээнэ")),
            _s("bi-flag", _("Хүлээгдэх үр дүн"), "201 · 400: …", desc=_("Мөр бүрт ямар хариу гарах ёстойг заана")),
            _s("bi-save", _("Хадгалах"), "", desc=_("Сценари бэлэн болж ажиллуулж болно")),
        ],
    }


def scenario_detail(scenario, last_run=None):
    target = f"{scenario.api_method} {scenario.api_path}" if scenario.is_api else (scenario.page.path if scenario.page else "")
    picked = " · ".join(filter(None, [last_run.data_file_name, last_run.environment_name])) if last_run else ""
    steps = []
    if scenario.account_id:
        steps.append(_s("bi-key", _("Нэвтрэх"), f"{scenario.account.label} · {scenario.account.username}", desc=_("Тестийн хэрэглэгчээр эхлээд нэвтэрнэ")))
    steps += [
        _s("bi-sliders", _("Файл + орчин сонгох"), picked, desc=_("Аль өгөгдлөөр, аль хаяг дээр шалгах")),
        _s("bi-play-fill", _("Ажиллуулах"), target, desc=_("Мөр бүрийг автоматаар бөглөж илгээнэ")),
        _s("bi-list-ol", _("Тестийн алхмууд"), "", key="steps", desc=_("Мөр бүр юу хийхийг алхмаар харна")),
        _s("bi-check2-circle", _("Үр дүн"), f"{last_run.pass_rate}%" if last_run and last_run.pass_rate is not None else "✅ ❌", desc=_("Мөр бүр тэнцсэн, унасан эсэх")),
        _s("bi-bug", _("Bug ticket"), "", desc=_("Унасан мөрөөс нэг товчоор ticket үүснэ")),
    ]
    if not scenario.is_api:
        steps.append(_s("bi-shield-lock", _("Эрх шалгах"), "", optional=True, desc=_("Хэрэглэгч бүрт хуудас нээгдэх эсэх")))
    return {"title": scenario.name, "steps": steps}


def run_detail(run):
    return {
        "title": f"{run.scenario.name} #{run.pk}",
        "steps": [
            _s("bi-hourglass-split", _("Явц"), f"{run.environment_name} · {run.data_file_name}" if run.data_file_name else run.environment_name, desc=_("Мөрүүд нэг нэгээр ажиллана")),
            _s("bi-check2-circle", _("Мөр бүрийн үр дүн"), "✅ ❌ 👁", desc=_("✅ тэнцсэн, ❌ унасан, 👁 гараар шалгах")),
            _s("bi-image", _("Дэлгэцийн зураг"), "", desc=_("Унасан мөр дээр хуудас ямар байсныг харна")),
            _s("bi-check2-square", _("Унасан мөр сонгох"), "", desc=_("Bug болгох мөрүүдээ чагтална")),
            _s("bi-bug", _("Bug ticket"), "", desc=_("Унасан мөрөөс нэг товчоор ticket үүснэ")),
            _s("bi-arrow-repeat", _("Дахин ажиллуулах"), "", optional=True, desc=_("Засварласны дараа ижил тестийг давтана")),
        ],
    }


def datafile(data_file=None, current=()):
    columns = " | ".join(data_file.columns[:4]) if data_file else "Тайлбар | email | хүлээгдэх"
    return {
        "title": _("Өгөгдлийн файл"),
        "steps": [
            _s("bi-download", _("Загвар татах"), "Excel / CSV", "template" in current, desc=_("Жишээ баганатай Excel файл")),
            _s("bi-pencil-square", _("Бөглөх"), columns, "fill" in current, desc=_("Мөр бүрт нэг тестийн өгөгдөл бичнэ")),
            _s("bi-upload", _("Оруулах"), "", "upload" in current, desc=_("Excel эсвэл CSV файлаа оруулна")),
            _s("bi-table", _("Browser-т засах"), "", "edit" in current, optional=True, desc=_("Мөр, баганаа шууд засаж болно")),
            _s("bi-ui-checks", _("Сценарид ашиглах"), "", "use" in current, desc=_("Нэг файлыг олон сценари ашиглана")),
        ],
    }
