from django.test import TestCase
from django.urls import reverse

from apps.autotest import generator
from apps.autotest.datafiles import read_rows
from apps.autotest.models import DataFile, PageScan
from apps.tickets.permissions import ROLE_QA
from apps.tickets.tests.helpers import make_user

from .helpers import TempMediaMixin, make_setup

SCAN_FIELDS = [
    {"label": "Имэйл хаяг", "selector": "#email", "kind": "email", "type": "email", "required": True},
    {"label": "Нууц үг", "selector": "#pw", "kind": "password", "type": "password", "required": True,
     "minlength": 8},
    {"label": "Тайлбар", "selector": "#note", "kind": "text", "type": "textarea", "maxlength": 50},
    {"label": "Нас", "selector": "#age", "kind": "text", "type": "number", "min": 18, "max": 99},
    {"label": "Хүйс", "selector": "#male", "kind": "radio", "type": "radio"},
    {"label": "Нөхцөл", "selector": "#terms", "kind": "checkbox", "type": "checkbox", "required": True},
    {"label": "language", "selector": "select[name=language]", "kind": "select", "type": "select",
     "options": ["Монгол", "English"], "in_main_form": False},
]


class DependentSelectTests(TestCase):
    """Ticket-ийн маягт шиг: ангилал сонгоход л идэвхждэг дэд ангилал, утгагүй "---------" сонголт."""

    FIELDS = [
        {"label": "Гарчиг", "selector": "#title", "kind": "text", "type": "text", "required": True},
        {"label": "Ангилал", "selector": "#cat", "kind": "select", "type": "select", "required": True,
         "has_empty_option": True, "options": ["Backend API", "Mobile апп"]},
        {"label": "Дэд ангилал", "selector": "#sub", "kind": "select", "type": "select", "disabled": True,
         "has_empty_option": True, "options": []},
    ]

    def test_long_label_column_has_no_trailing_space(self):
        """60 тэмдэгтээр тасалсны дараа зай үлдвэл файлаас уншихад нэр таарахгүй болж талбар алгасагдана."""
        label = "Алдааны хувьд: давтах алхам, хүлээгдэж буй үр дүн, бодит үр дүн, орчин"
        self.assertEqual(label[:60][-1], " ")
        columns, _rows, mapping = generator.generate([{"label": label, "selector": "#d", "kind": "text", "type": "textarea"}])
        self.assertEqual(mapping["#d"], label[:60].strip())
        self.assertIn(label[:60].strip(), columns)

    def test_disabled_select_is_left_empty_and_not_broken(self):
        columns, rows, _mapping = generator.generate(self.FIELDS)
        by_description = {row[0]: dict(zip(columns, row)) for row in rows}
        valid = by_description["Бүх талбар зөв"]
        self.assertEqual((valid["Ангилал"], valid["Дэд ангилал"]), ("Backend API", ""))
        self.assertIn("Ангилал: сонгоогүй", by_description)
        self.assertFalse([d for d in by_description if d.startswith("Дэд ангилал")])


class GeneratorTests(TestCase):
    def setUp(self):
        self.columns, self.rows, self.mapping = generator.generate(SCAN_FIELDS)
        self.by_description = {row[0]: dict(zip(self.columns, row)) for row in self.rows}

    def test_columns_skip_radio_and_avoid_reserved_names(self):
        self.assertEqual(self.columns, ["Тайлбар", "Имэйл хаяг", "Нууц үг", "Тайлбар 2", "Нас", "Нөхцөл", "хүлээгдэх"])
        self.assertNotIn("#male", self.mapping)
        self.assertNotIn("select[name=language]", self.mapping)
        self.assertEqual(self.mapping["#note"], "Тайлбар 2")

    def test_first_row_is_all_valid(self):
        valid = self.by_description["Бүх талбар зөв"]
        self.assertEqual(valid["хүлээгдэх"], "амжилттай")
        self.assertEqual(valid["Имэйл хаяг"], "qa{{run}}@example.com")
        self.assertGreaterEqual(len(valid["Нууц үг"]), 8)
        self.assertEqual((valid["Нас"], valid["Нөхцөл"]), ("18", "тийм"))
        self.assertLessEqual(len(valid["Тайлбар 2"]), 50)

    def test_each_row_breaks_one_field(self):
        row = self.by_description["Имэйл хаяг: буруу формат"]
        self.assertEqual((row["Имэйл хаяг"], row["хүлээгдэх"]), ("abc@@mail", "алдаа"))
        self.assertEqual(row["Нууц үг"], self.by_description["Бүх талбар зөв"]["Нууц үг"])
        self.assertEqual(self.by_description["Нууц үг: богино (8-аас бага тэмдэгт)"]["хүлээгдэх"], "алдаа")
        self.assertEqual(self.by_description["Нас: хамгийн багаас бага"]["Нас"], "17")
        self.assertEqual(self.by_description["Нас: хамгийн ихээс их"]["Нас"], "100")
        self.assertEqual(self.by_description["Нөхцөл: чагтлаагүй"]["Нөхцөл"], "үгүй")

    def test_unpredictable_rows_have_blank_expectation(self):
        self.assertEqual(self.by_description["Тайлбар 2: хэт урт (55 тэмдэгт)"]["хүлээгдэх"], "")
        self.assertEqual(self.by_description["Тайлбар 2: XSS"]["Тайлбар 2"], generator.XSS)
        self.assertEqual(self.by_description["Имэйл хаяг: SQL injection"]["хүлээгдэх"], "")
        self.assertNotIn("Нууц үг: SQL injection", self.by_description)


REGISTER_FIELDS = [
    {"label": "Имэйл", "selector": "#email", "kind": "email", "type": "email", "required": True},
    {"label": "Хэрэглэгчийн нэр", "selector": "#username", "kind": "text", "type": "text", "maxlength": 20},
    {"label": "Утас", "selector": "#phone", "kind": "text", "type": "tel"},
    {"label": "Нууц үг", "selector": "#pw", "kind": "password", "type": "password", "required": True,
     "minlength": 8},
    {"label": "Нууц үг давтах", "selector": "#pw2", "kind": "password", "type": "password", "required": True},
]
REGISTER_VALUES = {"#email": "bold@mail.mn", "#username": "bold", "#phone": "88112233",
                   "#pw": "Secret#123", "#pw2": "Secret#123"}
LOGIN_FIELDS = [
    {"label": "Хэрэглэгчийн нэр", "selector": "#u", "kind": "text", "type": "text", "required": True},
    {"label": "Нууц үг", "selector": "#p", "kind": "password", "type": "password", "required": True},
    {"label": "Намайг сана", "selector": "#remember", "kind": "checkbox", "type": "checkbox"},
]


def _rows_by_description(fields, values, login=None):
    columns, rows, _mapping = generator.generate(fields, values, login)
    return columns, [dict(zip(columns, row)) for row in rows]


class BaseRowTests(TestCase):
    """Бүртгэлийн форм: QA-н утгаас гаргаж, мөр бүрт яг нэг зүйл өөрчлөгдөнө."""

    def setUp(self):
        _columns, self.rows = _rows_by_description(REGISTER_FIELDS, REGISTER_VALUES)
        self.by = {row["Тайлбар"]: row for row in self.rows}
        self.first = self.rows[0]

    def test_first_row_uses_qa_values_made_unique(self):
        self.assertEqual(self.first["Тайлбар"], "Бүх талбар зөв")
        self.assertEqual(self.first["Имэйл"], "bold{{run}}@mail.mn")
        self.assertEqual(self.first["Хэрэглэгчийн нэр"], "bold{{run}}")
        self.assertEqual(self.first["Утас"], "88{{digits}}")
        self.assertEqual((self.first["Нууц үг"], self.first["Нууц үг давтах"]), ("Secret#123", "Secret#123"))

    def test_other_rows_get_their_own_unique_values(self):
        row = self.by["Нууц үг: хоосон"]
        self.assertEqual(row["Имэйл"], "bold{{run}}{{row}}@mail.mn")
        self.assertEqual(row["Хэрэглэгчийн нэр"], "bold{{run}}{{row}}")

    def test_unique_token_fits_maxlength(self):
        values = dict(REGISTER_VALUES, **{"#username": "a_very_long_username"})
        _columns, rows = _rows_by_description(REGISTER_FIELDS, values)
        self.assertEqual(rows[0]["Хэрэглэгчийн нэр"], "a_very{{run}}")  # 6 + 14 = 20

    def test_password_rules_are_checked_with_matching_confirm(self):
        row = self.by["Нууц үг: богино (8-аас бага тэмдэгт)"]
        self.assertEqual(row["Нууц үг"], "Secret#")
        self.assertEqual(row["Нууц үг давтах"], "Secret#")
        mismatch = self.by["Нууц үг давтах: таарахгүй"]
        self.assertEqual((mismatch["Нууц үг"], mismatch["хүлээгдэх"]), ("Secret#123", "алдаа"))
        self.assertNotEqual(mismatch["Нууц үг давтах"], "Secret#123")
        self.assertNotIn("Нууц үг давтах: хэт урт (300 тэмдэгт)", self.by)

    def test_duplicate_rows_repeat_first_row_value(self):
        email = self.by["Имэйл: давхардсан (1-р мөртэй ижил)"]
        self.assertEqual(email["Имэйл"], self.first["Имэйл"])
        self.assertEqual(email["Хэрэглэгчийн нэр"], "bold{{run}}{{row}}")
        self.assertEqual(email["хүлээгдэх"], "алдаа")
        self.assertIn("Хэрэглэгчийн нэр: давхардсан (1-р мөртэй ижил)", self.by)

    def test_each_row_changes_only_one_field(self):
        reference = {"Имэйл": "bold{{run}}{{row}}@mail.mn", "Хэрэглэгчийн нэр": "bold{{run}}{{row}}",
                     "Утас": "88{{digits}}", "Нууц үг": "Secret#123"}
        for row in self.rows[1:]:
            changed = [c for c in ("Имэйл", "Хэрэглэгчийн нэр", "Утас", "Нууц үг") if row[c] != reference[c]]
            if row["Тайлбар"].startswith("Нууц үг:") or row["Тайлбар"].startswith("Нууц үг давтах"):
                changed = [c for c in changed if c != "Нууц үг"]
            self.assertLessEqual(len(changed), 1, row["Тайлбар"])

    def test_qa_tokens_are_kept(self):
        values = dict(REGISTER_VALUES, **{"#email": "x{{random}}@mail.mn"})
        _columns, rows = _rows_by_description(REGISTER_FIELDS, values)
        self.assertEqual(rows[0]["Имэйл"], "x{{random}}@mail.mn")
        self.assertFalse(any(r["Тайлбар"] == "Имэйл: давхардсан (1-р мөртэй ижил)" for r in rows))

    def test_rejects_missing_required_and_mismatched_passwords(self):
        with self.assertRaises(generator.GenerateError):
            generator.generate(REGISTER_FIELDS, dict(REGISTER_VALUES, **{"#email": " "}))
        with self.assertRaises(generator.GenerateError):
            generator.generate(REGISTER_FIELDS, dict(REGISTER_VALUES, **{"#pw2": "other"}))


class LoginRowTests(TestCase):
    def setUp(self):
        _columns, self.rows = _rows_by_description(LOGIN_FIELDS, {"#u": "pm", "#p": " Pass word1", "#remember": "үгүй"})
        self.by = {row["Тайлбар"]: row for row in self.rows}

    def test_detects_login_form(self):
        form = generator.generate_form(LOGIN_FIELDS)
        self.assertTrue(form["login"])
        self.assertEqual([f["value"] for f in form["fields"]], ["", "", "тийм"])
        self.assertFalse(generator.generate_form(REGISTER_FIELDS)["login"])

    def test_real_account_is_the_base_and_password_spaces_kept(self):
        first = self.rows[0]
        self.assertEqual((first["Хэрэглэгчийн нэр"], first["Нууц үг"], first["хүлээгдэх"]), ("pm", " Pass word1", "амжилттай"))
        wrong = self.by["Нууц үг: буруу"]
        self.assertEqual(wrong["Хэрэглэгчийн нэр"], "pm")
        self.assertEqual(len(wrong["Нууц үг"]), len(" Pass word1"))
        self.assertNotEqual(wrong["Нууц үг"], " Pass word1")
        self.assertEqual(self.by["Нууц үг: том/жижиг үсэг солисон"]["Нууц үг"], " pASS WORD1")

    def test_attempts_on_real_account_never_exceed_two_in_a_row(self):
        run = 0
        for row in self.rows:
            if row["хүлээгдэх"] == "амжилттай":
                run = 0
            elif row["Хэрэглэгчийн нэр"].strip().lower() == "pm":
                run += 1
                self.assertLessEqual(run, 2, row["Тайлбар"])
        self.assertIn("Бүх талбар зөв (дахин нэвтрэх)", self.by)

    def test_other_user_rows_are_errors_and_case_rows_need_review(self):
        self.assertEqual(self.by["Хэрэглэгчийн нэр: бүртгэлгүй хэрэглэгч"]["Хэрэглэгчийн нэр"], "nouser{{run}}{{row}}")
        self.assertEqual(self.by["Хэрэглэгчийн нэр: SQL тайлбар (нэр' --)"]["Хэрэглэгчийн нэр"], "pm' --")
        self.assertEqual(self.by["Хэрэглэгчийн нэр: том/жижиг үсэг солисон"]["хүлээгдэх"], "")
        self.assertEqual(self.by["Хэрэглэгчийн нэр: урд, хойно зайтай"]["хүлээгдэх"], "")
        blank = {r["Тайлбар"] for r in self.rows if r["хүлээгдэх"] == ""}
        self.assertEqual(blank, {"Хэрэглэгчийн нэр: том/жижиг үсэг солисон", "Хэрэглэгчийн нэр: урд, хойно зайтай"})

    def test_login_needs_credentials(self):
        with self.assertRaises(generator.GenerateError):
            generator.generate(LOGIN_FIELDS, {"#u": "pm", "#p": ""})
        with self.assertRaises(generator.GenerateError):
            generator.generate(REGISTER_FIELDS, REGISTER_VALUES, login=True)


class GenerateViewTests(TempMediaMixin, TestCase):
    def setUp(self):
        self.app, _env, _scenario, _file = make_setup()
        self.qa = make_user("qa", ROLE_QA)
        self.client.force_login(self.qa)
        self.scan = PageScan.objects.create(url="https://staging.example.com/register", requested_by=self.qa,
                                            status=PageScan.Status.DONE, result={"fields": SCAN_FIELDS})

    def test_creates_readable_data_file(self):
        response = self.client.post(reverse("autotest:scan_generate", args=[self.app.pk, self.scan.pk]),
                                    {"name": "Бүртгүүлэх"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        data_file = DataFile.objects.get(pk=data["id"])
        self.assertEqual(data_file.category, self.app.category)
        self.assertEqual(data_file.name, "Бүртгүүлэх — автомат өгөгдөл")
        self.assertEqual(data["mapping"]["#email"], "Имэйл хаяг")
        self.assertEqual(data["expected_column"], "хүлээгдэх")
        with data_file.file.open("rb") as fh:
            columns, rows = read_rows(fh, data_file.file.name)
        self.assertEqual(columns, data_file.columns)
        self.assertEqual(len(rows), data_file.row_count)
        self.assertEqual(rows[0][1]["Тайлбар"], "Бүх талбар зөв")

    def test_uses_posted_values_and_reports_errors(self):
        import json

        scan = PageScan.objects.create(url="https://staging.example.com/login", requested_by=self.qa,
                                       status=PageScan.Status.DONE, result={"fields": LOGIN_FIELDS})
        url = reverse("autotest:scan_generate", args=[self.app.pk, scan.pk])
        response = self.client.post(url, {"values": json.dumps({"#u": "pm", "#p": ""}), "login": "1"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Нууц үг", response.json()["error"])
        response = self.client.post(url, {"values": json.dumps({"#u": "pm", "#p": "pw"}), "login": "1"})
        data_file = DataFile.objects.get(pk=response.json()["id"])
        with data_file.file.open("rb") as fh:
            _columns, rows = read_rows(fh, data_file.file.name)
        self.assertEqual(rows[0][1]["Хэрэглэгчийн нэр"], "pm")

    def test_only_own_finished_scan(self):
        other = PageScan.objects.create(url="https://staging.example.com/x", requested_by=make_user("qa2", ROLE_QA),
                                        status=PageScan.Status.DONE, result={"fields": SCAN_FIELDS})
        response = self.client.post(reverse("autotest:scan_generate", args=[self.app.pk, other.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertFalse(DataFile.objects.filter(name__contains="автомат").exists())

    def test_developer_cannot_generate(self):
        from apps.tickets.permissions import ROLE_DEV

        self.client.force_login(make_user("dev", ROLE_DEV))
        self.client.post(reverse("autotest:scan_generate", args=[self.app.pk, self.scan.pk]))
        self.assertFalse(DataFile.objects.filter(name__contains="автомат").exists())
