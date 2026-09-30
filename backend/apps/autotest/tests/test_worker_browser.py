"""
Worker-ийг жинхэнэ Chromium-аар, туршилтын "бүртгүүлэх" сайтын эсрэг ажиллуулна.
Playwright / Chromium суугаагүй орчинд алгасна. Удаан тул энгийн `./test.sh`-д ороогүй:

    ./test.sh --browser
"""
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from django.core.management import call_command
from django.test import TestCase, override_settings, tag

from apps.autotest.datafiles import suggest_mapping
from apps.autotest.models import Page, PageScan, TestAccount, TestRun
from apps.tickets.tests.helpers import make_user

from .helpers import REGISTER_FIELDS, TempMediaMixin, make_setup

REGISTER_PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Бүртгүүлэх</title></head><body>
<form method="post" action="/register">
  <label for="email">Имэйл хаяг</label><input id="email" name="email" type="email" required>
  <label for="password">Нууц үг</label><input id="password" name="password" type="password" required>
  <label>Гар утас <input name="phone"></label>
  <input type="checkbox" id="terms" name="terms" required><label for="terms">Нөхцөл зөвшөөрөх</label>
  {error}
  <button type="submit">Бүртгүүлэх</button>
</form>
<form action="/lang" method="post">
  <select name="language" onchange="this.form.submit()"><option>Монгол</option><option>English</option></select>
</form></body></html>"""


LOGIN_PAGE = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<form method="post" action="/login">
  <label>Нэвтрэх нэр <input name="username"></label>
  <label>Нууц үг <input name="password" type="password"></label>
  {error}<button type="submit">Нэвтрэх</button>
</form></body></html>"""

NEW_ITEM_PAGE = """<!doctype html><html><head><meta charset="utf-8"></head><body>
<form method="post" action="/panel/new">
  <label for="title">Гарчиг</label><input id="title" name="title">
  <label for="sub">Дэд ангилал</label><select id="sub" name="sub" disabled><option value="">Дэд ангилал байхгүй</option></select>
  <label>Тайлбар</label><textarea name="desc" placeholder="Алдааны хувьд: давтах алхам, хүлээгдэж буй үр дүн"></textarea>
  {error}<button type="submit">Хадгалах</button>
</form></body></html>"""


class FakeSite(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _redirect(self, location, cookie=None):
        self.send_response(302)
        self.send_header("Location", location)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def _logged_in(self):
        return "session=qa-ok" in self.headers.get("Cookie", "")

    def _html(self, body, status=200):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/to-metadata"):
            # Нийтийн сайт cloud metadata руу redirect хийх халдлага.
            self.send_response(302)
            self.send_header("Location", "http://169.254.169.254/latest/meta-data/")
            self.end_headers()
        elif self.path.startswith("/register"):
            self._html(REGISTER_PAGE.format(error=""))
        elif self.path.startswith("/welcome"):
            # Амжилтын хуудсан дээрх улаан текст (TMS-ийн SLA ⚠ шиг) нь илгээлтийн алдаа биш.
            self._html('<h1>Амжилттай бүртгэгдлээ</h1><span class="text-danger">⚠ 2026-09-30 16:31</span>')
        elif self.path.startswith("/login"):
            self._html(LOGIN_PAGE.format(error=""))
        elif self.path.startswith("/panel/new"):
            if "session=dev" in self.headers.get("Cookie", ""):
                return self._html("<h1>Хандах эрхгүй</h1>", 403)
            if not self._logged_in():
                return self._redirect("/login")
            self._html(NEW_ITEM_PAGE.format(error=""))
        elif self.path.startswith("/panel"):
            # Django messages шиг: амжилтын мессеж ч role="alert"-тай.
            body = '<h1>Самбар</h1><div class="alert alert-success" role="alert">Амжилттай хадгалагдлаа</div>'
            self._html(body if self._logged_in() else "forbidden", 200 if self._logged_in() else 403)
        else:
            self._html("not found", 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(length).decode()).items()}
        if self.path.startswith("/login"):
            if (form.get("username"), form.get("password")) == ("qa_test", "Right#pw1"):
                return self._redirect("/panel", cookie="session=qa-ok; Path=/")
            if (form.get("username"), form.get("password")) == ("dev_test", "Dev#pw1"):
                return self._redirect("/", cookie="session=dev; Path=/")
            return self._html(LOGIN_PAGE.format(error='<div class="error">Нэр эсвэл нууц үг буруу</div>'))
        if self.path.startswith("/panel/new"):
            if not self._logged_in():
                return self._redirect("/login")
            if not form.get("title"):
                return self._html(NEW_ITEM_PAGE.format(error='<div class="error">Гарчиг заавал</div>'))
            return self._redirect("/panel")
        if form.get("email") == "locked@mail.mn":  # TMS-ийн нэвтрэх түгжээ шиг шар анхааруулга
            return self._html(REGISTER_PAGE.format(
                error='<div class="alert alert-warning">Олон удаа буруу оролдсон тул 15 минутын дараа</div>'))
        if len(form.get("password", "")) < 8:
            return self._html(REGISTER_PAGE.format(error='<div class="error">Нууц үг 8-аас доошгүй тэмдэгт</div>'))
        # "exist@" бүртгэлтэй гэж алдаа өгөх ёстой ч энэ сайт өгдөггүй — тест үүнийг bug гэж илрүүлнэ.
        self.send_response(302)
        self.send_header("Location", "/welcome")
        self.end_headers()


def _chromium_available():
    from apps.autotest.runner import _in_browser_thread, launch_browser

    def launch():
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            launch_browser(playwright).close()

    try:
        _in_browser_thread(launch)
        return True
    except Exception:
        return False


@tag("browser")
@override_settings(AUTOTEST_ALLOW_PRIVATE_HOSTS=True, AUTOTEST_ROW_DELAY_MS=0)
class WorkerBrowserTests(TempMediaMixin, TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not _chromium_available():
            raise cls.skipTest(cls, "Playwright Chromium суугаагүй")
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeSite)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        super().tearDownClass()

    def _work(self):
        call_command("run_autotest_worker", once=True, stdout=open(os.devnull, "w"))

    def test_scan_finds_fields_by_visible_label(self):
        scan = PageScan.objects.create(url=self.base_url + "/register", requested_by=make_user("qa"))
        self._work()
        scan.refresh_from_db()
        self.assertEqual(scan.status, PageScan.Status.DONE, scan.error_message)
        labels = [f["label"] for f in scan.result["fields"]]
        self.assertEqual(labels, ["Имэйл хаяг", "Нууц үг", "Гар утас", "Нөхцөл зөвшөөрөх", "language"])
        # Хэл сонгох нь тусдаа форм — үндсэн формд хамаарахгүй.
        self.assertEqual([f["in_main_form"] for f in scan.result["fields"]], [True, True, True, True, False])
        self.assertEqual(scan.result["buttons"][0]["label"], "Бүртгүүлэх")

        mapped = suggest_mapping(scan.result["fields"], ["email", "password", "phone", "language"])
        self.assertEqual([m["source"] for m in mapped], ["column", "column", "column", "check", "skip"])

    def test_run_judges_every_row(self):
        fields = REGISTER_FIELDS + [{"label": "Гар утас", "selector": "input[name=phone]", "kind": "text",
                                     "source": "column", "value": "phone"}]
        _app, env, scenario, data_file = make_setup(base_url=self.base_url, fields=fields, rows=[
            ["Тайлбар", "email", "password", "phone", "хүлээгдэх"],
            ["Зөв бүртгэл", "ok{{random}}@mail.mn", "Pass1234", "99112233", "амжилттай"],
            ["Буруу имэйл", "bat@@mail", "Pass1234", "", "алдаа"],
            ["Богино нууц үг", "a@mail.mn", "12", "", "алдаа: 8-аас доошгүй"],
            ["Давхардсан имэйл", "exist@mail.mn", "Pass1234", "", "алдаа: бүртгэлтэй"],
            ["Түгжигдсэн", "locked@mail.mn", "Pass1234", "", "алдаа: Олон удаа"],
        ])
        run = TestRun.objects.create(
            scenario=scenario, data_file=data_file, environment=env, data_file_name="users",
            environment_name="staging", target_url=env.url_for(scenario.page.path), total=5,
        )
        self._work()
        run.refresh_from_db()
        self.assertEqual(run.status, TestRun.Status.DONE, run.error_message)
        results = {r.description: r for r in run.results.all()}

        ok = results["Зөв бүртгэл"]
        self.assertEqual((ok.verdict, ok.actual_outcome), ("pass", "success"), ok.actual_message)
        self.assertRegex(ok.input_data["email"], r"^ok[0-9a-f]{6}@mail\.mn$")
        self.assertEqual(ok.input_data["password"], "***")
        self.assertTrue(ok.final_url.endswith("/welcome"))

        self.assertEqual(results["Буруу имэйл"].verdict, "pass", results["Буруу имэйл"].actual_message)
        short = results["Богино нууц үг"]
        self.assertEqual(short.verdict, "pass")
        self.assertIn("8-аас доошгүй", short.actual_message)

        bug = results["Давхардсан имэйл"]
        self.assertEqual((bug.verdict, bug.actual_outcome), ("fail", "success"))
        self.assertTrue(bug.screenshot)
        self.assertEqual(results["Түгжигдсэн"].verdict, "pass", results["Түгжигдсэн"].actual_message)
        self.assertEqual((run.passed, run.failed, run.errored), (4, 1, 0))

    def test_missing_field_is_reported_as_error(self):
        fields = [{"label": "Байхгүй талбар", "selector": "#nope", "kind": "text", "source": "constant", "value": "x"}]
        _app, env, scenario, data_file = make_setup(base_url=self.base_url, fields=fields)
        run = TestRun.objects.create(
            scenario=scenario, data_file=data_file, environment=env, data_file_name="users",
            environment_name="staging", target_url=env.url_for(scenario.page.path), total=1,
        )
        self._work()
        result = run.results.get()
        self.assertEqual(result.verdict, "error")
        self.assertIn("'Байхгүй талбар' талбарыг бөглөж чадсангүй", result.actual_message)

    def test_generated_data_runs_without_errors(self):
        """Scan → өгөгдөл үүсгэх → ажиллуулах: үүсгэсэн утга бүрийг хуудсанд бөглөж чадна."""
        from apps.autotest import generator

        scan = PageScan.objects.create(url=self.base_url + "/register", requested_by=make_user("qa"))
        self._work()
        scan.refresh_from_db()
        columns, rows, mapping = generator.generate(scan.result["fields"])
        self.assertNotIn("language", columns)
        fields = [dict(f, source="column", value=mapping[f["selector"]])
                  for f in scan.result["fields"] if f["selector"] in mapping]
        _app, env, scenario, data_file = make_setup(base_url=self.base_url, fields=fields, rows=[columns] + rows)
        run = TestRun.objects.create(
            scenario=scenario, data_file=data_file, environment=env, data_file_name="gen",
            environment_name="staging", target_url=env.url_for(scenario.page.path), total=len(rows),
        )
        self._work()
        run.refresh_from_db()
        self.assertEqual(run.status, TestRun.Status.DONE, run.error_message)
        self.assertEqual(run.errored, 0, [r.actual_message for r in run.results.filter(verdict="error")])
        self.assertEqual(run.results.get(description="Бүх талбар зөв").verdict, "pass")
        self.assertEqual(run.results.get(description="Имэйл хаяг: буруу формат").verdict, "pass")
        self.assertEqual(run.results.get(description="Нөхцөл зөвшөөрөх: чагтлаагүй").verdict, "pass")

    def test_redirect_to_metadata_is_blocked(self):
        scan = PageScan.objects.create(url=self.base_url + "/to-metadata", requested_by=make_user("qa"))
        self._work()
        scan.refresh_from_db()
        self.assertEqual(scan.status, PageScan.Status.FAILED)
        self.assertIn("хаалттай хаяг", scan.error_message)

    def _login_run(self, password):
        fields = [
            {"label": "Гарчиг", "selector": "#title", "kind": "text", "source": "column", "value": "title"},
            {"label": "Дэд ангилал", "selector": "#sub", "kind": "select", "source": "column", "value": "sub"},
        ]
        # Хуучин scan-ээр үүссэн файл шиг: идэвхгүй талбарт утгагүй сонголтын текст бичигдсэн.
        app, env, scenario, data_file = make_setup(base_url=self.base_url, fields=fields, rows=[
            ["Тайлбар", "title", "sub", "хүлээгдэх"],
            ["Зөв", "Шинэ", "Дэд ангилал байхгүй", "амжилттай"],
            ["Хоосон", "", "", "алдаа: заавал"],
        ])
        page = Page.objects.create(app=app, name="Шинэ", path="/panel/new")
        app.login_page = Page.objects.create(app=app, name="Нэвтрэх", path="/login")
        app.save()
        account = TestAccount(app=app, label="QA", username="qa_test")
        account.set_password(password)
        account.save()
        scenario.page, scenario.account = page, account
        scenario.save()
        return TestRun.objects.create(
            scenario=scenario, data_file=data_file, environment=env, data_file_name="items",
            environment_name="staging", target_url=env.url_for(page.path), total=2,
            account=account, account_label="QA", login_url=env.url_for("/login"),
        )

    def test_logged_in_run_reaches_protected_page(self):
        run = self._login_run("Right#pw1")
        self._work()
        run.refresh_from_db()
        self.assertEqual(run.status, TestRun.Status.DONE, run.error_message)
        self.assertEqual((run.passed, run.failed, run.errored), (2, 0, 0),
                         [r.actual_message for r in run.results.all()])

    def test_wrong_password_fails_run_with_site_message(self):
        run = self._login_run("wrong")
        self._work()
        run.refresh_from_db()
        self.assertEqual(run.status, TestRun.Status.FAILED)
        self.assertIn("нэвтэрч чадсангүй", run.error_message)
        self.assertIn("Нэр эсвэл нууц үг буруу", run.error_message)
        self.assertFalse(run.results.exists())

    def test_access_check_per_user(self):
        from apps.autotest.views import _queue_access_run

        data_run = self._login_run("Right#pw1")
        scenario, qa = data_run.scenario, data_run.account
        dev = TestAccount(app=scenario.app, label="Dev", username="dev_test")
        dev.set_password("Dev#pw1")
        dev.save()
        # Dev-д нээлттэй гэж буруу хүлээлт тавьж, унах ёстойг шалгана.
        scenario.access_rules = {"anon": "denied", str(qa.pk): "open", str(dev.pk): "open"}
        scenario.save()
        run = _queue_access_run(scenario, data_run.environment, None)
        self._work()
        run.refresh_from_db()
        self.assertEqual(run.status, TestRun.Status.DONE, run.error_message)
        results = {r.description: r for r in run.results.all()}
        self.assertEqual((results["Нэвтрэхгүй"].verdict, results["Нэвтрэхгүй"].actual_message),
                         ("pass", "Нэвтрэх хуудас руу шилжүүлсэн"))
        self.assertEqual((results["QA"].verdict, results["QA"].actual_outcome), ("pass", "open"))
        self.assertEqual((results["Dev"].verdict, results["Dev"].actual_message), ("fail", "HTTP 403"))
        self.assertTrue(results["Dev"].screenshot)

    def test_scan_logs_in_first(self):
        run = self._login_run("Right#pw1")
        scan = PageScan.objects.create(url=run.target_url, account=run.account, login_url=run.login_url,
                                       requested_by=make_user("qa"))
        self._work()
        scan.refresh_from_db()
        self.assertEqual(scan.status, PageScan.Status.DONE, scan.error_message)
        # for=-гүй шошго ч placeholder-оос давуу (урт placeholder баганын нэр болохгүй).
        self.assertEqual([f["label"] for f in scan.result["fields"]], ["Гарчиг", "Дэд ангилал", "Тайлбар"])
        sub = scan.result["fields"][1]
        self.assertEqual((sub["disabled"], sub["has_empty_option"], sub["options"]), (True, True, []))

    @override_settings(AUTOTEST_ALLOW_PRIVATE_HOSTS=False)
    def test_private_hosts_blocked_by_default(self):
        _app, env, scenario, data_file = make_setup(base_url=self.base_url)
        run = TestRun.objects.create(
            scenario=scenario, data_file=data_file, environment=env, data_file_name="users",
            environment_name="staging", target_url=env.url_for(scenario.page.path), total=1,
        )
        self._work()
        run.refresh_from_db()
        self.assertEqual(run.status, TestRun.Status.FAILED)
        self.assertIn("Дотоод сүлжээний", run.error_message)
        self.assertFalse(run.results.exists())
