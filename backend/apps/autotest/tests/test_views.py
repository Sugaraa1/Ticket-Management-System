import json
from io import BytesIO

from django.core.files.base import ContentFile
from django.test import TestCase
from django.urls import reverse
from openpyxl import load_workbook

from apps.autotest.models import DataFile, PageScan, RunResult, Scenario, TestApp, TestRun
from apps.projects.models import Project
from apps.tickets.models import Ticket
from apps.tickets.permissions import ROLE_DEV, ROLE_PM, ROLE_QA
from apps.tickets.tests.helpers import make_project, make_routed_category, make_user

from .helpers import REGISTER_FIELDS, TempMediaMixin, make_setup, xlsx_upload


class PermissionTests(TempMediaMixin, TestCase):
    def setUp(self):
        self.app, self.env, self.scenario, self.data_file = make_setup()

    def test_developer_sees_results_but_cannot_run(self):
        self.client.force_login(make_user("dev", ROLE_DEV))
        self.assertEqual(self.client.get(reverse("autotest:home")).status_code, 200)
        self.assertEqual(self.client.get(reverse("autotest:scenario_detail", args=[self.scenario.pk])).status_code, 200)
        self.client.post(reverse("autotest:run_create", args=[self.scenario.pk]),
                         {"data_file": self.data_file.pk, "environment": self.env.pk})
        self.assertFalse(TestRun.objects.exists())

    def test_qa_cannot_register_apps_but_can_create_scenarios(self):
        self.client.force_login(make_user("qa", ROLE_QA))
        self.client.post(reverse("autotest:app_create"), {"project": self.app.project_id, "name": "Other"})
        self.assertFalse(TestApp.objects.filter(name="Other").exists())
        response = self.client.get(reverse("autotest:scenario_create", args=[self.app.pk]))
        self.assertEqual(response.status_code, 200)

    def test_nav_link_visible_to_roles(self):
        self.client.force_login(make_user("dev", ROLE_DEV))
        self.assertContains(self.client.get(reverse("tickets:ticket_list")), reverse("autotest:home"))


class DataFileViewTests(TempMediaMixin, TestCase):
    def setUp(self):
        self.project = make_project()
        self.client.force_login(make_user("qa", ROLE_QA))

    def test_upload_reads_columns_and_rows(self):
        upload = xlsx_upload([["email", "password"], ["a@mail.mn", "x"], ["b@mail.mn", "y"]])
        response = self.client.post(reverse("autotest:datafile_create"), {"project": self.project.pk, "file": upload})
        data_file = DataFile.objects.get()
        self.assertRedirects(response, reverse("autotest:datafile_detail", args=[data_file.pk]))
        self.assertEqual(data_file.name, "users")
        self.assertEqual(data_file.columns, ["email", "password"])
        self.assertEqual(data_file.row_count, 2)
        detail = self.client.get(reverse("autotest:datafile_detail", args=[data_file.pk]))
        self.assertContains(detail, "b@mail.mn")

    def test_broken_file_shows_error(self):
        upload = xlsx_upload([["email", "email"], ["a", "b"]])
        response = self.client.post(reverse("autotest:datafile_create"), {"project": self.project.pk, "file": upload})
        self.assertContains(response, "Давхардсан")
        self.assertFalse(DataFile.objects.exists())

    def test_detail_lists_compatible_scenarios(self):
        _app, _env, scenario, data_file = make_setup(project=self.project)
        Scenario.objects.create(app=scenario.app, name="Утас", page_path="/p",
                                fields=[{"label": "Утас", "selector": "#p", "source": "column", "value": "phone"}])
        response = self.client.get(reverse("autotest:datafile_detail", args=[data_file.pk]))
        self.assertContains(response, "Бэлэн")
        self.assertContains(response, "Дутуу багана:")

    def test_template_download(self):
        response = self.client.get(reverse("autotest:template_download"))
        sheet = load_workbook(BytesIO(response.content)).worksheets[0]
        self.assertEqual(sheet["B1"].value, "email")


class ScenarioViewTests(TempMediaMixin, TestCase):
    def setUp(self):
        self.app, self.env, _scenario, _file = make_setup()
        self.client.force_login(make_user("qa", ROLE_QA))

    def _post(self, fields, **extra):
        data = {"name": "Нэвтрэх", "page_path": "/login", "success_mode": "auto", "fields_json": json.dumps(fields)}
        data.update(extra)
        return self.client.post(reverse("autotest:scenario_create", args=[self.app.pk]), data)

    def test_create_saves_field_mapping(self):
        response = self._post(REGISTER_FIELDS, submit_selector="#go", submit_label="Нэвтрэх")
        scenario = Scenario.objects.get(name="Нэвтрэх")
        self.assertRedirects(response, reverse("autotest:scenario_detail", args=[scenario.pk]))
        self.assertEqual([f["source"] for f in scenario.fields], ["column", "column", "check"])
        self.assertEqual(scenario.required_columns(), ["email", "password"])
        self.assertEqual(scenario.secret_columns(), {"password"})

    def test_requires_at_least_one_field(self):
        response = self._post([{"label": "x", "selector": "#x", "source": "skip"}])
        self.assertContains(response, "Дор хаяж нэг талбар")

    def test_column_source_needs_column_name(self):
        response = self._post([{"label": "Имэйл", "selector": "#e", "source": "column", "value": ""}])
        self.assertContains(response, "багана сонгоогүй")

    def test_scan_is_queued_and_only_owner_can_read_it(self):
        response = self.client.post(reverse("autotest:scan_create", args=[self.app.pk]),
                                    {"environment": self.env.pk, "page_path": "/register"})
        scan = PageScan.objects.get(pk=response.json()["id"])
        self.assertEqual(scan.url, "https://staging.example.com/register")
        scan.status = PageScan.Status.DONE
        scan.result = {"fields": [{"label": "Имэйл", "selector": "#email", "kind": "email"}], "buttons": []}
        scan.save()
        data = self.client.get(reverse("autotest:scan_status", args=[scan.pk]),
                               {"data_file": DataFile.objects.get().pk}).json()
        self.assertEqual((data["fields"][0]["source"], data["fields"][0]["value"]), ("column", "email"))

        self.client.force_login(make_user("qa2", ROLE_QA))
        self.assertEqual(self.client.get(reverse("autotest:scan_status", args=[scan.pk])).status_code, 404)


class RunViewTests(TempMediaMixin, TestCase):
    def setUp(self):
        self.app, self.env, self.scenario, self.data_file = make_setup()
        self.qa = make_user("qa", ROLE_QA)
        self.client.force_login(self.qa)

    def test_run_is_queued_with_snapshot(self):
        response = self.client.post(reverse("autotest:run_create", args=[self.scenario.pk]),
                                    {"data_file": self.data_file.pk, "environment": self.env.pk})
        run = TestRun.objects.get()
        self.assertRedirects(response, reverse("autotest:run_detail", args=[run.pk]))
        self.assertEqual(run.status, TestRun.Status.QUEUED)
        self.assertEqual(run.target_url, "https://staging.example.com/register")
        self.assertEqual((run.data_file_name, run.environment_name, run.total), ("users", "staging", 1))

    def test_missing_columns_block_the_run(self):
        self.scenario.expected_message_column = "мессеж"
        self.scenario.save()
        self.client.post(reverse("autotest:run_create", args=[self.scenario.pk]),
                         {"data_file": self.data_file.pk, "environment": self.env.pk})
        self.assertFalse(TestRun.objects.exists())

    def _finished_run(self):
        run = TestRun.objects.create(
            scenario=self.scenario, data_file=self.data_file, environment=self.env,
            data_file_name="users", environment_name="staging", target_url="https://staging.example.com/register",
            status=TestRun.Status.DONE, total=2, passed=1, failed=1, started_by=self.qa,
        )
        RunResult.objects.create(run=run, row_number=2, description="Зөв", verdict="pass",
                                 input_data={"email": "a@mail.mn", "password": "***"},
                                 expected_outcome="success", actual_outcome="success")
        failed = RunResult(run=run, row_number=3, description="Давхардсан имэйл", verdict="fail",
                           input_data={"email": "=HYPERLINK(1)", "password": "***"},
                           expected_outcome="error", actual_outcome="success", actual_message="Тавтай морил")
        failed.screenshot.save("shot.png", ContentFile(b"\x89PNG fake"), save=False)
        failed.save()
        return run, failed

    def test_status_json_and_failed_filter(self):
        run, _failed = self._finished_run()
        data = self.client.get(reverse("autotest:run_status", args=[run.pk]), {"show": "failed"}).json()
        self.assertEqual((data["passed"], data["failed"], data["active"]), (1, 1, False))
        self.assertIn("Давхардсан имэйл", data["html"])
        self.assertNotIn("a@mail.mn", data["html"])

    def test_export_escapes_formulas(self):
        run, _failed = self._finished_run()
        response = self.client.get(reverse("autotest:run_export", args=[run.pk]))
        sheet = load_workbook(BytesIO(response.content)).worksheets[0]
        values = [cell.value for row in sheet.iter_rows() for cell in row]
        self.assertIn("'=HYPERLINK(1)", values)
        self.assertIn("Унасан", values)

    def test_bug_ticket_prefilled_then_linked_with_screenshot(self):
        run, failed = self._finished_run()
        url = reverse("autotest:bug_ticket", args=[run.pk]) + f"?ids={failed.pk}"
        response = self.client.get(url)
        self.assertContains(response, "[Автомат тест] Бүртгүүлэх: Давхардсан имэйл")
        self.assertContains(response, "Тавтай морил")

        category, _team = make_routed_category()
        form = response.context["form"]
        response = self.client.post(url, {
            "title": form.initial["title"], "description": form.initial["description"],
            "ticket_type": "bug", "priority": "medium", "category": category.pk,
            "project": self.app.project_id,
        })
        ticket = Ticket.objects.get()
        self.assertRedirects(response, reverse("tickets:ticket_detail", args=[ticket.pk]))
        failed.refresh_from_db()
        self.assertEqual(failed.ticket, ticket)
        self.assertEqual(ticket.attachments.count(), 1)

    def test_bug_ticket_ignores_passed_rows(self):
        run, _failed = self._finished_run()
        passed = run.results.get(verdict="pass")
        response = self.client.get(reverse("autotest:bug_ticket", args=[run.pk]) + f"?ids={passed.pk}")
        self.assertRedirects(response, reverse("autotest:run_detail", args=[run.pk]))

    def test_cancel_and_rerun(self):
        run, _failed = self._finished_run()
        self.client.post(reverse("autotest:run_rerun", args=[run.pk]))
        new_run = TestRun.objects.exclude(pk=run.pk).get()
        self.assertEqual(new_run.status, TestRun.Status.QUEUED)
        self.client.post(reverse("autotest:run_cancel", args=[new_run.pk]))
        new_run.refresh_from_db()
        self.assertEqual(new_run.status, TestRun.Status.CANCELLED)


class ProjectDeleteTests(TempMediaMixin, TestCase):
    def test_project_with_tests_is_deactivated_not_deleted(self):
        app, *_ = make_setup()
        self.client.force_login(make_user("pm", ROLE_PM))
        self.client.post(reverse("projects:project_delete", args=[app.project_id]))
        project = Project.objects.get(pk=app.project_id)
        self.assertFalse(project.is_active)


class PagesRenderTests(TempMediaMixin, TestCase):
    def test_every_page_renders(self):
        app, _env, scenario, data_file = make_setup()
        run = TestRun.objects.create(
            scenario=scenario, data_file=data_file, environment=_env, data_file_name="users",
            environment_name="staging", target_url="https://staging.example.com/register", total=1,
        )
        self.client.force_login(make_user("pm", ROLE_PM))
        for url in [
            reverse("autotest:home"),
            reverse("autotest:app_create"),
            reverse("autotest:app_detail", args=[app.pk]),
            reverse("autotest:datafile_list"),
            reverse("autotest:datafile_create"),
            reverse("autotest:datafile_detail", args=[data_file.pk]),
            reverse("autotest:scenario_create", args=[app.pk]),
            reverse("autotest:scenario_edit", args=[scenario.pk]),
            reverse("autotest:scenario_detail", args=[scenario.pk]),
            reverse("autotest:run_detail", args=[run.pk]),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
