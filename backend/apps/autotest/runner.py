"""
Playwright (Chromium)-аар хуудас шалгах (PageScan) болон сценари ажиллуулах (TestRun).
Зөвхөн `run_autotest_worker` процессоос дуудагдана — вэб хүсэлт дотор browser нээхгүй.
"""
import queue
import threading
import time

from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone
from django.utils.translation import gettext as _

from .datafiles import DataFileError, description_of, fill_placeholders, judge, parse_expected, read_rows
from .models import PageScan, RunResult, TestRun
from .safety import UnsafeURL, check_url

NAV_TIMEOUT_MS = 30_000
ACTION_TIMEOUT_MS = 8_000
SETTLE_TIMEOUT_MS = 8_000

DEFAULT_ERROR_SELECTORS = ", ".join([
    ".error", ".errors", ".errorlist", ".error-message", ".error-text", ".field-error",
    ".form-error", ".invalid-feedback", ".alert-danger", ".alert-error", ".text-danger",
    ".has-error .help-block", "[role=alert]", "[aria-live=assertive]", ".toast-error",
    ".ant-form-item-explain-error", ".Mui-error", ".v-messages__message", ".parsley-errors-list",
])
SUCCESS_SELECTORS = ", ".join([
    ".alert-success", ".success", ".success-message", ".toast-success", "[role=status]",
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
  const quote = v => '"' + String(v).replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';
  const text = el => (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();

  function selectorFor(el) {
    const tag = el.tagName.toLowerCase();
    if (el.id && unique('#' + CSS.escape(el.id))) return '#' + CSS.escape(el.id);
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
    if (el.placeholder) return el.placeholder.trim();
    const prev = el.previousElementSibling;
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
      options: el.tagName === 'SELECT' ? [...el.options].map(o => o.text.trim()).filter(Boolean).slice(0, 50) : [],
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

# Browser-ийн өөрийн (HTML5) шалгалтад унасан талбаруудын мессеж.
INVALID_JS = """
() => [...document.querySelectorAll('input, select, textarea')]
  .filter(el => el.willValidate && !el.checkValidity())
  .map(el => el.validationMessage).filter(Boolean)
"""


class RowError(Exception):
    """Мөрийг ажиллуулж чадаагүй (талбар олдоогүй г.м.) — хэрэглэгчид харуулах мессежтэй."""


def launch_browser(playwright):
    try:
        return playwright.chromium.launch(headless=True)
    except Exception:
        # Playwright-ийн Chromium татагдаагүй бол системийн Google Chrome-ийг ашиглана.
        return playwright.chromium.launch(headless=True, channel="chrome")


def _new_context(browser):
    context = browser.new_context(
        locale="mn-MN", ignore_https_errors=True, viewport={"width": 1280, "height": 900}
    )
    context.set_default_timeout(ACTION_TIMEOUT_MS)
    return context


# --- PageScan ---------------------------------------------------------------

def execute_scan(scan):
    from playwright.sync_api import Error as PlaywrightError

    try:
        check_url(scan.url)
        scan.result = _in_browser_thread(_scan_page, scan.url)
        scan.status = PageScan.Status.DONE
        if not scan.result.get("fields"):
            scan.error_message = _("Энэ хуудсанд бөглөх талбар олдсонгүй.")
    except UnsafeURL as exc:
        scan.status, scan.error_message = PageScan.Status.FAILED, str(exc)
    except PlaywrightError as exc:
        scan.status = PageScan.Status.FAILED
        scan.error_message = _("Хуудсыг нээж чадсангүй: %(err)s") % {"err": _short_error(exc)}
    scan.save()


def _scan_page(url):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = launch_browser(playwright)
        try:
            page = _new_context(browser).new_page()
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
    scenario = run.scenario
    try:
        rows = _load_rows(run)
        check_url(run.target_url)
    except (DataFileError, UnsafeURL) as exc:
        return _finish(run, TestRun.Status.FAILED, str(exc))

    run.total = len(rows)
    run.save(update_fields=["total", "updated_at"])
    secret_columns = scenario.secret_columns()
    delay = getattr(settings, "AUTOTEST_ROW_DELAY_MS", 300) / 1000

    results, stop = queue.Queue(), threading.Event()
    browser_thread = threading.Thread(
        target=_browse_rows, args=(scenario, run.target_url, rows, delay, results, stop), daemon=True
    )
    browser_thread.start()
    status = TestRun.Status.DONE
    try:
        while True:
            item = results.get()
            if item is _FINISHED:
                break
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
    return _finish(run, status)


_FINISHED = object()


def _browse_rows(scenario, url, rows, delay, results, stop):
    """Browser thread: DB-д хандахгүй, зөвхөн үр дүнг дараалалд хийнэ."""
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as playwright:
            browser = launch_browser(playwright)
            try:
                for index, (line_number, row) in enumerate(rows):
                    if stop.is_set():
                        break
                    if index and delay:
                        time.sleep(delay)
                    results.put((line_number, row, run_row(browser, scenario, url, row, line_number)))
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
            _, rows = read_rows(fh, data_file.file.name)
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


def run_row(browser, scenario, url, row, line_number):
    """Нэг мөрийг шинэ (cookie-гүй) browser context дээр ажиллуулж, dict буцаана."""
    from playwright.sync_api import Error as PlaywrightError

    expected_outcome, expected_message = _expected_for(scenario, row)
    result = {
        "expected_outcome": expected_outcome, "expected_message": expected_message,
        "actual_outcome": "", "actual_message": "", "final_url": "",
        "used_values": {}, "screenshot": None,
    }
    started = time.monotonic()
    context = _new_context(browser)
    page = context.new_page()
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)
        _settle(page)
        start_url = page.url
        _fill_fields(page, scenario, row, line_number, result["used_values"])
        _submit(page, scenario)
        _settle(page)
        outcome, message, page_text = _read_outcome(page, scenario, start_url)
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


def _fill_fields(page, scenario, row, line_number, used_values):
    from playwright.sync_api import Error as PlaywrightError

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
            value = fill_placeholders(value, line_number)
            if source == "column":
                used_values[field["value"]] = value
            _fill(locator, field.get("kind"), value)
        except PlaywrightError as exc:
            raise RowError(
                _("'%(label)s' талбарыг бөглөж чадсангүй: %(err)s") % {"label": label, "err": _short_error(exc)}
            )


def _fill(locator, kind, value):
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

    selector = scenario.submit_selector or "form [type=submit], button[type=submit], input[type=submit]"
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


def _visible_texts(page, selector):
    texts = []
    try:
        for element in page.locator(selector).all()[:20]:
            if element.is_visible():
                text = " ".join(element.inner_text().split())
                if text and text not in texts:
                    texts.append(text[:300])
    except Exception:
        pass
    return texts


def _read_outcome(page, scenario, start_url):
    """(амжилттай/алдаа/тодорхойгүй, мессеж, хуудасны текст)."""
    url_changed = _strip_url(page.url) != _strip_url(start_url)
    errors = _visible_texts(page, scenario.error_selector or DEFAULT_ERROR_SELECTORS)
    if not url_changed:
        # Хуудас шилжээгүй бол browser-ийн өөрийн шалгалт (required, type=email) илгээлтийг зогсоосон байж болно.
        errors = page.evaluate(INVALID_JS) + errors
    successes = _visible_texts(page, SUCCESS_SELECTORS)
    try:
        page_text = page.locator("body").inner_text()[:20_000]
    except Exception:
        page_text = ""

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
    if "Timeout" in first:
        return _("хугацаа хэтэрлээ (элемент олдсонгүй эсвэл хуудас хариу өгсөнгүй)")
    return first[:300]
