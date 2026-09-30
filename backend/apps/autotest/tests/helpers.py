"""Автомат тестийн тестүүдэд ашиглагдах туслах функцууд."""
import shutil
import tempfile
from io import BytesIO
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook

from apps.autotest.models import DataFile, Environment, Page, RunResult, Scenario, TestApp
from apps.categories.models import Category
from apps.tickets.models import Attachment

REGISTER_FIELDS = [
    {"label": "Имэйл", "selector": "#email", "kind": "email", "source": "column", "value": "email"},
    {"label": "Нууц үг", "selector": "#password", "kind": "password", "source": "column", "value": "password"},
    {"label": "Зөвшөөрөх", "selector": "#terms", "kind": "checkbox", "source": "check", "value": ""},
]


def xlsx_upload(rows, name="users.xlsx"):
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return SimpleUploadedFile(name, buffer.getvalue())


def csv_upload(text, name="users.csv"):
    return SimpleUploadedFile(name, text.encode("utf-8"))


class TempMediaMixin:
    """Тестийн үед хадгалагдах файлуудыг (өгөгдлийн файл, screenshot) түр хавтас руу чиглүүлнэ."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._media_dir = tempfile.mkdtemp()
        cls._patches = []
        for model, field in ((DataFile, "file"), (RunResult, "screenshot"), (Attachment, "file")):
            storage = model._meta.get_field(field).storage
            for attr in ("base_location", "location"):
                patcher = mock.patch.object(storage, attr, cls._media_dir, create=True)
                patcher.start()
                cls._patches.append(patcher)

    @classmethod
    def tearDownClass(cls):
        for patcher in cls._patches:
            patcher.stop()
        shutil.rmtree(cls._media_dir, ignore_errors=True)
        super().tearDownClass()


def make_category():
    return Category.objects.create(name=f"Web {Category.objects.count() + 1}")


def make_setup(base_url="https://staging.example.com", fields=None, rows=None, category=None):
    """Апп + орчин + хуудас + сценари + өгөгдлийн файлыг бэлдэнэ."""
    category = category or make_category()
    app = TestApp.objects.create(category=category, name="Shop")
    env = Environment.objects.create(app=app, name="staging", base_url=base_url)
    page = Page.objects.create(app=app, name="Бүртгүүлэх", path="/register")
    scenario = Scenario.objects.create(
        app=app, name="Бүртгүүлэх", page=page,
        fields=fields if fields is not None else REGISTER_FIELDS,
        expected_column="хүлээгдэх",
    )
    rows = rows or [
        ["Тайлбар", "email", "password", "хүлээгдэх"],
        ["Зөв", "a@mail.mn", "Pass1234", "амжилттай"],
    ]
    upload = xlsx_upload(rows)
    data_file = DataFile(category=category, name="users", columns=rows[0], row_count=len(rows) - 1)
    data_file.file.save(upload.name, upload, save=True)
    return app, env, scenario, data_file
