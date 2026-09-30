"""
Хуудас шалгах (PageScan) үед олдсон талбаруудаас тестийн өгөгдлийн файл автоматаар үүсгэнэ.

Эхний мөр нь QA-н оруулсан "бүгд зөв" утгууд; бусад мөр бүр түүнээс яг НЭГ зүйлийг өөрчилнө —
тест унавал шалтгаан нь тэр өөрчлөлт. Хариу нь тодорхой мөрт 'алдаа' гэж бичнэ; хариуг таах
боломжгүй (хэт урт, SQL/XSS, emoji ...) мөрийн "хүлээгдэх" нүдийг хоосон үлдээнэ — ажиллуулахад
"Гараар шалгах" гарч, QA үр дүнг хараад шийднэ.

Бүртгэлийн форм: имэйл / хэрэглэгчийн нэрт {{run}} токен нэмж ажиллуулалт, мөр бүрт давхардахгүй
болгоно (утсанд {{digits}}); "давхардсан" мөр нь 1-р мөрийн утгыг яг давтана.
Нэвтрэх форм: бодит бүртгэл дээр суурилна; тэр бүртгэлээр буруу оролдох мөрүүдийг 2-оос илүүгүйгээр
бүлэглэж хооронд нь зөв нэвтрэлт оруулна — олон буруу оролдлогод түгждэг системд бүртгэл түгжигдэхгүй.
"""
from django.utils.translation import gettext as _

from .datafiles import _key, _synonym_group, write_xlsx

to_xlsx = write_xlsx

DESCRIPTION_COLUMN = "Тайлбар"
EXPECTED_COLUMN = "хүлээгдэх"
SUCCESS = "амжилттай"
ERROR = "алдаа"

RUN = "{{run}}"
RUN_ROW = "{{run}}{{row}}"
UNIQUE_SUFFIX_MAX = 14  # {{run}} 10 орон + {{row}} 4 хүртэл орон
VALID_PASSWORD = "Test#2026abc"
TEXT_TYPES = {"text", "textarea", "search", ""}
LONG_TEXT_LENGTH = 300
SQL_INJECTION = "' OR '1'='1' --"
XSS = "<script>alert(1)</script>"
UNICODE_TEXT = "Тест Öü 😀"
PLACEHOLDER_OPTION_WORDS = ("сонго", "select", "choose", "--", "—")
LOGIN_ATTEMPTS_PER_GROUP = 2


class GenerateError(ValueError):
    """QA-н оруулсан утгаар өгөгдөл үүсгэж болохгүй — хэрэглэгчид харуулах мессежтэй."""


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


def _is_password(field):
    return _kind(field) == "password" or _type(field) == "password"


def _is_email(field):
    return _kind(field) == "email" or _type(field) == "email"


def _is_text_like(field):
    """Нэвтрэх нэр байж болох талбар (текст, имэйл, утас)."""
    return _kind(field) in ("text", "email") and _type(field) in TEXT_TYPES | {"email", "tel"}


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


def _has_empty_option(field):
    """Утгагүй сонголттой ("---------") select. Шинэ scan үүнийг хэлнэ, хуучин нь текстээр таана."""
    if "has_empty_option" in field:
        return bool(field["has_empty_option"])
    return _placeholder_option(field.get("options") or [])


def _select_options(field):
    """Жинхэнэ сонголтууд (шинэ scan-д утгагүй сонголт аль хэдийн хасагдсан)."""
    options = field.get("options") or []
    if "has_empty_option" not in field and _placeholder_option(options):
        return options[1:]
    return options


def _other_char(value):
    """Сүүлийн тэмдэгтийг өөр болгоно — урт нь ижил тул maxlength-д тасрахгүй."""
    return value[:-1] + ("x" if value[-1:] != "x" else "y")


def valid_value(field):
    """QA-д санал болгох "зөв" утга (токенгүй — давхардахгүй болгохыг generate хийнэ)."""
    kind, input_type, meaning = _kind(field), _type(field), _meaning(field)
    if field.get("disabled"):
        return ""  # өөр талбараас хамаарч идэвхждэг (ж: дэд ангилал) — бөглөхгүй
    if kind == "checkbox":
        return "тийм"
    if kind == "select":
        options = _select_options(field)
        return options[0] if options else ""
    if _is_password(field):
        return _fit_length(VALID_PASSWORD, field)
    if _is_email(field) or meaning == "email":
        return "qa@example.com"
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
        return _fit_length("qa", field)
    return _fit_length("Тест", field)


# --- Талбарууд ----------------------------------------------------------------

def _column_names(fields):
    """Талбар бүрт давхардахгүй баганын нэр (label) өгнө."""
    used = {DESCRIPTION_COLUMN.lower(), EXPECTED_COLUMN.lower()}
    for field in fields:
        # Таслаад дараа нь strip — эс тэгвэл төгсгөлийн зай үлдэж, файлаас уншихад (strip) нэр таарахгүй.
        base = (field.get("label") or field.get("name") or field.get("id") or _("талбар")).strip()[:60].strip()
        name, n = base, 2
        while name.lower() in used:
            name, n = f"{base} {n}", n + 1
        used.add(name.lower())
        field["column"] = name


def form_fields(scan_fields):
    """
    Өгөгдөл үүсгэх талбарууд (баганын нэртэй). Radio (сонголт бүр тусдаа талбар) болон үндсэн
    формоос гадуурх талбарт (хэл сонгох г.м.) багана үүсгэхгүй.
    """
    fields = [
        dict(f) for f in scan_fields
        if _kind(f) != "radio" and f.get("selector") and f.get("in_main_form") is not False
    ]
    _column_names(fields)
    return fields


def _login_parts(fields):
    """(нэвтрэх нэрийн талбар, нууц үгийн талбар) эсвэл None."""
    passwords = [f for f in fields if _is_password(f)]
    texts = [f for f in fields if _is_text_like(f)]
    if len(passwords) != 1 or not texts:
        return None
    named = [f for f in texts if _is_email(f) or _meaning(f) in ("username", "email", "phone")]
    return (named or texts)[0], passwords[0]


def looks_like_login(fields):
    """Нэг нууц үг + нэг нэвтрэх нэр, бусад нь зөвхөн чагт (намайг сана г.м.)."""
    others = [f for f in fields if not _is_password(f) and not _is_text_like(f)]
    return (
        _login_parts(fields) is not None
        and sum(1 for f in fields if _is_text_like(f)) == 1
        and all(_kind(f) == "checkbox" for f in others)
    )


def generate_form(scan_fields):
    """Хэрэглэгчид харуулах маягт: {login, fields: [{selector, column, ..., value}]}."""
    fields = form_fields(scan_fields)
    login = looks_like_login(fields)
    parts = _login_parts(fields) if login else ()
    return {
        "login": login,
        "fields": [
            {
                "selector": f["selector"], "column": f["column"], "kind": _kind(f), "type": _type(f),
                "required": bool(f.get("required")), "options": f.get("options") or [],
                # Нэвтрэх формд бодит бүртгэл хэрэгтэй — таамаг утга санал болгохгүй.
                "value": "" if f in parts else valid_value(f),
            }
            for f in fields
        ],
    }


# --- Ердийн форм (бүртгэл г.м.) ------------------------------------------------

def _unique_field(field):
    """Систем давхардуулахгүй байж магадгүй талбар: имэйл, хэрэглэгчийн нэр."""
    return _is_text_like(field) and (_is_email(field) or _meaning(field) in ("email", "username"))


def _with_token(value, token, field):
    """Утгад токен нэмнэ (имэйлд @-ийн өмнө). maxlength-д багтахгүй бол None."""
    local, at, domain = value.partition("@") if "@" in value else (value, "", "")
    maxlength = field.get("maxlength")
    if maxlength:
        room = maxlength - UNIQUE_SUFFIX_MAX - len(at + domain)
        if room < 1:
            return None
        local = local[:room]
    return f"{local}{token}{at}{domain}"


def _phone_token(value):
    """Утасны сүүлийн 6 оронг {{digits}} болгоно (эхний орнууд — оператор — хэвээр)."""
    digits = value.strip()
    if digits.isdigit() and len(digits) >= 8:
        return digits[:-6] + "{{digits}}"
    return value


def _password_pair(fields):
    """(нууц үг, нууц үг давтах) — 2+ нууц үгийн талбартай бол сүүлийн хоёр."""
    passwords = [f for f in fields if _is_password(f)]
    return (passwords[-2], passwords[-1]) if len(passwords) >= 2 else (None, None)


def _invalid_cases(field, base):
    """[(тайлбар, утга, хүлээгдэх)] — энэ талбарыг эвдсэн мөрүүд (base — QA-н зөв утга)."""
    kind, input_type = _kind(field), _type(field)
    label = field["column"]
    cases = []
    if field.get("disabled"):
        return cases
    if kind == "checkbox":
        if field.get("required"):
            cases.append((_("%(f)s: чагтлаагүй") % {"f": label}, "үгүй", ERROR))
        return cases
    if kind == "select":
        if field.get("required") and _has_empty_option(field):
            cases.append((_("%(f)s: сонгоогүй") % {"f": label}, "", ERROR))
        return cases

    if field.get("required"):
        cases.append((_("%(f)s: хоосон") % {"f": label}, "", ERROR))
    is_email = _is_email(field)
    if is_email:
        cases.append((_("%(f)s: буруу формат") % {"f": label}, "abc@@mail", ERROR))
    if field.get("minlength"):
        short = _fit_length(base, {"minlength": field["minlength"]})[: field["minlength"] - 1]
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
    if not _is_password(field) and input_type in TEXT_TYPES | {"email"}:
        cases.append((_("%(f)s: SQL injection") % {"f": label}, SQL_INJECTION, ""))
        cases.append((_("%(f)s: XSS") % {"f": label}, XSS, ""))
    if kind == "text" and input_type in TEXT_TYPES:
        cases.append((_("%(f)s: кирилл, emoji") % {"f": label}, UNICODE_TEXT, ""))
    return cases


def _form_rows(fields, base):
    first, other, duplicates = dict(base), dict(base), []
    for field in fields:
        column, value = field["column"], base[field["column"]]
        if not value or "{{" in value:
            continue
        if _unique_field(field):
            first_value, other_value = _with_token(value, RUN, field), _with_token(value, RUN_ROW, field)
            if first_value:
                first[column], other[column] = first_value, other_value
                duplicates.append(field)
        elif _type(field) == "tel" or _meaning(field) == "phone":
            first[column] = other[column] = _phone_token(value)

    password, confirm = _password_pair(fields)
    rows = [(_("Бүх талбар зөв"), first, SUCCESS)]
    for field in fields:
        column = field["column"]
        if confirm is not None and field is confirm:
            cases = []
            if field.get("required"):
                cases.append((_("%(f)s: хоосон") % {"f": column}, "", ERROR))
            if base[column]:
                cases.append((_("%(f)s: таарахгүй") % {"f": column}, _other_char(base[column]), ERROR))
        else:
            cases = _invalid_cases(field, base[column])
        for description, value, expected in cases:
            values = dict(other, **{column: value})
            if field is password:  # давтах талбар ижил байж зөвхөн нууц үгийн дүрэм шалгагдана
                values[confirm["column"]] = value
            rows.append((description, values, expected))
    for field in duplicates:
        values = dict(other, **{field["column"]: first[field["column"]]})
        rows.append((_("%(f)s: давхардсан (1-р мөртэй ижил)") % {"f": field["column"]}, values, ERROR))
    return rows


# --- Нэвтрэх форм ---------------------------------------------------------------

def _login_rows(fields, base):
    user, password = _login_parts(fields)
    ucol, pcol = user["column"], password["column"]
    username, secret = base[ucol], base[pcol]
    ok = (_("Бүх талбар зөв"), base, SUCCESS)

    def row(description, expected, n=None, **changes):
        values = dict(base)
        values.update({ucol if k == "user" else pcol: v for k, v in changes.items()})
        return description % {"u": ucol, "p": pcol, "n": n}, values, expected

    def too_long(field):
        return (field.get("maxlength") or LONG_TEXT_LENGTH) + (5 if field.get("maxlength") else 0)

    # Бодит бүртгэлээр буруу оролдох (түгжих тоолуурт орж болох) мөрүүд.
    attempts = [row(_("%(p)s: буруу"), ERROR, password=_other_char(secret))]
    if secret.swapcase() != secret:
        attempts.append(row(_("%(p)s: том/жижиг үсэг солисон"), ERROR, password=secret.swapcase()))
    attempts += [
        row(_("%(p)s: хоосон"), ERROR, password=""),
        row(_("%(p)s: SQL injection"), ERROR, password=SQL_INJECTION),
        row(_("%(p)s: хэт урт (%(n)s тэмдэгт)"), ERROR, too_long(password), password="a" * too_long(password)),
    ]
    changed_case = username.upper() if username.upper() != username else username.lower()
    if changed_case != username:
        attempts.append(row(_("%(u)s: том/жижиг үсэг солисон"), "", user=changed_case))
    attempts.append(row(_("%(u)s: урд, хойно зайтай"), "", user=f" {username} "))

    rows = [ok]
    for index in range(0, len(attempts), LOGIN_ATTEMPTS_PER_GROUP):
        if index:
            rows.append((_("Бүх талбар зөв (дахин нэвтрэх)"), base, SUCCESS))
        rows += attempts[index:index + LOGIN_ATTEMPTS_PER_GROUP]

    # Бодит бүртгэлд хамаарахгүй (өөр хэрэглэгчийн нэртэй) мөрүүд.
    missing = "nouser{{run}}{{row}}"
    if _is_email(user) or "@" in username:
        missing += "@example.com"
    rows += [
        row(_("%(u)s: бүртгэлгүй хэрэглэгч"), ERROR, user=missing),
        row(_("%(u)s: хоосон"), ERROR, user=""),
    ]
    if _is_email(user):
        rows.append(row(_("%(u)s: буруу формат"), ERROR, user="abc@@mail"))
    rows += [
        row(_("%(u)s: SQL injection"), ERROR, user=SQL_INJECTION),
        row(_("%(u)s: SQL тайлбар (нэр' --)"), ERROR, user=f"{username}' --"),
        row(_("%(u)s: XSS"), ERROR, user=XSS),
        row(_("%(u)s: хэт урт (%(n)s тэмдэгт)"), ERROR, too_long(user), user="a" * too_long(user)),
        row(_("%(u)s: кирилл, emoji"), ERROR, user=UNICODE_TEXT),
    ]
    return rows


# --- Үүсгэх ---------------------------------------------------------------------

def _validate(fields, base, login):
    if login:
        parts = _login_parts(fields)
        if parts is None:
            raise GenerateError(_("Нэвтрэх форм биш байна: нэг нууц үгийн талбар, нэг нэвтрэх нэрийн талбар хэрэгтэй."))
        missing = [f["column"] for f in parts if not base[f["column"]]]
    else:
        missing = [
            f["column"] for f in fields
            if f.get("required") and not f.get("disabled") and (not base[f["column"]] or _kind(f) == "checkbox" and not _checked(base[f["column"]]))
        ]
        password, confirm = _password_pair(fields)
        if confirm is not None and base[password["column"]] != base[confirm["column"]]:
            raise GenerateError(_("«%(a)s» ба «%(b)s» ижил байх ёстой.") % {"a": password["column"], "b": confirm["column"]})
    if missing:
        raise GenerateError(_("Бөглөнө үү: %(cols)s") % {"cols": ", ".join(missing)})


def _checked(value):
    from .runner import TRUTHY

    return value.strip().lower() in TRUTHY


def _given(field, values):
    if field["selector"] not in values:
        return valid_value(field)
    value = str(values[field["selector"]] or "")
    return value if _is_password(field) else value.strip()  # нууц үгийн зайг хадгална


def generate(scan_fields, values=None, login=None):
    """
    (баганууд, мөрүүд, {selector: багана}) буцаана. values — {selector: QA-н зөв утга} (байхгүй талбарт
    санал болгох утга); login=None бол талбараас таана. Буруу оролтод GenerateError.
    """
    fields = form_fields(scan_fields)
    values = values or {}
    if login is None:
        login = looks_like_login(fields)
    base = {f["column"]: _given(f, values) for f in fields}
    _validate(fields, base, login)
    columns = [DESCRIPTION_COLUMN] + [f["column"] for f in fields] + [EXPECTED_COLUMN]
    rows = [
        [description] + [row_values[f["column"]] for f in fields] + [expected]
        for description, row_values, expected in (_login_rows if login else _form_rows)(fields, base)
    ]
    return columns, rows, {f["selector"]: f["column"] for f in fields}
