"""API сценари: загвар, хүлээгдэх үр дүн, жинхэнэ HTTP сервер дээр worker-ээр ажиллуулах."""
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from apps.autotest.api import check_body_template, parse_expected_api, parse_headers, render, template_columns
from apps.autotest.models import RunResult, Scenario, TestAccount, TestRun
from apps.tickets.permissions import ROLE_QA
from apps.tickets.tests.helpers import make_user

from .helpers import TempMediaMixin, make_setup


class TemplateTests(SimpleTestCase):
    def test_json_values_are_escaped_and_quotes_stay_with_the_template(self):
        body = render('{"name": "{{name}}", "age": {{age}}}', {"name": 'Бат "Б"\n', "age": "25"}, "json")
        self.assertEqual(json.loads(body), {"name": 'Бат "Б"\n', "age": 25})

    def test_url_values_are_percent_encoded(self):
        self.assertEqual(render("/api/search?q={{q}}", {"q": "a b&c"}, "url"), "/api/search?q=a%20b%26c")

    def test_columns_exclude_builtin_placeholders(self):
        self.assertEqual(
            template_columns("/u/{{ id }}", "X-Key: {{key}}", '{"e": "{{email}}{{random}}", "i": "{{id}}"}'),
            ["id", "key", "email"],
        )

    def test_body_must_be_json_once_placeholders_are_filled(self):
        check_body_template('{"age": {{age}}, "e": "{{email}}"}', [])
        with self.assertRaises(ValueError):
            check_body_template('{"age": {{age}},}', [])
        check_body_template("a={{a}}", [("Content-Type", "application/x-www-form-urlencoded")])

    def test_headers_need_name_and_colon(self):
        self.assertEqual(parse_headers("X-Key: abc\n\nAccept: */*"), [("X-Key", "abc"), ("Accept", "*/*")])
        with self.assertRaises(ValueError):
            parse_headers("just text")

    def test_expected_accepts_status_codes_and_words(self):
        self.assertEqual(parse_expected_api("201"), ("success", 201, ""))
        self.assertEqual(parse_expected_api("400: Имэйл буруу"), ("error", 400, "Имэйл буруу"))
        self.assertEqual(parse_expected_api("алдаа: x"), ("error", None, "x"))
        self.assertEqual(parse_expected_api(""), ("", None, ""))


class FakeApi(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _reply(self, status, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        data = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        if self.path == "/api/login":
            if data.get("password") == "Secret#1":
                return self._reply(200, {"data": {"access_token": "tok-123456"}})
            return self._reply(401, {"detail": "Нууц үг буруу"})
        if self.path == "/api/users":
            if self.headers.get("Authorization") != "Bearer tok-123456":
                return self._reply(401, {"detail": "Нэвтрээгүй"})
            if "@" not in data.get("email", ""):
                return self._reply(400, {"email": ["Имэйл буруу байна"]})
            return self._reply(201, {"id": 7, "email": data["email"], "age": data.get("age")})
        self._reply(404, {"detail": "Not found"})

    def do_GET(self):
        if self.path == "/old":
            self.send_response(301)
            self.send_header("Location", "/api/ping")
            self.end_headers()
            return
        self._reply(200, {"pong": True})


@override_settings(AUTOTEST_ALLOW_PRIVATE_HOSTS=True, AUTOTEST_ROW_DELAY_MS=0)
class ApiRunTests(TempMediaMixin, TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeApi)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        super().tearDownClass()

    def setUp(self):
        self.app, self.env, _web, self.data_file = make_setup(base_url=self.base_url, rows=[
            ["Тайлбар", "email", "age", "password", "хүлээгдэх"],
            ["Зөв", "a{{row}}@mail.mn", "30", "Pass#9999", "201"],
            ["Буруу имэйл", "nope", "30", "Pass#9999", "400: Имэйл буруу"],
            ["Буруу хүлээлт", "b@mail.mn", "30", "Pass#9999", "400"],
            ["Хүлээлтгүй", "c@mail.mn", "30", "Pass#9999", ""],
            ["Тоо биш", "d@mail.mn", "", "Pass#9999", "201"],
        ])
        self.app.api_login_path = "/api/login"
        self.app.save()
        self.account = TestAccount(app=self.app, label="QA", username="qa")
        self.account.set_password("Secret#1")
        self.account.save()
        self.scenario = Scenario.objects.create(
            app=self.app, kind=Scenario.Kind.API, name="Хэрэглэгч үүсгэх", account=self.account,
            api_method="POST", api_path="/api/users",
            api_body='{"email": "{{email}}", "age": {{age}}, "password": "{{password}}"}',
            expected_column="хүлээгдэх",
        )
        self.qa = make_user("qa")

    def _run(self):
        from apps.autotest.views import _queue_run

        run = _queue_run(self.scenario, self.data_file, self.env, self.qa)
        with mock.patch("apps.autotest.management.commands.run_autotest_worker.close_old_connections"):
            call_command("run_autotest_worker", once=True, stdout=open(os.devnull, "w"))
        run.refresh_from_db()
        return run

    def test_rows_are_judged_by_status_and_message(self):
        run = self._run()
        self.assertEqual(run.status, TestRun.Status.DONE, run.error_message)
        verdicts = {r.description: r for r in run.results.all()}
        self.assertEqual(verdicts["Зөв"].verdict, RunResult.Verdict.PASS, verdicts["Зөв"].actual_message)
        self.assertEqual(verdicts["Буруу имэйл"].verdict, RunResult.Verdict.PASS)
        self.assertEqual(verdicts["Буруу хүлээлт"].verdict, RunResult.Verdict.FAIL)
        self.assertEqual(verdicts["Хүлээлтгүй"].verdict, RunResult.Verdict.RECORDED)
        # age хоосон → {"age": ,} — сервер рүү эвдэрсэн JSON илгээхгүй.
        self.assertEqual(verdicts["Тоо биш"].verdict, RunResult.Verdict.ERROR)
        self.assertIn("JSON", verdicts["Тоо биш"].actual_message)

        ok = verdicts["Зөв"]
        self.assertEqual(ok.input_data["email"], "a2@mail.mn")  # {{row}} орлуулсан утга
        self.assertEqual(ok.input_data["password"], "***")
        self.assertIn("HTTP 201", ok.actual_message)
        self.assertIn("curl -X POST", ok.response_detail)
        self.assertNotIn("Pass#9999", ok.response_detail)
        self.assertNotIn("tok-123456", ok.response_detail)

    def test_wrong_login_stops_the_run(self):
        self.account.set_password("wrong")
        self.account.save()
        run = self._run()
        self.assertEqual(run.status, TestRun.Status.FAILED)
        self.assertIn("Нууц үг буруу", run.error_message)
        self.assertFalse(run.results.exists())

    def test_redirects_are_followed(self):
        self.scenario.account, self.scenario.api_method, self.scenario.api_path = None, "GET", "/old"
        self.scenario.api_body, self.scenario.expected_column = "", ""
        self.scenario.save()
        run = self._run()
        result = run.results.first()
        self.assertIn("HTTP 200", result.actual_message)
        self.assertTrue(result.final_url.endswith("/api/ping"))


class ApiScenarioViewTests(TempMediaMixin, TestCase):
    def setUp(self):
        self.app, self.env, _web, self.data_file = make_setup()
        self.client.force_login(make_user("qa", ROLE_QA))

    def _create(self, **data):
        payload = {"name": "API", "api_method": "POST", "api_path": "api/users",
                   "api_body": '{"email": "{{email}}"}', "expected_column": "хүлээгдэх"}
        payload.update(data)
        return self.client.post(reverse("autotest:scenario_create", args=[self.app.pk]) + "?kind=api", payload)

    def test_steps_show_the_request_with_row_values(self):
        self.app.api_login_path = "/api/login"
        self.app.save()
        account = TestAccount(app=self.app, label="QA", username="qa")
        account.set_password("Secret#1")
        account.save()
        scenario = Scenario.objects.create(
            app=self.app, kind=Scenario.Kind.API, name="API", account=account, api_method="POST",
            api_path="/api/users", api_body='{"email": "{{email}}", "password": "{{password}}"}',
            expected_column="хүлээгдэх",
        )
        response = self.client.get(reverse("autotest:scenario_detail", args=[scenario.pk]))
        steps = response.context["wf_steps"]
        self.assertEqual([s["title"] for s in steps], ["Нэвтрэх", "Хүсэлт илгээх", "Үр дүнг шалгах"])
        self.assertIn('"email": "a@mail.mn"', steps[1]["code"])
        self.assertIn('"password": "***"', steps[1]["code"])
        self.assertNotContains(response, "Pass1234")

    def test_create_api_scenario(self):
        response = self._create()
        scenario = Scenario.objects.get(name="API")
        self.assertRedirects(response, reverse("autotest:scenario_detail", args=[scenario.pk]))
        self.assertTrue(scenario.is_api)
        self.assertIsNone(scenario.page)
        self.assertEqual(scenario.api_path, "/api/users")
        self.assertEqual(scenario.required_columns(), ["email", "хүлээгдэх"])
        for url in (reverse("autotest:scenario_detail", args=[scenario.pk]),
                    reverse("autotest:scenario_edit", args=[scenario.pk]),
                    reverse("autotest:app_detail", args=[self.app.pk])):
            self.assertEqual(self.client.get(url).status_code, 200, url)

    def test_invalid_body_and_full_url_are_rejected(self):
        response = self._create(api_body='{"email": }', api_path="https://evil.example/x")
        self.assertEqual(response.status_code, 200)
        self.assertIn("api_body", response.context["form"].errors)
        self.assertIn("api_path", response.context["form"].errors)

    def test_account_needs_api_login_path(self):
        account = TestAccount(app=self.app, label="QA", username="qa")
        account.set_password("x")
        account.save()
        response = self._create(account=account.pk)
        self.assertIn("account", response.context["form"].errors)

    def test_run_detail_shows_response(self):
        self._create()
        scenario = Scenario.objects.get(name="API")
        run = TestRun.objects.create(scenario=scenario, data_file=self.data_file, environment=self.env,
                                     data_file_name="users", environment_name="staging",
                                     target_url="https://staging.example.com/api/users", status="done")
        RunResult.objects.create(run=run, row_number=2, verdict="fail", response_detail="curl -X POST x\n\n→ HTTP 500")
        response = self.client.get(reverse("autotest:run_detail", args=[run.pk]))
        self.assertContains(response, "js-response")
        self.assertContains(response, "→ HTTP 500")
