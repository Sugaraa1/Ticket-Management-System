"""
Хуудас шалгах (PageScan) үед олдсон талбаруудаас тестийн өгөгдлийн файл автоматаар үүсгэнэ:
нэг "бүгд зөв" мөр, дараа нь талбар бүрийг ээлжлэн эвдсэн мөрүүд (бусад талбар зөв хэвээр).
Хариу нь тодорхой (хоосон, буруу формат, богино ...) мөрт 'алдаа' гэж бичнэ; хариуг таах
боломжгүй (хэт урт, SQL/XSS, emoji ...) мөрийн "хүлээгдэх" нүдийг хоосон үлдээнэ — ажиллуулахад
"Гараар шалгах" гарч, QA үр дүнг хараад шийднэ.
"""
from django.utils.translation import gettext as _
from .datafiles import _key, _synonym_group, write_xlsx

to_xlsx = write_xlsx

DESCRIPTION_COLUMN = "Тайлбар"
EXPECTED_COLUMN = "хүлээгдэх"
SUCCESS = "амжилттай"
ERROR = "алдаа"

# Нэг мөрийн дотор {{timestamp}}{{row}} ижил утгатай тул (давтах имэйл г.м.) талбаруудад таарна,
# мөр болон ажиллуулалт бүрт өөр байна — давхардахгүй бүртгэл үүсгэхэд хэрэгтэй.
UNIQUE = "{{timestamp}}{{row}}"
VALID_PASSWORD = "Test#2026abc"
TEXT_TYPES = {"text", "textarea", "search", ""}
LONG_TEXT_LENGTH = 300
SQL_INJECTION = "' OR '1'='1' --"
XSS = "<script>alert(1)</script>"
UNICODE_TEXT = "Тест Öü 😀"
PLACEHOLDER_OPTION_WORDS = ("сонго", "select", "choose", "--", "—")


def _kind(field):
    return field.get("kind") or "text"


def _type(field):
    return (field.get("type") or "").lower()


def _meaning(field):
    """Талбарын нэр/label-ээс утгыг таана: email, phone, username, name ..."""
    for key in ("label", "name", "id", "placeholder"):
        group = _synonym_group(_key(field.get(key, "")))
        for meaning in ("email", "phone", "username", "password", "firstname", "lastname"):
            if meaning in group:
                return meaning
    return ""


def _fit_length(value, field):
    minlength, maxlength = field.get("minlength"), field.get("maxlength")
    if minlength and len(value) < minlength:
        value += "a" * (minlength - len(value))
    if maxlength and len(value) > maxlength:
        value = value[:maxlength]
    return value


def _placeholder_option(options):
    return bool(options) and (
        not options[0].strip() or any(w in options[0].lower() for w in PLACEHOLDER_OPTION_WORDS)
    )


def valid_value(field):
    kind, input_type, meaning = _kind(field), _type(field), _meaning(field)
    if kind == "checkbox":
        return "тийм"
    if kind == "select":
        options = field.get("options") or []
        if _placeholder_option(options):
            options = options[1:]
        return options[0] if options else ""
    if kind == "password" or input_type == "password":
        return _fit_length(VALID_PASSWORD, field)
    if kind == "email" or input_type == "email" or meaning == "email":
        return f"qa{UNIQUE}@example.com"
    if input_type == "number":
        low, high = field.get("min"), field.get("max")
        number = low if low is not None else 1
        if high is not None and number > high:
            number = high
        return str(int(number) if float(number).is_integer() else number)
    if input_type == "tel" or meaning == "phone":
        return "99112233"
    if input_type == "url":
        return "https://example.com"
    if input_type == "date":
        return "2000-01-01"
    if meaning == "username":
        return _fit_length(f"qa{UNIQUE}", field)
    if meaning in ("firstname", "lastname"):
        return _fit_length("Тест", field)
    return _fit_length(f"Тест {UNIQUE}", field)


def invalid_cases(field):
    """[(тайлбар, утга, хүлээгдэх)] — энэ талбарыг эвдсэн мөрүүд."""
    kind, input_type = _kind(field), _type(field)
    label = field["column"]
    cases = []
    if kind == "radio":
        return cases
    if kind == "checkbox":
        if field.get("required"):
            cases.append((_("%(f)s: чагтлаагүй") % {"f": label}, "үгүй", ERROR))
        return cases
    if kind == "select":
        if field.get("required") and _placeholder_option(field.get("options") or []):
            cases.append((_("%(f)s: сонгоогүй") % {"f": label}, "", ERROR))
        return cases

    if field.get("required"):
        cases.append((_("%(f)s: хоосон") % {"f": label}, "", ERROR))
    is_email = kind == "email" or input_type == "email"
    if is_email:
        cases.append((_("%(f)s: буруу формат") % {"f": label}, "abc@@mail", ERROR))
    if field.get("minlength"):
        short = valid_value(field)[: field["minlength"] - 1]
        cases.append((_("%(f)s: богино (%(n)s-аас бага тэмдэгт)") % {"f": label, "n": field["minlength"]},
                      short, ERROR))
    if input_type == "number":
        if field.get("min") is not None:
            cases.append((_("%(f)s: хамгийн багаас бага") % {"f": label}, str(field["min"] - 1), ERROR))
        if field.get("max") is not None:
            cases.append((_("%(f)s: хамгийн ихээс их") % {"f": label}, str(field["max"] + 1), ERROR))
        return cases
    if input_type in ("date", "url"):
        return cases
    if field.get("pattern"):
        cases.append((_("%(f)s: хэв загварт таарахгүй") % {"f": label}, "!@#$%", ERROR))
    if input_type == "tel" and not field.get("pattern"):
        cases.append((_("%(f)s: үсэгтэй") % {"f": label}, "abcdefgh", ""))

    length = (field.get("maxlength") or LONG_TEXT_LENGTH) + (5 if field.get("maxlength") else 0)
    long_value = ("a" * (length - len("@example.com")) + "@example.com") if is_email else "a" * length
    cases.append((_("%(f)s: хэт урт (%(n)s тэмдэгт)") % {"f": label, "n": length}, long_value, ""))
    if kind != "password" and input_type in TEXT_TYPES | {"email"}:
        cases.append((_("%(f)s: SQL injection") % {"f": label}, SQL_INJECTION, ""))
        cases.append((_("%(f)s: XSS") % {"f": label}, XSS, ""))
    if kind == "text" and input_type in TEXT_TYPES:
        cases.append((_("%(f)s: кирилл, emoji") % {"f": label}, UNICODE_TEXT, ""))
    return cases


def _column_names(fields):
    """Талбар бүрт давхардахгүй баганын нэр (label) өгнө."""
    used = {DESCRIPTION_COLUMN.lower(), EXPECTED_COLUMN.lower()}
    for field in fields:
        base = (field.get("label") or field.get("name") or field.get("id") or _("талбар")).strip()[:60]
        name, n = base, 2
        while name.lower() in used:
            name, n = f"{base} {n}", n + 1
        used.add(name.lower())
        field["column"] = name


def generate(scan_fields):
    """
    (баганууд, мөрүүд, {selector: багана}) буцаана. Radio талбарт (сонголт бүр тусдаа талбар)
    болон үндсэн формоос гадуурх талбарт (хэл сонгох г.м.) багана үүсгэхгүй.
    """
    fields = [
        dict(f) for f in scan_fields
        if _kind(f) != "radio" and f.get("selector") and f.get("in_main_form") is not False
    ]
    _column_names(fields)
    valid = {f["column"]: valid_value(f) for f in fields}
    columns = [DESCRIPTION_COLUMN] + [f["column"] for f in fields] + [EXPECTED_COLUMN]

    rows = [[_("Бүх талбар зөв")] + list(valid.values()) + [SUCCESS]]
    for field in fields:
        for description, value, expected in invalid_cases(field):
            values = dict(valid, **{field["column"]: value})
            rows.append([description] + [values[f["column"]] for f in fields] + [expected])
    return columns, rows, {f["selector"]: f["column"] for f in fields}
