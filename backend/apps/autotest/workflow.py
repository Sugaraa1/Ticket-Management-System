"""
Сценарийн workflow: тест мөр бүрт ямар алхмуудыг хийхийг код мэдэхгүй хүнд ойлгомжтой харуулна.
Сценарийн тохиргооноос шууд гаргана (тусад нь зурах шаардлагагүй); мөр сонговол тэр мөрийн утгаар бөглөнө.
"""
import json

from django.utils.translation import gettext as _

from .api import is_secret_column, parse_expected_api, render, TemplateError
from .datafiles import DataFileError, description_of, fill_placeholders, placeholder_values, read_rows

MAX_ROWS = 200


def load_rows(data_file):
    """[(мөрийн дугаар, тайлбар, мөр)] — эхний MAX_ROWS мөр."""
    try:
        with data_file.file.open("rb") as fh:
            _columns, rows = read_rows(fh, data_file.file.name)
    except (DataFileError, FileNotFoundError, OSError):
        return []
    return [(number, description_of(row), row) for number, row in rows[:MAX_ROWS]]


def _value(column, row, values, secret):
    """Файлын баганаас авах утга: мөр сонгоогүй бол None, нууц бол ***."""
    if row is None:
        return None
    value = values.get(column, "")
    return "***" if secret and value else value


def _step(icon, title, **extra):
    return {"icon": icon, "title": title, "items": [], "detail": "", "code": "", **extra}


def _login_step(scenario):
    account = scenario.account
    step = _step("bi-key", _("Нэвтрэх"))
    step["items"].append({"label": _("Хэрэглэгч"), "value": f"{account.label} · {account.username}"})
    if scenario.is_api:
        step["detail"] = f"POST {scenario.app.api_login_path or '?'} → token"
    elif scenario.app.login_page_id:
        step["detail"] = scenario.app.login_page.path
    return step


def _expected_step(scenario, outcome, message, status=None, row=None):
    step = _step("bi-flag", _("Үр дүнг шалгах"))
    if row is not None and not outcome and not message and not status:
        step["verdict"] = "manual"
        step["items"].append({"label": _("Хүлээгдэх"), "value": _("Гараар шалгах")})
        return step
    if row is None:
        column = scenario.expected_column
        step["items"].append({
            "label": _("Хүлээгдэх"), "value": None if column else _("Гараар шалгах"), "column": column,
        })
    else:
        if status:
            step["items"].append({"label": _("Status код"), "value": str(status)})
        if outcome:
            step["verdict"] = outcome
            step["items"].append({
                "label": _("Хүлээгдэх"), "value": _("Амжилттай") if outcome == "success" else _("Алдаа гарна"),
            })
        if message:
            step["items"].append({"label": _("Гарах текст"), "value": message})
    if not scenario.is_api and outcome != "error":
        mode = scenario.get_success_mode_display() if scenario.success_mode != scenario.SuccessMode.AUTO else ""
        if mode:
            step["detail"] = f"{mode}: “{scenario.success_value}”"
    return step


def web_steps(scenario, row=None, line_number=1):
    values = {}
    if row is not None:
        placeholders = placeholder_values(line_number)
        values = {k: fill_placeholders(v, line_number, placeholders) for k, v in row.items()}
    steps = []
    if scenario.account_id:
        steps.append(_login_step(scenario))
    open_step = _step("bi-window", _("Хуудас нээх"))
    open_step["items"].append({"label": scenario.page.name if scenario.page else "", "value": scenario.page.path if scenario.page else "/"})
    steps.append(open_step)
    for field in scenario.fields:
        source, label = field.get("source"), field.get("label") or field.get("selector")
        if source == "check":
            steps.append(_step("bi-check2-square", _("«%(label)s» чагтлах") % {"label": label}))
            continue
        if source not in ("column", "constant"):
            continue
        kind = field.get("kind")
        if kind == "select":
            icon, title = "bi-menu-button-wide", _("«%(label)s» сонгох") % {"label": label}
        elif kind in ("checkbox", "radio"):
            icon, title = "bi-ui-radios", _("«%(label)s» сонгох") % {"label": label}
        else:
            icon, title = "bi-input-cursor-text", _("«%(label)s» бөглөх") % {"label": label}
        step = _step(icon, title)
        secret = kind == "password"
        if source == "column":
            step["items"].append({"value": _value(field["value"], row, values, secret), "column": field["value"]})
        else:
            value = field.get("value", "")
            step["items"].append({"value": "***" if secret and value else value})
        steps.append(step)
    steps.append(_step("bi-hand-index", _("«%(label)s» товч дарах") % {"label": scenario.submit_label or _("Илгээх")}))
    if row is None:
        steps.append(_expected_step(scenario, "", ""))
    else:
        from .runner import _expected_for

        outcome, message = _expected_for(scenario, row)
        steps.append(_expected_step(scenario, outcome, message, row=row))
    return steps


def api_steps(scenario, row=None, line_number=1):
    steps = []
    if scenario.account_id:
        steps.append(_login_step(scenario))
    request = _step("bi-send", _("Хүсэлт илгээх"))
    path, body = scenario.api_path, scenario.api_body
    if row is not None:
        placeholders = placeholder_values(line_number)
        values = {k: fill_placeholders(v, line_number, placeholders) for k, v in row.items()}
        values.update(placeholders)
        for column in values:
            if is_secret_column(column) and values[column]:
                values[column] = "***"
        try:
            path = render(path, values, "url")
            body = render(body, values, "json" if body.strip().startswith(("{", "[")) else "raw")
            body = json.dumps(json.loads(body), ensure_ascii=False, indent=2)
        except (TemplateError, ValueError):
            pass
    request["items"].append({"label": scenario.api_method, "value": path, "mono": True})
    request["code"] = "\n".join(filter(None, [scenario.api_headers.strip(), body.strip()]))
    steps.append(request)
    if row is None:
        steps.append(_expected_step(scenario, "", ""))
    else:
        raw = row.get(scenario.expected_column, "") if scenario.expected_column else ""
        outcome, status, message = parse_expected_api(raw)
        if scenario.expected_message_column and row.get(scenario.expected_message_column):
            message = row[scenario.expected_message_column]
        steps.append(_expected_step(scenario, outcome, message, status=status, row=row))
    return steps


def build(scenario, row=None, line_number=1):
    return api_steps(scenario, row, line_number) if scenario.is_api else web_steps(scenario, row, line_number)


def context(scenario, data_file_id=None, line_number=None):
    """Workflow tab-ын context: сонгох боломжтой файлууд, мөрүүд, сонгосон мөрийн алхмууд."""
    from .models import DataFile

    files = [
        f for f in DataFile.objects.filter(category_id=scenario.app.category_id)
        if not scenario.missing_columns(f)
    ]
    data_file = next((f for f in files if str(f.pk) == str(data_file_id)), files[0] if files else None)
    rows = load_rows(data_file) if data_file else []
    current = next((r for r in rows if str(r[0]) == str(line_number)), rows[0] if rows else None)
    return {
        "wf_files": files,
        "wf_file": data_file,
        "wf_rows": rows,
        "wf_row": current,
        "wf_steps": build(scenario, current[2], current[0]) if current else build(scenario),
    }

