"""
Өгөгдлийн файл (Excel/CSV) унших, хүлээгдэх үр дүнг ойлгох, хуудасны талбарыг
файлын баганатай автоматаар тааруулах — browser-гүй цэвэр логик.
"""
import csv
import datetime
import io
import os
import re
import secrets
import time

from django.conf import settings
from django.utils.translation import gettext as _

ALLOWED_EXTENSIONS = ("xlsx", "csv")
DESCRIPTION_COLUMNS = ("тайлбар", "description", "кейс", "case", "нэр")


class DataFileError(ValueError):
    """Файлыг уншиж чадаагүй — хэрэглэгчид харуулах ойлгомжтой мессежтэй."""


def max_rows():
    return getattr(settings, "AUTOTEST_MAX_ROWS", 1000)


def read_rows(fileobj, filename):
    """
    (баганууд, мөрүүд) буцаана. Мөр бүр (Excel дээрх мөрийн дугаар, {багана: текст}) —
    хоосон мөрийг алгасах тул дугаар нь QA-д файлаасаа мөрөө олоход хэрэгтэй.
    """
    ext = os.path.splitext(filename)[1].lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        raise DataFileError(_("Зөвхөн .xlsx эсвэл .csv файл оруулна уу."))
    fileobj.seek(0)
    raw = _read_xlsx(fileobj) if ext == "xlsx" else _read_csv(fileobj)
    if not raw:
        raise DataFileError(_("Файл хоосон байна."))

    header = [_cell_text(c) for c in raw[0]]
    while header and not header[-1]:
        header.pop()
    if not header:
        raise DataFileError(_("Эхний мөрөнд баганын нэрс байх ёстой."))
    if "" in header:
        position = header.index("") + 1
        raise DataFileError(_("%(n)s-р баганын нэр хоосон байна.") % {"n": position})
    duplicates = sorted({c for c in header if header.count(c) > 1})
    if duplicates:
        raise DataFileError(_("Давхардсан баганын нэр: %(cols)s") % {"cols": ", ".join(duplicates)})

    rows = []
    for line_number, values in enumerate(raw[1:], start=2):
        values = [_cell_text(v) for v in values[: len(header)]]
        if not any(values):
            continue
        values += [""] * (len(header) - len(values))
        rows.append((line_number, dict(zip(header, values))))
    if not rows:
        raise DataFileError(_("Файлд өгөгдлийн мөр алга (зөвхөн гарчгийн мөр байна)."))
    if len(rows) > max_rows():
        raise DataFileError(
            _("Файлд %(n)s мөр байна — нэг файлд хамгийн ихдээ %(max)s мөр байна.")
            % {"n": len(rows), "max": max_rows()}
        )
    return header, rows


def _read_xlsx(fileobj):
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(fileobj, read_only=True, data_only=True)
    except Exception:
        raise DataFileError(_("Excel файлыг уншиж чадсангүй. Файл эвдэрсэн эсэхийг шалгана уу."))
    try:
        sheet = workbook.worksheets[0]
        # Жижиг файлд сая сая хоосон/давтагдсан мөр шахаж болно — хязгаараас хэтэрмэгц зогсоно
        # (гарчиг + max_rows мөрөөс нэгийг илүү уншиж, read_rows "хэт олон мөр" гэж хэлнэ).
        # Хоосон мөр байрандаа үлдэнэ ([]) — Excel-ийн мөрийн дугаар зөв гарна.
        raw, filled = [], 0
        for row in sheet.iter_rows(values_only=True):
            if any(value not in (None, "") for value in row):
                raw.append(list(row))
                filled += 1
                if filled > max_rows() + 1:
                    break
            else:
                raw.append([])
        return raw
    finally:
        workbook.close()


def write_xlsx(columns, rows):
    """
    Гарчиг + мөрүүдийг .xlsx болгоно. Бүх утгыг текстээр хадгална — "=..."-ээр эхэлсэн утгыг
    openpyxl томьёо гэж бичвэл дахин уншихад (data_only) хоосон болдог.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = _("Өгөгдөл")
    for row_index, values in enumerate([columns, *rows], start=1):
        for col_index, value in enumerate(values, start=1):
            cell = sheet.cell(row=row_index, column=col_index)
            cell.value = "" if value is None else str(value)
            cell.data_type = "s"
            if row_index == 1:
                cell.font = Font(bold=True)
    for column in sheet.columns:
        width = max(len(str(cell.value or "")) for cell in column)
        sheet.column_dimensions[column[0].column_letter].width = min(max(width + 2, 10), 40)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def write_csv(columns, rows):
    """
    UTF-8 BOM-тэй CSV — Excel кирилл үсгийг зөв нээнэ. Утгыг өөрчлөхгүй тул татаж аваад
    дахин оруулахад ижил өгөгдөл болно (read_rows BOM-ийг хасна).
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    for values in [columns, *rows]:
        writer.writerow(["" if value is None else str(value) for value in values])
    return buffer.getvalue().encode("utf-8-sig")


def write_table(columns, rows, fmt):
    """fmt: 'xlsx' эсвэл 'csv'."""
    return write_csv(columns, rows) if fmt == "csv" else write_xlsx(columns, rows)


def _read_csv(fileobj):
    data = fileobj.read()
    if isinstance(data, bytes):
        for encoding in ("utf-8-sig", "cp1251"):
            try:
                data = data.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            raise DataFileError(_("CSV файлын кодчлолыг таньсангүй. UTF-8-аар хадгална уу."))
    try:
        dialect = csv.Sniffer().sniff(data[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [row for row in csv.reader(io.StringIO(data), dialect)]


def _cell_text(value):
    if value is None:
        return ""
    if isinstance(value, datetime.datetime):  # Excel-ийн огноо нүд → '2024-01-05' ('00:00:00'-гүй)
        if value.time() == datetime.time():
            return value.date().isoformat()
        return value.isoformat(sep=" ", timespec="minutes")
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, datetime.time):
        return value.isoformat(timespec="minutes")
    if isinstance(value, float) and value.is_integer():
        value = int(value)  # Excel 99112233-ийг 99112233.0 болгодог
    return str(value).strip()


def description_of(row):
    for column, value in row.items():
        if column.strip().lower() in DESCRIPTION_COLUMNS and value:
            return value[:300]
    return ""


# --- Хүлээгдэх үр дүн ------------------------------------------------------

SUCCESS_WORDS = {"амжилттай", "амжилт", "success", "ok", "pass", "passed", "тийм", "✅", "✔"}
ERROR_WORDS = {"алдаа", "алдаатай", "error", "fail", "failed", "invalid", "үгүй", "❌", "✖"}


def parse_expected(text):
    """
    'амжилттай' → ("success", ""), 'алдаа: И-мэйл буруу' → ("error", "И-мэйл буруу").
    Ойлгохгүй бол (None, text).
    """
    text = (text or "").strip()
    if not text:
        return "", ""
    head, sep, rest = text.partition(":")
    word = head.strip().lower()
    if word in SUCCESS_WORDS:
        return "success", rest.strip()
    if word in ERROR_WORDS:
        return "error", rest.strip()
    return None, text


def judge(expected_outcome, expected_message, actual_outcome, actual_text):
    """Хүлээгдэх үр дүнгүй бол 'recorded', үгүй бол 'pass' / 'fail'."""
    if not expected_outcome and not expected_message:
        return "recorded"
    if expected_outcome and expected_outcome != actual_outcome:
        return "fail"
    if expected_message and _norm_text(expected_message) not in _norm_text(actual_text):
        return "fail"
    return "pass"


def _norm_text(text):
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


# --- Placeholder ------------------------------------------------------------

PLACEHOLDER_RE = re.compile(r"\{\{\s*(random|timestamp|row|run|digits)\s*\}\}")


def run_stamp():
    """{{run}} — ажиллуулалт эхэлсэн unix секунд (10 оронтой тул {{run}}{{row}} ажиллуулалт хооронд давхардахгүй)."""
    return str(int(time.time()))


def placeholder_values(row_number, run=None):
    """Нэг мөрийн placeholder-ууд — мөр доторх бүх нүдэд ижил (нууц үг давтах г.м.), мөр бүрт шинэ."""
    now = str(int(time.time()))
    return {
        "random": secrets.token_hex(3), "timestamp": now, "row": str(row_number),
        "run": run or now, "digits": f"{secrets.randbelow(10 ** 6):06d}",
    }


def fill_placeholders(value, row_number, values=None):
    """
    {{random}} — мөр бүрт шинэ 6 тэмдэгт, {{digits}} — мөр бүрт шинэ 6 орон, {{timestamp}} — unix секунд,
    {{row}} — мөрийн дугаар, {{run}} — нэг ажиллуулалтын бүх мөрт ижил.
    """
    values = values or placeholder_values(row_number)
    return PLACEHOLDER_RE.sub(lambda match: values[match.group(1)], value or "")


# --- Талбар ↔ багана автоматаар тааруулах ---------------------------------

SYNONYMS = [
    {"email", "e-mail", "mail", "имэйл", "и-мэйл", "имэйлхаяг", "мэйл", "цахимшуудан", "цахимхаяг"},
    {"password", "pass", "pwd", "нууцүг", "passwd"},
    {"passwordconfirm", "confirmpassword", "password2", "repeatpassword", "нууцүгдавтах",
     "нууцүгбаталгаажуулах", "нууцүгдахин", "passwordconfirmation"},
    {"phone", "mobile", "tel", "telephone", "утас", "утасныдугаар", "гарутас", "phonenumber"},
    {"username", "login", "user", "хэрэглэгчийннэр", "нэвтрэхнэр"},
    {"firstname", "name", "нэр", "fname", "givenname"},
    {"lastname", "surname", "овог", "lname", "familyname"},
    {"search", "q", "query", "хайх", "хайлт", "хайлтынүг", "keyword"},
    {"address", "хаяг"},
    {"register", "регистр", "регистрийндугаар"},
    {"birthday", "birthdate", "dob", "төрсөнөдөр"},
]


def _key(text):
    return re.sub(r"[\s_\-.*:]+", "", (text or "").lower())


def _synonym_group(key):
    for group in SYNONYMS:
        if key in group:
            return group
    return {key}


def suggest_column(field, columns):
    """Талбарын нэр/label/placeholder/id-ээс файлын аль баганатай таарахыг таана."""
    candidates = [field.get(k, "") for k in ("label", "name", "id", "placeholder")]
    keys = [_key(c) for c in candidates if c]
    column_keys = {_key(c): c for c in columns}
    for key in keys:  # яг таарсан
        if key in column_keys:
            return column_keys[key]
    for key in keys:  # ижил утгатай үг
        for synonym in _synonym_group(key):
            if synonym in column_keys:
                return column_keys[synonym]
    return ""


def suggest_mapping(fields, columns):
    """PageScan-ийн талбарууд дээр source/value санал нэмнэ (checkbox → үргэлж чагтлах)."""
    mapped = []
    used = set()
    for field in fields:
        item = dict(field)
        if field.get("in_main_form") is False:
            item.update(source="skip", value="")
            mapped.append(item)
            continue
        column = suggest_column(field, [c for c in columns if c not in used])
        if column:
            item.update(source="column", value=column)
            used.add(column)
        elif field.get("kind") == "checkbox" and field.get("required"):
            item.update(source="check", value="")
        else:
            item.update(source="skip", value="")
        mapped.append(item)
    return mapped
