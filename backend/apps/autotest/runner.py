"""
Playwright (Chromium)-аар хуудас шалгах (PageScan) болон сценари ажиллуулах (TestRun).
Зөвхөн `run_autotest_worker` процессоос дуудагдана — вэб хүсэлт дотор browser нээхгүй.
"""
import queue
import re
import threading
import time
from urllib.parse import urljoin, urlsplit

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone
from django.utils.translation import gettext as _

from .datafiles import (
    DataFileError, description_of, fill_placeholders, judge, parse_expected, placeholder_values, read_rows,
    run_stamp,
)
from .models import PageScan, RunResult, TestRun
from .safety import UnsafeURL, check_url

NAV_TIMEOUT_MS = 30_000
ACTION_TIMEOUT_MS = 8_000
SETTLE_TIMEOUT_MS = 8_000
DEPENDENT_TIMEOUT_MS = 5_000  # дэд ангилал г.м. өөр талбараас хамаарч идэвхжихийг хүлээх

DEFAULT_ERROR_SELECTORS = ", ".join([
    ".error", ".errors", ".errorlist", ".error-message", ".error-text", ".field-error",
    ".form-error", ".invalid-feedback", ".alert-danger", ".alert-error", ".text-danger",
    ".has-error .help-block", "[role=alert]", "[aria-live=assertive]", ".toast-error",
    ".ant-form-item-explain-error", ".Mui-error", ".v-messages__message", ".parsley-errors-list",
])
SUCCESS_SELECTORS = ", ".join([
    ".alert-success", ".success", ".success-message", ".toast-success", "[role=status]",
])
# Формоос өөр хуудас руу шилжсэний дараа алдаа гэж тооцох зүйлс (өнгөний класс .text-danger биш).
PAGE_ERROR_SELECTORS = ", ".join([
    ".alert-danger", ".alert-error", "[role=alert]", ".toast-error", ".errorlist", ".invalid-feedback",
])
WARNING_SELECTORS = ".alert-warning, .toast-warning"
NOT_ERROR_SELECTORS = SUCCESS_SELECTORS + ", " + ", ".join([
    ".alert-info", ".alert-primary", ".alert-secondary", ".alert-light", ".alert-dark",
])
TRUTHY = {"1", "true", "yes", "y", "x", "тийм", "✓", "✔", "✅", "on"}

# Хуудсан дээрх бөглөх талбар, товчнуудыг хүний ойлгох нэртэй нь цуглуулна.
SCAN_JS = r"""
() => {
  const visible = el => {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none';
  };
  const unique = sel => { try { return document.querySelectorAll(sel).length === 1; } catch (e) { return false; } };
  // React (:r1:), MUI (mui-123), Ember (ember45) г.м. ачаалах бүрт өөрчлөгддөг автомат id-г ашиглахгүй.
  const stableId = id => id && !/:|^\d|\d{3,}|^(react|mui|ember|radix|headlessui|rc[-_]|ext-gen|yui|ng-|downshift)/i.test(id);
  const quote = v => '"' + String(v).replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
  const text = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();

  function selectorFor(el) {
    const tag = el.tagName.toLowerCase();
    if (stableId(el.id) && unique('#' + CSS.escape(el.id))) return '#' + CSS.escape(el.id);
    const name = el.getAttribute('name');
    if (name) {
      let sel = tag + '[name=' + quote(name) + ']';
      if (el.type === 'radio' || el.type === 'checkbox') sel += '[value=' + quote(el.value) + ']';
      if (unique(sel)) return sel;
    }
    for (const attr of ['data-testid', 'data-test', 'aria-label', 'placeholder']) {
      const v = el.getAttribute(attr);
      if (v && unique(tag + '[' + attr + '=' + quote(v) + ']')) return tag + '[' + attr + '=' + quote(v) + ']';
    }
    const path = [];
    for (let node = el; node && node.nodeType === 1 && node !== document.body; node = node.parentElement) {
      let i = 1;
      for (let sib = node.previousElementSibling; sib; sib = sib.previousElementSibling)
        if (sib.tagName === node.tagName) i++;
      path.unshift(node.tagName.toLowerCase() + ':nth-of-type(' + i + ')');
    }
    return 'body > ' + path.join(' > ');
  }

  function labelFor(el) {
    if (el.labels && el.labels.length) { const t = text(el.labels[0]); if (t) return t; }
    const aria = el.getAttribute('aria-label');
    if (aria) return aria.trim();
    const by = el.getAttribute('aria-labelledby');
    if (by) {
      const t = by.split(/\s+/).map(id => { const n = document.getElementById(id); return n ? text(n) : ''; }).join(' ').trim();
      if (t) return t;
    }
    const prev = el.previousElementSibling;
    // for=-гүй ч талбарын яг өмнөх <label> — placeholder-оос (урт тайлбар байж болно) илүү нэр.
    if (prev && prev.tagName === 'LABEL' && text(prev) && text(prev).length < 60) return text(prev);
    if (el.placeholder) return el.placeholder.trim();
    if (prev && text(prev) && text(prev).length < 60) return text(prev);
    return el.name || el.id || '';
  }

  const skipTypes = new Set(['hidden', 'submit', 'button', 'reset', 'image', 'file']);
  const fillable = [...document.querySelectorAll('input, textarea, select')].filter(el => {
    const type = (el.getAttribute('type') || 'text').toLowerCase();
    if (el.tagName === 'INPUT' && skipTypes.has(type)) return false;
    const labelVisible = el.labels && [...el.labels].some(visible);
    return visible(el) || labelVisible;
  });
  // Үндсэн форм = хамгийн олон бөглөх талбартай форм. Бусад формын талбарууд (хэл сонгох,
  // толгой хэсгийн хайлт ...) in_main_form=false — автоматаар алгасагдана.
  const counts = new Map();
  fillable.forEach(el => { if (el.form) counts.set(el.form, (counts.get(el.form) || 0) + 1); });
  let mainForm = null;
  counts.forEach((n, form) => { if (!mainForm || n > counts.get(mainForm)) mainForm = form; });
  const fields = [];
  fillable.forEach(el => {
    const type = (el.getAttribute('type') || 'text').toLowerCase();
    let kind = 'text';
    if (el.tagName === 'SELECT') kind = 'select';
    else if (['checkbox', 'radio', 'password', 'email'].includes(type)) kind = type;
    const num = attr => { const v = el.getAttribute(attr); return v !== null && v !== '' && !isNaN(v) ? Number(v) : null; };
    fields.push({
      label: labelFor(el).replace(/\s*\*\s*$/, '').slice(0, 120),
      selector: selectorFor(el),
      kind: kind,
      type: el.tagName === 'INPUT' ? type : el.tagName.toLowerCase(),
      maxlength: el.maxLength > 0 && el.maxLength < 100000 ? el.maxLength : null,
      minlength: el.minLength > 0 ? el.minLength : null,
      min: num('min'),
      max: num('max'),
      pattern: el.getAttribute('pattern') || '',
      in_main_form: !mainForm || el.form === mainForm,
      name: el.getAttribute('name') || '',
      id: el.id || '',
      placeholder: el.getAttribute('placeholder') || '',
      required: !!el.required,
      // Өөр талбараас хамаарч идэвхждэг (ж: ангилал сонгоход дэд ангилал) — өгөгдөл үүсгэхгүй.
      disabled: !!el.disabled,
      // Утгагүй сонголт ("---------", "Дэд ангилал байхгүй") нь жинхэнэ сонголт биш.
      has_empty_option: el.tagName === 'SELECT' && [...el.options].some(o => o.value === ''),
      options: el.tagName === 'SELECT'
        ? [...el.options].filter(o => o.value !== '').map(o => o.text.trim()).filter(Boolean).slice(0, 50) : [],
    });
  });

  const buttons = [];
  document.querySelectorAll('button, input[type=submit], input[type=button], [role=button]').forEach(el => {
    if (!visible(el)) return;
    const label = (text(el) || el.value || el.getAttribute('aria-label') || el.getAttribute('title') || '').slice(0, 80);
    const type = (el.getAttribute('type') || (el.tagName === 'BUTTON' && el.form ? 'submit' : '')).toLowerCase();
    buttons.push({ label: label, selector: selectorFor(el), is_submit: type === 'submit' });
  });
  buttons.sort((a, b) => b.is_submit - a.is_submit);
  return { title: document.title, fields: fields.slice(0, 60), buttons: buttons.slice(0, 30) };
}
"""

DEFAULT_SUBMIT_SELECTOR = "form [type=submit], button[type=submit], input[type=submit]"

# Browser-ийн өөрийн (HTML5) шалгалтад унасан талбаруудын мессеж — зөвхөн илгээсэн формын
# дотор (толгой хэсгийн хайлт гэх мэт өөр формын required талбар алдаа болж орохгүй).
INVALID_JS = """
(submitSelector) => {
  let scope = document;
  try {
    const button = document.querySelector(submitSelector);
    const form = button && (button.form || button.closest('form'));
    if (form) scope = form;
  } catch (e) {}
  return [...scope.querySelectorAll('input, select, textarea')]
    .filter(el => el.willValidate && !el.checkValidity())
    .map(el => el.validationMessage).filter(Boolean);
}
"""


class RowError(Exception):
    """Мөрийг ажиллуулж чадаагүй (талбар олдоогүй г.м.) — хэрэглэгчид харуулах мессежтэй."""


class LoginFailed(Exception):
    """Тестийн хэрэглэгчээр нэвтэрч чадаагүй — ажил бүхэлдээ зогсоно."""


def _login_of(job):
    """(login_url, username, password) эсвэл None. Нууц үгийг DB-тэй thread-д тайлна."""
    from .crypto import DecryptError

    if not job.login_url:
        return None
    account = job.account
    if account is None:
        raise LoginFailed(_("Тестийн хэрэглэгч устгагдсан байна."))
    try:
        password = account.get_password()
    except DecryptError:
        raise LoginFailed(
            _("'%(name)s' хэрэглэгчийн нууц үгийг уншиж чадсангүй. Нууц үгийг дахин оруулна уу.") % {"name": account.label}
        )
    try:
        check_url(job.login_url)
    except UnsafeURL as exc:
        raise LoginFailed(str(exc))
    return job.login_url, account.username, password


def login(browser, login_url, username, password):
    """
    Нэвтрэх хуудсыг бөглөж, session-ийг (cookie, localStorage) буцаана — мөр бүр тэр session-тэй
    шинэ context дээр ажиллана. Талбарыг автоматаар олно: харагдаж буй нууц үгийн талбар ба
    түүний формын эхний текст/имэйл талбар.
    """
    from playwright.sync_api import Error as PlaywrightError

    context = _new_context(browser)
    page = context.new_page()
    try:
        page.goto(login_url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        _settle(page)
        password_input = page.locator("input[type=password]:visible").first
        if not password_input.count():
            raise LoginFailed(_("Нэвтрэх хуудсанд нууц үгийн талбар олдсонгүй: %(url)s") % {"url": login_url})
        form = password_input.locator("xpath=ancestor::form[1]")
        scope = form if form.count() else page
        # Эхлээд нэр/autocomplete-оороо нэвтрэх нэр гэдэг нь тодорхой талбар, үгүй бол эхний текст талбар.
        username_input = scope.locator(", ".join(
            f"input{attr}:visible" for attr in (
                "[autocomplete=username]", "[type=email]", "[name*=user i]", "[name*=login i]", "[name*=email i]",
                "[id*=user i]", "[id*=login i]", "[id*=email i]",
            )
        )).first
        if not username_input.count():
            username_input = scope.locator(
                "input[type=text]:visible, input[type=tel]:visible, input:not([type]):visible"
            ).first
        if not username_input.count():
            raise LoginFailed(_("Нэвтрэх хуудсанд нэвтрэх нэрийн талбар олдсонгүй: %(url)s") % {"url": login_url})
        username_input.fill(username)
        password_input.fill(password)
        password_input.press("Enter")
        _settle(page)
        still_on_login = (
            _strip_url(page.url) == _strip_url(login_url)
            and page.locator("input[type=password]:visible").count()
        )
        if still_on_login:
            errors = "; ".join(_visible_texts(page, DEFAULT_ERROR_SELECTORS))[:300]
            raise LoginFailed(
                _("'%(user)s' хэрэглэгчээр нэвтэрч чадсангүй: %(err)s")
                % {"user": username, "err": errors or _("нэвтрэх нэр, нууц үгээ шалгана уу")}
            )
        return context.storage_state()
    except PlaywrightError as exc:
        raise LoginFailed(_("Нэвтрэх хуудсыг нээж чадсангүй: %(err)s") % {"err": _short_error(exc)})
    finally:
        context.close()


def launch_browser(playwright):
    try:
        return playwright.chromium.launch(headless=True)
    except Exception:
        # Playwright-ийн Chromium татагдаагүй бол системийн Google Chrome-ийг ашиглана.
        return playwright.chromium.launch(headless=True, channel="chrome")


def _new_context(browser, storage_state=None):
    context = browser.new_context(
        locale="mn-MN", ignore_https_errors=True, viewport={"width": 1280, "height": 900},
        storage_state=storage_state,
    )
    context.set_default_timeout(ACTION_TIMEOUT_MS)
    _guard_requests(context)
    return context


def _guard_requests(context):
    """
    Хуудас дотроос хийгдэх бүх хүсэлтийг (хуудас, iframe, fetch, зураг ...) safety.check_url-аар
    шалгана. Redirect-ийг browser өөрөө дагавал route-д харагддаггүй тул хариуг энд авч
    (redirect дагахгүйгээр), Location нь аюулгүй бол л browser-т дамжуулна — эс тэгвэл нийтийн
    сайт 169.254.x.x (cloud metadata) руу redirect хийж, агуулга нь дэлгэцийн зурагт үлдэж болно.
    (Зөвхөн хуудас шилжилтийг ингэж дамжуулбал Chromium нэг сайтын static файлуудыг ERR_FAILED
    болгодог тул бүх хүсэлтийг ижил замаар дамжуулна.) Хост бүрийг нэг л удаа шалгана.
    """
    decisions = {}

    def allowed(url):
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https"):
            return True
        key = (parts.hostname, parts.port)
        if key not in decisions:
            try:
                check_url(url)
                decisions[key] = True
            except UnsafeURL:
                decisions[key] = False
        return decisions[key]

    def handle(route):
        from playwright.sync_api import Error as PlaywrightError

        url = route.request.url
        if urlsplit(url).scheme not in ("http", "https"):
            return route.continue_()
        if not allowed(url):
            return route.abort("blockedbyclient")
        try:
            response = route.fetch(max_redirects=0, timeout=NAV_TIMEOUT_MS)
        except PlaywrightError:
            return route.abort("failed")
        location = response.headers.get("location")
        if 300 <= response.status < 400 and location and not allowed(urljoin(url, location)):
            return route.abort("blockedbyclient")
        route.fulfill(response=response)  # redirect-ийг browser дагаж, шинэ хүсэлт дахин энд шалгагдана

    context.route("**/*", handle)


# --- PageScan ---------------------------------------------------------------

def execute_scan(scan):
    from playwright.sync_api import Error as PlaywrightError

    try:
        check_url(scan.url)
        scan.result = _in_browser_thread(_scan_page, scan.url, _login_of(scan))
        scan.status = PageScan.Status.DONE
        if not scan.result.get("fields"):
            scan.error_message = _("Энэ хуудсанд бөглөх талбар олдсонгүй.")
    except (UnsafeURL, LoginFailed) as exc:
        scan.status, scan.error_message = PageScan.Status.FAILED, str(exc)
    except PlaywrightError as exc:
        scan.status = PageScan.Status.FAILED
        scan.error_message = _("Хуудсыг нээж чадсангүй: %(err)s") % {"err": _short_error(exc)}
    scan.save()


def _scan_page(url, credentials=None):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = launch_browser(playwright)
        try:
            state = login(browser, *credentials) if credentials else None
            page = _new_context(browser, state).new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
            _settle(page)
            return page.evaluate(SCAN_JS)
        finally:
            browser.close()


def _in_browser_thread(func, *args):
    """func-ийг тусдаа thread-д ажиллуулж үр дүнг (эсвэл алдааг) буцаана."""
    outcome = {}

    def target():
        try:
            outcome["value"] = func(*args)
        except BaseException as exc:
            outcome["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join()
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


# --- TestRun ----------------------------------------------------------------

def execute_run(run):
    """
    Browser-ийг тусдаа thread-д ажиллуулж, мөр бүрийн үр дүнг энд (үндсэн thread) DB-д бичнэ.
    Playwright-ийн sync API event loop ажиллуулдаг тул түүний дотор ORM дуудвал Django
    өөр DB холболт нээж (хаагдахгүй үлдэнэ) — тиймээс browser, DB хоёрыг салгасан.
    """
    run.started_at = timezone.now()
    run.save(update_fields=["started_at", "updated_at"])
    if run.kind == TestRun.Kind.ACCESS:
        return _execute_access(run)
    scenario = run.scenario
    if scenario.is_api:
        from . import api

        return api.execute_run(run)
    try:
        rows = _load_rows(run)
        credentials = _login_of(run)
        check_url(run.target_url)
    except (DataFileError, UnsafeURL, LoginFailed) as exc:
        return _finish(run, TestRun.Status.FAILED, str(exc))

    run.total = len(rows)
    run.save(update_fields=["total", "updated_at"])
    secret_columns = scenario.secret_columns()
    delay = getattr(settings, "AUTOTEST_ROW_DELAY_MS", 300) / 1000

    results, stop = queue.Queue(), threading.Event()
    browser_thread = threading.Thread(
        target=_browse_rows, args=(scenario, run.target_url, rows, delay, results, stop, credentials), daemon=True
    )
    browser_thread.start()
    status, error = TestRun.Status.DONE, ""
    try:
        while True:
            item = results.get()
            if item is _FINISHED:
                break
            if isinstance(item, LoginFailed):
                status, error = TestRun.Status.FAILED, str(item)
                continue
            if isinstance(item, BaseException):
                raise item
            line_number, row, result = item
            _save_result(run, line_number, row, result, secret_columns)
            if TestRun.objects.filter(pk=run.pk, status=TestRun.Status.CANCELLED).exists():
                status = TestRun.Status.CANCELLED
                stop.set()
    finally:
        stop.set()
        browser_thread.join()
    return _finish(run, status, error)


_FINISHED = object()


# --- Эрх шалгах -------------------------------------------------------------

def _execute_access(run):
    """
    Хэрэглэгч бүрээр (эсвэл нэвтрэхгүйгээр) хуудсыг нээж, нээлттэй/хаалттай эсэхийг хүлээлттэй
    тулгана. Сценарийн форм харагдвал "нээлттэй", үгүй бол (403/404, нэвтрэх хуудас руу
    шилжүүлсэн, "эрхгүй" хуудас) "хаалттай".
    """
    from .crypto import DecryptError
    from .models import TestAccount

    try:
        check_url(run.target_url)
    except UnsafeURL as exc:
        return _finish(run, TestRun.Status.FAILED, str(exc))
    accounts = TestAccount.objects.in_bulk([r["account"] for r in run.access_rules if r.get("account")])
    checks = []  # (label, expect, credentials | None, алдааны мессеж)
    for rule in run.access_rules:
        credentials, problem = None, ""
        if rule.get("account"):
            account = accounts.get(rule["account"])
            if account is None:
                problem = _("Тестийн хэрэглэгч устгагдсан байна.")
            elif not run.login_url:
                problem = _("Тестийн хэрэглэгчид хэсэгт нэвтрэх хуудсаа сонгоно уу.")
            else:
                try:
                    credentials = (run.login_url, account.username, account.get_password())
                except DecryptError:
                    problem = _("'%(name)s' хэрэглэгчийн нууц үгийг уншиж чадсангүй. Нууц үгийг дахин оруулна уу.") % {
                        "name": account.label}
        checks.append((rule["label"], rule["expect"], credentials, problem))

    selectors = [f["selector"] for f in run.scenario.fields if f.get("source") != "skip" and f.get("selector")]
    results = _in_browser_thread(_browse_access, run.target_url, run.login_url, selectors, checks)
    for index, ((label, _expect, _cred, _problem), result) in enumerate(zip(checks, results), start=1):
        _save_result(run, index, {"Тайлбар": label}, result, set())
    return _finish(run, TestRun.Status.DONE)


def _browse_access(url, login_url, selectors, checks):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = launch_browser(playwright)
        try:
            return [check_access(browser, url, login_url, selectors, *check) for check in checks]
        finally:
            browser.close()


def check_access(browser, url, login_url, selectors, label, expect, credentials, problem):
    from playwright.sync_api import Error as PlaywrightError

    result = {
        "expected_outcome": expect, "expected_message": "", "actual_outcome": "", "actual_message": "",
        "final_url": "", "used_values": {}, "screenshot": None,
    }
    started = time.monotonic()
    if problem:
        result.update(verdict=RunResult.Verdict.ERROR, actual_message=problem, duration_ms=0)
        return result
    context = None
    try:
        state = login(browser, *credentials) if credentials else None
        context = _new_context(browser, state)
        page = context.new_page()
        response = page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        _settle(page)
        status = response.status if response else 0
        form_visible = any(page.locator(s).first.is_visible() for s in selectors) if status < 400 else False
        if status >= 400:
            message = f"HTTP {status}"
        elif login_url and _strip_url(page.url.split("?")[0]) == _strip_url(login_url.split("?")[0]):
            message = _("Нэвтрэх хуудас руу шилжүүлсэн")
        elif form_visible:
            message = _("Хуудас нээгдэж, форм харагдсан")
        else:
            message = _("Хуудас нээгдсэн ч форм харагдаагүй")
        actual = RunResult.Outcome.OPEN if form_visible else RunResult.Outcome.DENIED
        result.update(actual_outcome=actual, actual_message=message, final_url=page.url,
                      verdict=RunResult.Verdict.PASS if actual == expect else RunResult.Verdict.FAIL)
        if result["verdict"] == RunResult.Verdict.FAIL:
            result["screenshot"] = page.screenshot(full_page=True, type="png")
    except LoginFailed as exc:
        result.update(verdict=RunResult.Verdict.ERROR, actual_message=str(exc))
    except PlaywrightError as exc:
        result.update(verdict=RunResult.Verdict.ERROR, actual_message=_short_error(exc))
    finally:
        if context:
            context.close()
    result["duration_ms"] = int((time.monotonic() - started) * 1000)
    return result


def _browse_rows(scenario, url, rows, delay, results, stop, credentials=None):
    """Browser thread: DB-д хандахгүй, зөвхөн үр дүнг дараалалд хийнэ."""
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as playwright:
            browser = launch_browser(playwright)
            stamp = run_stamp()
            try:
                state = login(browser, *credentials) if credentials else None  # нэг л удаа нэвтэрнэ
                for index, (line_number, row) in enumerate(rows):
                    if stop.is_set():
                        break
                    if index and delay:
                        time.sleep(delay)
                    result = run_row(browser, scenario, url, row, line_number, stamp, state, credentials and credentials[0])
                    if result.get("session_lost"):  # session дууссан — дахин нэвтэрч, мөрийг давтана
                        state = login(browser, *credentials)
                        result = run_row(browser, scenario, url, row, line_number, stamp, state, credentials[0])
                    results.put((line_number, row, result))
            finally:
                browser.close()
    except BaseException as exc:
        results.put(exc)
    finally:
        results.put(_FINISHED)


def _load_rows(run):
    data_file = run.data_file
    if data_file is None:
        raise DataFileError(_("Өгөгдлийн файл устгагдсан байна."))
    try:
        with data_file.file.open("rb") as fh:
            _columns, rows = read_rows(fh, data_file.file.name)
    except FileNotFoundError:
        raise DataFileError(_("Өгөгдлийн файл серверээс олдсонгүй."))
    missing = [c for c in run.scenario.required_columns() if c not in rows[0][1]]
    if missing:
        raise DataFileError(_("Файлд дараах багана алга: %(cols)s") % {"cols": ", ".join(missing)})
    return rows


def _expected_for(scenario, row):
    outcome, message = parse_expected(row.get(scenario.expected_column, "")) if scenario.expected_column else ("", "")
    if outcome is None:  # 'амжилттай/алдаа' биш текст → зөвхөн мессежийг шалгана
        outcome = ""
    if scenario.expected_message_column and row.get(scenario.expected_message_column):
        message = row[scenario.expected_message_column]
    return outcome, message


def run_row(browser, scenario, url, row, line_number, stamp=None, storage_state=None, login_url=None):
    """
    Нэг мөрийг шинэ browser context дээр (нэвтэрсэн бол тэр session-тэй) ажиллуулж, dict буцаана.
    Хуудас нэвтрэх хуудас руу шилжүүлбэл (session дууссан) result["session_lost"] = True.
    """
    from playwright.sync_api import Error as PlaywrightError

    expected_outcome, expected_message = _expected_for(scenario, row)
    result = {
        "expected_outcome": expected_outcome, "expected_message": expected_message,
        "actual_outcome": "", "actual_message": "", "final_url": "",
        "used_values": {}, "screenshot": None,
    }
    started = time.monotonic()
    context = _new_context(browser, storage_state)
    page = context.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        _settle(page)
        start_url = page.url
        if login_url and _same_page(start_url, login_url) and not _same_page(url, login_url):
            result["session_lost"] = True
            raise RowError(_("Session дууссан — нэвтрэх хуудас руу шилжүүлсэн."))
        _fill_fields(page, scenario, row, line_number, result["used_values"], stamp)
        # Browser-ийн өөрийн шалгалтыг (required, type=email) илгээхээс ӨМНӨ уншина — илгээсний
        # дараа сервер талбарыг хоосолж буцаавал (нууц үг г.м.) түүнийг алдаа гэж андуурахгүй.
        invalid = page.evaluate(INVALID_JS, scenario.submit_selector or DEFAULT_SUBMIT_SELECTOR)
        _submit(page, scenario)
        flashes = _await_outcome(page)
        if login_url and _same_page(page.url, login_url) and not _same_page(url, login_url):
            # "Хуудас шилжсэн = амжилттай" гэж андуурахгүй. Илгээлт хийгдсэн эсэх нь тодорхойгүй тул
            # (нууц үг солиод гаргасан ч байж болно) давхар илгээхгүйн тулд давтахгүй.
            raise RowError(_("Илгээсний дараа нэвтрэх хуудас руу шилжсэн — session дууссан байж магадгүй."))
        outcome, message, page_text = _read_outcome(page, scenario, start_url, invalid, flashes)
        result.update(actual_outcome=outcome, actual_message=message, final_url=page.url)
        result["verdict"] = judge(expected_outcome, expected_message, outcome, message + "\n" + page_text)
    except RowError as exc:
        result.update(verdict=RunResult.Verdict.ERROR, actual_message=str(exc))
    except PlaywrightError as exc:
        result.update(verdict=RunResult.Verdict.ERROR, actual_message=_short_error(exc))
    try:
        result["final_url"] = result["final_url"] or page.url
        if result["verdict"] in (RunResult.Verdict.FAIL, RunResult.Verdict.ERROR):
            result["screenshot"] = page.screenshot(full_page=True, type="png")
    except PlaywrightError:
        pass
    finally:
        context.close()
    result["duration_ms"] = int((time.monotonic() - started) * 1000)
    return result


def _fill_fields(page, scenario, row, line_number, used_values, stamp=None):
    from playwright.sync_api import Error as PlaywrightError

    placeholders = placeholder_values(line_number, stamp)
    for field in scenario.fields:
        source = field.get("source")
        if source not in ("column", "constant", "check"):
            continue
        label = field.get("label") or field.get("selector")
        locator = page.locator(field["selector"]).first
        try:
            if source == "check":
                _set_checked(locator, True)
                continue
            value = row.get(field["value"], "") if source == "column" else field.get("value", "")
            value = fill_placeholders(value, line_number, placeholders)
            if source == "column":
                used_values[field["value"]] = value
            if locator.count() and locator.is_disabled():
                # Өөр талбараас хамаарч идэвхждэг талбар (ж: ангилал сонгоход AJAX-аар ачаалагдах
                # дэд ангилал) — утга өгөх шаардлагатай бол идэвхжтэл нь богино хүлээнэ.
                if not value.strip() or value.strip() == _current_text(locator):
                    continue
                if not _wait_enabled(page, locator):
                    raise RowError(
                        _("'%(label)s' талбар идэвхгүй тул '%(value)s' утгыг оруулж чадсангүй.")
                        % {"label": label, "value": value[:60]}
                    )
            _fill(locator, field.get("kind"), value, field.get("type"))
            if field.get("kind") == "select" and value:
                page.wait_for_timeout(200)  # сонголтоос хамаарсан талбарууд шинэчлэгдэх хугацаа
        except PlaywrightError as exc:
            raise RowError(
                _("'%(label)s' талбарыг бөглөж чадсангүй: %(err)s") % {"label": label, "err": _short_error(exc)}
            )


def _wait_enabled(page, locator):
    deadline = time.monotonic() + DEPENDENT_TIMEOUT_MS / 1000
    while time.monotonic() < deadline:
        page.wait_for_timeout(200)
        if not locator.is_disabled():
            return True
    return False


_DATE_RE = re.compile(r"^(\d{4})[-./](\d{1,2})[-./](\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::\d{2}(?:\.\d+)?)?)?$")


def normalize_date(value, input_type):
    """
    Excel-ийн '2024-01-05 00:00:00', '2024.1.5' г.м. утгыг <input type=date|datetime-local|month>-ийн
    хүлээж авах хэлбэрт оруулна. Танихгүй бол өөрчлөхгүй (буруу огноог шалгах тест байж болно).
    """
    match = _DATE_RE.match(value.strip())
    if not match:
        return value
    year, month, day, hour, minute = match.groups()
    date = f"{year}-{int(month):02d}-{int(day):02d}"
    if input_type == "date":
        return date
    if input_type == "month":
        return date[:7]
    if input_type == "datetime-local":
        return f"{date}T{int(hour or 0):02d}:{minute or '00'}"
    return value


def _fill(locator, kind, value, input_type=""):
    if input_type in ("date", "datetime-local", "month"):
        value = normalize_date(value, input_type)
    if kind in ("checkbox", "radio"):
        if value.strip().lower() in TRUTHY:
            _set_checked(locator, True)
        elif kind == "checkbox":
            _set_checked(locator, False)
    elif kind == "select":
        if value:
            try:
                locator.select_option(label=value, timeout=ACTION_TIMEOUT_MS)
            except Exception:
                locator.select_option(value=value)
    else:
        locator.fill(value)


def _current_text(locator):
    """Талбарын одоогийн утга (select бол сонгосон сонголтын текст)."""
    return locator.evaluate(
        "el => (el.tagName === 'SELECT' ? (el.selectedOptions[0] || {}).text || '' : el.value || '').trim()"
    )


def _set_checked(locator, checked):
    try:
        locator.set_checked(checked)
    except Exception:
        # Загварчилсан (нуугдсан) checkbox — шууд утгыг нь тохируулж event өгнө.
        locator.evaluate(
            "(el, v) => { el.checked = v; el.dispatchEvent(new Event('input', {bubbles: true}));"
            " el.dispatchEvent(new Event('change', {bubbles: true})); }",
            checked,
        )


def _submit(page, scenario):
    from playwright.sync_api import Error as PlaywrightError

    selector = scenario.submit_selector or DEFAULT_SUBMIT_SELECTOR
    try:
        page.locator(selector).first.click()
    except PlaywrightError as exc:
        label = scenario.submit_label or _("илгээх")
        raise RowError(_("'%(label)s' товчийг дарж чадсангүй: %(err)s") % {"label": label, "err": _short_error(exc)})


def _settle(page):
    """Хуудас шилжих / AJAX хариу ирэхийг богино хугацаанд хүлээнэ."""
    page.wait_for_timeout(300)
    try:
        page.wait_for_load_state("networkidle", timeout=SETTLE_TIMEOUT_MS)
    except Exception:
        pass


# Түр гараад алга болдог мессеж (toast, snackbar, alert) — илгээсний дараа ажиглаж барина.
FLASH_JS = r"""
(s) => {
  const out = [];
  document.querySelectorAll(s.all).forEach(el => {
    const r = el.getBoundingClientRect(), st = getComputedStyle(el);
    if (!r.width || !r.height || st.visibility === 'hidden' || st.display === 'none') return;
    const text = (el.innerText || '').replace(/\s+/g, ' ').trim();
    if (!/[\p{L}\p{N}]/u.test(text)) return;
    const cls = el.getAttribute('class') || '';
    let kind = '';
    if (el.matches(s.success) || /success/i.test(cls)) kind = 'success';
    else if (el.matches(s.error) || /error|danger|fail/i.test(cls)) kind = 'error';
    if (kind) out.push([kind, text.slice(0, 300)]);
  });
  return out;
}
"""
FLASH_SELECTORS = {
    "all": ", ".join([
        "[role=alert]", "[role=status]", "[aria-live]", ".toast", ".alert", ".Toastify__toast", ".notification",
        ".snackbar", ".MuiSnackbar-root", ".ant-message-notice", ".swal2-popup", ".invalid-feedback", ".errorlist",
    ]),
    "error": PAGE_ERROR_SELECTORS,
    "success": SUCCESS_SELECTORS,
}


def _await_outcome(page):
    """
    Илгээсний дараа хариуг хүлээнэ: явагдаж буй хүсэлтүүдийг өөрөө тоолно (networkidle нь хуудас
    ачаалахад нэг л удаа болдог тул AJAX илгээлтийг хүлээдэггүй). Хүсэлт дуусаад хагас секунд
    чимээгүй болох, эсвэл мессеж гараад хагас секунд болоход зогсоно. Энэ хооронд 200ms тутам
    toast/alert-ийг цуглуулна — дараа нь алга болсон ч тооцогдоно. [(kind, text)] буцаана.
    """
    pending, last_activity = set(), [time.monotonic()]

    def request_started(request):
        pending.add(request)
        last_activity[0] = time.monotonic()

    def request_ended(request):
        pending.discard(request)
        last_activity[0] = time.monotonic()

    listeners = (("request", request_started), ("requestfinished", request_ended), ("requestfailed", request_ended))
    for event, handler in listeners:
        page.on(event, handler)
    seen, first_seen = [], None
    started = time.monotonic()
    try:
        page.wait_for_timeout(200)
        while time.monotonic() - started < SETTLE_TIMEOUT_MS / 1000:
            try:
                for kind, text in page.evaluate(FLASH_JS, FLASH_SELECTORS):
                    if (kind, text) not in seen:
                        seen.append((kind, text))
            except Exception:
                pass  # хуудас шилжиж байна
            now = time.monotonic()
            if seen and first_seen is None:
                first_seen = now
            quiet = not pending and now - last_activity[0] > 0.5
            if quiet or (first_seen and now - first_seen > 0.5 and not pending):
                break
            page.wait_for_timeout(200)
    finally:
        for event, handler in listeners:
            page.remove_listener(event, handler)
    try:
        page.wait_for_load_state("domcontentloaded", timeout=2000)
    except Exception:
        pass
    return seen


def _visible_texts(page, selector, exclude=None):
    """exclude-д таарах элементийг алгасна (ж: role=alert-тай амжилтын мессеж)."""
    texts = []
    try:
        for element in page.locator(selector).all()[:20]:
            if exclude and element.evaluate("(el, s) => el.matches(s)", exclude):
                continue
            if element.is_visible():
                text = " ".join(element.inner_text().split())
                # Заавал бөглөх талбарын улаан "*" (.text-danger) г.м. үсэг, тоогүй тэмдэг алдаа биш.
                if not any(ch.isalnum() for ch in text):
                    continue
                if text not in texts:
                    texts.append(text[:300])
    except Exception:
        pass
    return texts


def _read_outcome(page, scenario, start_url, invalid=(), flashes=()):
    """(амжилттай/алдаа/тодорхойгүй, мессеж, хуудасны текст). flashes — илгээсний дараа түр харагдсан мессежүүд."""
    url_changed = _strip_url(page.url) != _strip_url(start_url)
    left_form = url_changed and not _form_present(page, scenario)
    if scenario.error_selector:
        errors = _visible_texts(page, scenario.error_selector)
    elif left_form:
        # Формоос өөр хуудас руу шилжсэн (ж: нэвтэрсний дараах ticket жагсаалт) — тэнд байгаа
        # улаан текст (.text-danger, SLA ⚠) илгээлтийн алдаа биш. Зөвхөн тодорхой алдааны мессеж.
        errors = _visible_texts(page, PAGE_ERROR_SELECTORS, exclude=NOT_ERROR_SELECTORS)
    else:  # [role=alert]-ыг амжилт/мэдээллийн мессежид ч хэрэглэдэг (Bootstrap, Django messages)
        errors = _visible_texts(page, DEFAULT_ERROR_SELECTORS, exclude=NOT_ERROR_SELECTORS)
    if not url_changed:
        # Хуудас шилжээгүй бол browser-ийн өөрийн шалгалт илгээлтийг зогсоосон байж болно.
        # Шар анхааруулга ч татгалзсан гэсэн үг (ж: "олон удаа буруу оролдсон" түгжээ).
        errors = list(invalid) + errors + _visible_texts(page, WARNING_SELECTORS)
    successes = _visible_texts(page, SUCCESS_SELECTORS)
    if not scenario.error_selector:  # алга болсон toast-ыг нэмнэ (одоо харагдаж байгаа нь давхардахгүй)
        errors += [t for kind, t in flashes if kind == "error" and t not in errors]
    successes += [t for kind, t in flashes if kind == "success" and t not in successes]
    try:
        page_text = page.locator("body").inner_text()[:20_000]
    except Exception:
        page_text = ""
    page_text += "\n" + "\n".join(t for _kind, t in flashes)  # хүлээгдэх мессежийг toast-аас ч олно

    mode, value = scenario.success_mode, scenario.success_value.strip()
    if mode == "url_contains" and value:
        outcome = "success" if value.lower() in page.url.lower() else "error"
    elif mode == "text_visible" and value:
        outcome = "success" if value.lower() in page_text.lower() else "error"
    elif errors:
        outcome = "error"
    elif url_changed or successes:
        outcome = "success"
    else:
        outcome = "unknown"

    message = "; ".join(errors if outcome != "success" else successes)[:1000]
    return outcome, message, page_text


def _form_present(page, scenario):
    """Илгээсэн форм (сценарийн талбарууд) хуудсан дээр хэвээр байгаа эсэх."""
    selectors = [f["selector"] for f in scenario.fields if f.get("source") != "skip" and f.get("selector")]
    try:
        return any(page.locator(s).count() for s in selectors[:5])
    except Exception:
        return True


def _same_page(a, b):
    return _strip_url(a.split("?")[0]) == _strip_url(b.split("?")[0])


def _strip_url(url):
    return url.split("#")[0].rstrip("/")


def _save_result(run, line_number, row, result, secret_columns):
    data = dict(row)
    data.update(result["used_values"])
    for column in secret_columns:
        if data.get(column):
            data[column] = "***"
    item = RunResult(
        run=run,
        row_number=line_number,
        description=description_of(row),
        input_data=data,
        expected_outcome=result["expected_outcome"],
        expected_message=result["expected_message"],
        actual_outcome=result["actual_outcome"],
        actual_message=result["actual_message"],
        final_url=result["final_url"][:1000],
        verdict=result["verdict"],
        duration_ms=result["duration_ms"],
        response_detail=result.get("detail", ""),
    )
    if result["screenshot"]:
        item.screenshot.save(f"run{run.pk}_row{line_number}.png", ContentFile(result["screenshot"]), save=False)
    item.save()

    counter = {"pass": "passed", "fail": "failed", "error": "errored", "recorded": "recorded"}[item.verdict]
    setattr(run, counter, getattr(run, counter) + 1)
    run.save(update_fields=[counter, "updated_at"])


def _finish(run, status, error_message=""):
    run.status = status
    run.error_message = error_message
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "error_message", "finished_at", "updated_at"])
    return run


def _short_error(exc):
    """Playwright-ийн олон мөрт алдаанаас эхний утга учиртай мөрийг авна."""
    text = str(exc).strip().splitlines()
    first = text[0] if text else exc.__class__.__name__
    if "ERR_BLOCKED_BY_CLIENT" in first:
        return _("хаалттай хаяг руу хандах гэсэн (аюулгүй байдлын хязгаарлалт)")
    if "Timeout" in first:
        return _("хугацаа хэтэрлээ (элемент олдсонгүй эсвэл хуудас хариу өгсөнгүй)")
    return first[:300]
