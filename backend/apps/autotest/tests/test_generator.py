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
        self.assertEqual(valid["Имэйл хаяг"], "qa{{timestamp}}{{row}}@example.com")
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
        self.assertEqual(data_file.project, self.app.project)
        self.assertEqual(data_file.name, "Бүртгүүлэх — автомат өгөгдөл")
        self.assertEqual(data["mapping"]["#email"], "Имэйл хаяг")
        self.assertEqual(data["expected_column"], "хүлээгдэх")
        with data_file.file.open("rb") as fh:
            columns, rows = read_rows(fh, data_file.file.name)
        self.assertEqual(columns, data_file.columns)
        self.assertEqual(len(rows), data_file.row_count)
        self.assertEqual(rows[0][1]["Тайлбар"], "Бүх талбар зөв")

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
