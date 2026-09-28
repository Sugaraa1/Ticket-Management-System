"""
Автомат тест (data-driven): QA өгөгдлийн файл (Excel/CSV) бэлдээд, шалгах апп-ын
хуудсан дээр мөр бүрийг browser-оор бөглүүлж, үр дүнг хүлээгдэх үр дүнтэй тулгана.

    TestApp ─ Environment (dev/staging... base URL)
            └ Scenario (хуудас, талбар ↔ баганын холбоос, амжилтын нөхцөл)
    DataFile (project-д харьяалагдах, олон сценарид дахин ашиглагдана)
    TestRun (сценари + файл + орчин) └ RunResult (мөр бүрийн үр дүн)
    PageScan — сценари тохируулахад хуудасны талбаруудыг олох түр ажил

Browser ажиллуулах бүх ажлыг (TestRun, PageScan) `run_autotest_worker` процесс
DB-ийн дарааллаас авч гүйцэтгэнэ — вэб серверт Chromium шаардлагагүй.
"""
from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel
from apps.projects.models import Project
from apps.tickets.storage import private_storage


class TestApp(TimeStampedModel):
    project = models.ForeignKey(Project, related_name="test_apps", on_delete=models.PROTECT)
    name = models.CharField(_("Нэр"), max_length=150)
    description = models.TextField(_("Тайлбар"), blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["project", "name"], name="autotest_unique_app_name"),
        ]

    def __str__(self):
        return self.name


class Environment(models.Model):
    app = models.ForeignKey(TestApp, related_name="environments", on_delete=models.CASCADE)
    name = models.CharField(_("Орчин"), max_length=50, help_text=_("Жишээ: dev, staging"))
    base_url = models.URLField(_("Үндсэн хаяг"), help_text=_("Жишээ: https://staging.shop.mn"))

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["app", "name"], name="autotest_unique_env_name"),
        ]

    def __str__(self):
        return f"{self.app.name} · {self.name}"

    def url_for(self, path):
        path = (path or "").strip()
        if path.startswith(("http://", "https://")):
            return path
        return self.base_url.rstrip("/") + "/" + path.lstrip("/")


class DataFile(TimeStampedModel):
    project = models.ForeignKey(Project, related_name="test_data_files", on_delete=models.PROTECT)
    name = models.CharField(_("Нэр"), max_length=150)
    file = models.FileField(upload_to="autotest/data/%Y/%m/", storage=private_storage)
    columns = models.JSONField(default=list)
    row_count = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.name


class Scenario(TimeStampedModel):
    class SuccessMode(models.TextChoices):
        AUTO = "auto", _("Автоматаар (хуудас шилжсэн, алдааны мессеж гараагүй)")
        URL_CONTAINS = "url_contains", _("Хаяг (URL) нь дараах текстийг агуулсан")
        TEXT_VISIBLE = "text_visible", _("Хуудсанд дараах текст гарсан")

    app = models.ForeignKey(TestApp, related_name="scenarios", on_delete=models.CASCADE)
    name = models.CharField(_("Нэр"), max_length=150, help_text=_("Жишээ: Бүртгүүлэх, Нэвтрэх"))
    page_path = models.CharField(
        _("Хуудас"), max_length=500, help_text=_("Орчны үндсэн хаягаас хойших зам. Жишээ: /register")
    )
    # [{"label", "selector", "kind", "source": "column|constant|check|skip", "value"}]
    fields = models.JSONField(default=list)
    submit_selector = models.CharField(max_length=500, blank=True)
    submit_label = models.CharField(max_length=200, blank=True)
    success_mode = models.CharField(
        _("Амжилттай гэж үзэх нөхцөл"), max_length=20, choices=SuccessMode.choices, default=SuccessMode.AUTO
    )
    success_value = models.CharField(_("Нөхцөлийн текст"), max_length=300, blank=True)
    error_selector = models.CharField(
        _("Алдааны мессежийн элемент"), max_length=300, blank=True,
        help_text=_("Хоосон бол түгээмэл алдааны элементүүдийг (.error, [role=alert] ...) автоматаар хайна."),
    )
    expected_column = models.CharField(
        _("Хүлээгдэх үр дүнгийн багана"), max_length=150, blank=True,
        help_text=_("'амжилттай' / 'алдаа' эсвэл 'алдаа: мессеж' гэж бичсэн багана. Хоосон бол зөвхөн тэмдэглэнэ."),
    )
    expected_message_column = models.CharField(
        _("Хүлээгдэх мессежийн багана"), max_length=150, blank=True
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.app.name} · {self.name}"

    def required_columns(self):
        """Файлд заавал байх ёстой баганууд (талбарт холбосон + хүлээгдэх)."""
        cols = [f["value"] for f in self.fields if f.get("source") == "column" and f.get("value")]
        cols += [c for c in (self.expected_column, self.expected_message_column) if c]
        return list(dict.fromkeys(cols))

    def missing_columns(self, data_file):
        present = set(data_file.columns)
        return [c for c in self.required_columns() if c not in present]

    def secret_columns(self):
        """Нууц үгийн талбарт холбосон баганууд — үр дүнд *** гэж харагдана."""
        return {
            f["value"] for f in self.fields
            if f.get("source") == "column" and f.get("kind") == "password"
        }


class TestRun(TimeStampedModel):
    class Status(models.TextChoices):
        QUEUED = "queued", _("Дараалалд")
        RUNNING = "running", _("Ажиллаж байна")
        DONE = "done", _("Дууссан")
        FAILED = "failed", _("Алдаатай зогссон")
        CANCELLED = "cancelled", _("Цуцлагдсан")

    ACTIVE_STATUSES = (Status.QUEUED, Status.RUNNING)

    scenario = models.ForeignKey(Scenario, related_name="runs", on_delete=models.CASCADE)
    data_file = models.ForeignKey(DataFile, related_name="runs", on_delete=models.SET_NULL, null=True)
    environment = models.ForeignKey(Environment, related_name="runs", on_delete=models.SET_NULL, null=True)
    # Файл / орчин дараа нь өөрчлөгдсөн ч түүх хэвээр харагдана.
    data_file_name = models.CharField(max_length=150)
    environment_name = models.CharField(max_length=50)
    target_url = models.URLField(max_length=600)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    total = models.PositiveIntegerField(default=0)
    passed = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)
    errored = models.PositiveIntegerField(default=0)
    recorded = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"#{self.pk} {self.scenario}"

    @property
    def done_count(self):
        return self.passed + self.failed + self.errored + self.recorded

    @property
    def is_active(self):
        return self.status in self.ACTIVE_STATUSES

    @property
    def pass_rate(self):
        judged = self.passed + self.failed + self.errored
        return round(self.passed * 100 / judged) if judged else None


class RunResult(models.Model):
    class Verdict(models.TextChoices):
        PASS = "pass", _("Тэнцсэн")
        FAIL = "fail", _("Унасан")
        ERROR = "error", _("Ажиллуулж чадсангүй")
        RECORDED = "recorded", _("Тэмдэглэсэн")

    class Outcome(models.TextChoices):
        SUCCESS = "success", _("амжилттай")
        ERROR = "error", _("алдаа")
        UNKNOWN = "unknown", _("тодорхойгүй")

    run = models.ForeignKey(TestRun, related_name="results", on_delete=models.CASCADE)
    row_number = models.PositiveIntegerField()
    description = models.CharField(max_length=300, blank=True)
    input_data = models.JSONField(default=dict)
    expected_outcome = models.CharField(max_length=10, choices=Outcome.choices, blank=True)
    expected_message = models.TextField(blank=True)
    actual_outcome = models.CharField(max_length=10, choices=Outcome.choices, blank=True)
    actual_message = models.TextField(blank=True)
    final_url = models.URLField(max_length=1000, blank=True)
    verdict = models.CharField(max_length=10, choices=Verdict.choices)
    duration_ms = models.PositiveIntegerField(default=0)
    screenshot = models.FileField(upload_to="autotest/shots/%Y/%m/", storage=private_storage, blank=True)
    ticket = models.ForeignKey(
        "tickets.Ticket", related_name="autotest_results", on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        ordering = ["row_number"]

    def __str__(self):
        return f"{self.run} · row {self.row_number}"


class PageScan(TimeStampedModel):
    class Status(models.TextChoices):
        QUEUED = "queued", _("Дараалалд")
        DONE = "done", _("Дууссан")
        FAILED = "failed", _("Алдаатай")

    url = models.URLField(max_length=600)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    # {"fields": [...], "buttons": [...], "title": "..."}
    result = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+"
    )
