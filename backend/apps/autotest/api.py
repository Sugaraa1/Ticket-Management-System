"""
API сценари: файлын мөр бүрээр нэг HTTP хүсэлт илгээж, status код / хариуг хүлээгдэх үр дүнтэй
тулгана. Browser хэрэггүй (стандарт urllib) ч вэб тесттэй адил worker-ийн дарааллаар ажиллана.
Хүсэлт, redirect бүрийг safety.check_url шалгана — тест зөвхөн зөвшөөрөгдсөн хаяг руу хандана.

Загварт {{багана}} нь файлын нүдний утга, {{random}} / {{run}} ... нь datafiles-ийн placeholder.
JSON body-д утгыг JSON-оор escape хийж орлуулна — хашилтыг QA өөрөө сонгоно:
    {"email": "{{email}}", "age": {{age}}}  →  {"email": "a@b.mn", "age": 25}
"""
import http.cookiejar
import json
import re
import socket
import ssl
import time
import urllib.error
import urllib.request
from urllib.parse import quote, urljoin

from django.conf import settings
from django.utils.translation import gettext as _

from .datafiles import (
    DataFileError, _key, _norm_text, fill_placeholders, parse_expected, placeholder_values, run_stamp,
)
from .models import RunResult, TestRun
from .runner import LoginFailed, RowError, _finish, _load_rows, _login_of, _save_result
from .safety import UnsafeURL, check_url

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
TIMEOUT_SECONDS = 30
MAX_REDIRECTS = 5
MAX_RESPONSE_BYTES = 512 * 1024
DETAIL_BODY_CHARS = 20_000
BUILTIN_PLACEHOLDERS = {"random", "timestamp", "row", "run", "digits"}
TEMPLATE_RE = re.compile(r"\{\{\s*([^{}]+?)\s*\}\}")
# Нэвтрэх хариунаас token хайх түлхүүрүүд (эхэлж таарсныг авна): JWT, DRF, OAuth ...
TOKEN_KEYS = ("access_token", "accessToken", "access", "token", "jwt", "id_token", "key")
SECRET_HINTS = ("password", "passwd", "pwd", "нууцүг", "token", "secret")
# urllib-ийн анхдагч "Python-urllib/3.x"-ийг Cloudflare г.м. хамгаалалт bot гэж 403-аар хаадаг.
USER_AGENT = "TMS-Autotest/1.0"
STATUS_RE = re.compile(r"[1-5]\d\d")


class TemplateError(ValueError):
    pass


# --- Загвар ------------------------------------------------------------------

def template_columns(*texts):
    """Загваруудад ашигласан файлын баганууд (placeholder-оос бусад), дарааллаараа."""
    columns = []
    for text in texts:
        for match in TEMPLATE_RE.finditer(text or ""):
            name = match.group(1)
            if name not in BUILTIN_PLACEHOLDERS and name not in columns:
                columns.append(name)
    return columns


def is_secret_column(name):
    key = _key(name)
    return any(hint in key for hint in SECRET_HINTS)


def render(text, values, mode="raw"):
    """mode: json — JSON string-ийн доторх escape, url — percent-encode, raw — өөрчлөхгүй."""
    def replace(match):
        name = match.group(1)
        if name not in values:
            raise TemplateError(_("'%(name)s' багана файлд алга.") % {"name": name})
        value = values[name]
        if mode == "json":
            return json.dumps(value, ensure_ascii=False)[1:-1]
        if mode == "url":
            return quote(value, safe="")
        return value

    return TEMPLATE_RE.sub(replace, text or "")


def parse_headers(text):
    """'Нэр: утга' мөрүүд → [(нэр, утга)]. Буруу мөр байвал ValueError."""
    headers = []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        name, sep, value = line.partition(":")
        name = name.strip()
        if not sep or not name or not re.fullmatch(r"[A-Za-z0-9!#$%&'*+.^_`|~-]+", name):
            raise ValueError(_("Header буруу: '%(line)s' — 'Нэр: утга' хэлбэрээр бичнэ үү.") % {"line": line.strip()[:80]})
        headers.append((name, value.strip()))
    return headers


def body_mode(headers):
    content_type = next((v for k, v in headers if k.lower() == "content-type"), "application/json").lower()
    if "json" in content_type:
        return "json"
    if "x-www-form-urlencoded" in content_type:
        return "url"
    return "raw"


def check_body_template(body, headers):
    """Хадгалахаас өмнө: placeholder бүрийг 1 гэж орлуулахад JSON зөв байх ёстой."""
    if not body.strip() or body_mode(headers) != "json":
        return
    try:
        json.loads(TEMPLATE_RE.sub("1", body))
    except ValueError as exc:
        raise ValueError(_("Body зөв JSON биш байна: %(err)s") % {"err": exc})


# --- Хүлээгдэх үр дүн ----------------------------------------------------------

def parse_expected_api(text):
    """'201' / '400: мессеж' / 'амжилттай' / 'алдаа: мессеж' → (outcome, status | None, мессеж)."""
    head, _sep, rest = (text or "").strip().partition(":")
    if STATUS_RE.fullmatch(head.strip()):
        status = int(head)
        return ("success" if status < 400 else "error"), status, rest.strip()
    outcome, message = parse_expected(text)
    return (outcome or ""), None, message


def judge_api(expected_outcome, expected_status, expected_message, status, body):
    if not expected_outcome and not expected_message:
        return RunResult.Verdict.RECORDED
    if expected_status and expected_status != status:
        return RunResult.Verdict.FAIL
    if expected_outcome and expected_outcome != ("success" if status < 400 else "error"):
        return RunResult.Verdict.FAIL
    if expected_message and _norm_text(expected_message) not in _norm_text(body):
        return RunResult.Verdict.FAIL
    return RunResult.Verdict.PASS


# --- HTTP ---------------------------------------------------------------------

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Redirect-ийг Client өөрөө дагана — шинэ хаяг бүрийг check_url-аар шалгахын тулд."""
    def redirect_request(self, *args, **kwargs):
        return None


class Client:
    """Нэг ажиллуулалтын HTTP session: cookie, нэвтэрсэн token-ийг мөр хооронд хадгална."""

    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.auth = ""
        context = ssl.create_default_context()
        context.check_hostname, context.verify_mode = False, ssl.CERT_NONE  # staging-ийн self-signed сертификат
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), _NoRedirect, urllib.request.HTTPCookieProcessor(self.jar),
            urllib.request.HTTPSHandler(context=context),
        )

    def _cookie(self, name):
        return next((c.value for c in self.jar if c.name == name), "")

    def send(self, method, url, headers, body=None):
        """(status, хариуны header, bytes, эцсийн url). Сүлжээний алдааг RowError болгоно."""
        headers = dict(headers)
        names = {k.lower() for k in headers}
        if self.auth and "authorization" not in names:
            headers["Authorization"] = self.auth
        if "user-agent" not in names:
            headers["User-Agent"] = USER_AGENT
        for _attempt in range(MAX_REDIRECTS + 1):
            try:
                check_url(url)
            except UnsafeURL as exc:
                raise RowError(str(exc))
            request_headers = dict(headers)
            csrf = self._cookie("csrftoken")
            if csrf and method not in ("GET", "HEAD") and "x-csrftoken" not in names:
                request_headers.update({"X-CSRFToken": csrf, "Referer": url})  # Django session API
            request = urllib.request.Request(url, data=body, method=method, headers=request_headers)
            try:
                try:
                    response = self.opener.open(request, timeout=TIMEOUT_SECONDS)
                except urllib.error.HTTPError as exc:  # 3xx/4xx/5xx — энэ ч хариу
                    response = exc
                status, response_headers = response.status, response.headers
                data = response.read(MAX_RESPONSE_BYTES)
            except (socket.timeout, TimeoutError):
                raise RowError(_("хугацаа хэтэрлээ (%(n)s сек хариу ирсэнгүй)") % {"n": TIMEOUT_SECONDS})
            except urllib.error.URLError as exc:
                raise RowError(_("Холбогдож чадсангүй: %(err)s") % {"err": exc.reason})
            except (ValueError, OSError) as exc:  # header-т мөр шилжилт, эвдэрсэн хаяг ...
                raise RowError(_("Хүсэлт илгээж чадсангүй: %(err)s") % {"err": exc})
            location = response_headers.get("Location")
            if status in (301, 302, 303, 307, 308) and location:
                url = urljoin(url, location)
                if status == 303 or (status in (301, 302) and method != "GET"):
                    method, body = "GET", None
                continue
            return status, response_headers, data, url
        raise RowError(_("Хэт олон redirect."))


def _decode(data, headers):
    charset = headers.get_content_charset() if headers else None
    return data.decode(charset or "utf-8", errors="replace")


def _find_token(data, depth=0):
    if not isinstance(data, dict) or depth > 2:
        return ""
    for key in TOKEN_KEYS:
        if isinstance(data.get(key), str) and data[key]:
            return data[key]
    for value in data.values():
        token = _find_token(value, depth + 1)
        if token:
            return token
    return ""


def _snippet(text, limit=300):
    return " ".join(text.split())[:limit]


def login(client, login_url, username, password, body_template, token_prefix):
    """Нэвтрэх замд POST хийж, хариуны token-ийг (байхгүй бол cookie-г) client-д үлдээнэ."""
    try:
        body = render(body_template or '{"username": "{{username}}", "password": "{{password}}"}',
                      {"username": username, "password": password}, "json")
        status, headers, data, _url = client.send(
            "POST", login_url, {"Content-Type": "application/json", "Accept": "application/json"}, body.encode()
        )
    except (TemplateError, RowError) as exc:
        raise LoginFailed(_("API-д нэвтэрч чадсангүй: %(err)s") % {"err": exc})
    text = _decode(data, headers)
    if status >= 400:
        raise LoginFailed(
            _("'%(user)s' хэрэглэгчээр API-д нэвтэрч чадсангүй: HTTP %(status)s %(body)s")
            % {"user": username, "status": status, "body": _snippet(text, 200)}
        )
    try:
        token = _find_token(json.loads(text))
    except ValueError:
        token = ""
    if token:
        client.auth = f"{token_prefix} {token}".strip()
    elif not len(client.jar):
        raise LoginFailed(_("API нэвтрэх хариунд token ч, cookie ч ирсэнгүй (HTTP %(status)s).") % {"status": status})


# --- Мөр ажиллуулах --------------------------------------------------------------

def _shell_quote(text):
    return "'" + text.replace("'", "'\\''") + "'"


def _curl(method, url, headers, body):
    parts = [f"curl -X {method} {_shell_quote(url)}"]
    parts += [f"-H {_shell_quote(f'{k}: {v}')}" for k, v in headers]
    if body:
        parts.append(f"--data {_shell_quote(body)}")
    return " \\\n  ".join(parts)


def _pretty(text):
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, indent=2)[:DETAIL_BODY_CHARS]
    except ValueError:
        return text[:DETAIL_BODY_CHARS]


def _mask(text, secrets):
    for secret in secrets:
        if len(secret) >= 4:
            text = text.replace(secret, "***")
    return text


def run_row(client, scenario, url_template, row, line_number, stamp=None, secret_columns=()):
    raw = row.get(scenario.expected_column, "") if scenario.expected_column else ""
    expected_outcome, expected_status, expected_message = parse_expected_api(raw)
    if scenario.expected_message_column and row.get(scenario.expected_message_column):
        expected_message = row[scenario.expected_message_column]
    shown_expected = " · ".join(filter(None, [f"HTTP {expected_status}" if expected_status else "", expected_message]))
    result = {
        "expected_outcome": expected_outcome, "expected_message": shown_expected,
        "actual_outcome": "", "actual_message": "", "final_url": "", "used_values": {}, "screenshot": None,
        "detail": "",
    }
    placeholders = placeholder_values(line_number, stamp)
    values = {k: fill_placeholders(v, line_number, placeholders) for k, v in row.items()}
    values.update(placeholders)
    result["used_values"] = {c: values[c] for c in scenario.required_columns() if c in row and values[c] != row[c]}
    secrets = [values[c] for c in secret_columns if values.get(c)]
    if client.auth:
        secrets.append(client.auth.split()[-1])
    started = time.monotonic()
    method = scenario.api_method
    try:
        try:
            url = quote(render(url_template, values, "url"), safe=":/?#[]@!$&'()*+,;=%")
            headers = parse_headers(render(scenario.api_headers, values, "raw"))
            body = ""
            if scenario.api_body.strip():
                mode = body_mode(headers)
                body = render(scenario.api_body, values, mode)
                if mode == "json":
                    try:
                        json.loads(body)
                    except ValueError as exc:
                        raise RowError(_("Утга орлуулсны дараа body зөв JSON биш болсон: %(err)s") % {"err": exc})
                if not any(k.lower() == "content-type" for k, _v in headers):
                    headers.append(("Content-Type", "application/json"))
        except (TemplateError, ValueError) as exc:
            raise RowError(str(exc))
        if not any(k.lower() == "accept" for k, _v in headers):
            headers.append(("Accept", "application/json"))
        shown_headers = headers + ([("Authorization", client.auth)] if client.auth else [])
        result["final_url"] = url
        result["detail"] = _curl(method, url, shown_headers, body)
        status, response_headers, data, final_url = client.send(method, url, headers, body.encode() if body else None)
        text = _decode(data, response_headers)
        snippet = _snippet(text)
        result.update(
            actual_outcome="success" if status < 400 else "error",
            actual_message=f"HTTP {status}" + (f" — {snippet}" if snippet else ""),
            final_url=final_url,
            verdict=judge_api(expected_outcome, expected_status, expected_message, status, text),
        )
        result["detail"] += f"\n\n→ HTTP {status}\n{_pretty(text)}"
    except RowError as exc:
        result.update(verdict=RunResult.Verdict.ERROR, actual_message=str(exc))
    result["duration_ms"] = int((time.monotonic() - started) * 1000)
    result["detail"] = _mask(result["detail"], secrets)
    result["actual_message"] = _mask(result["actual_message"], secrets)
    return result


def execute_run(run):
    """runner.execute_run-оос дуудагдана (API сценари). Browser-гүй тул DB-тэй нэг thread-д."""
    scenario = run.scenario
    client = Client()
    try:
        rows = _load_rows(run)
        credentials = _login_of(run)
        check_url(run.target_url)
        if credentials:
            app = scenario.app
            login(client, *credentials, app.api_login_body, app.api_token_prefix)
    except (DataFileError, UnsafeURL, LoginFailed) as exc:
        return _finish(run, TestRun.Status.FAILED, str(exc))

    run.total = len(rows)
    run.save(update_fields=["total", "updated_at"])
    secret_columns = scenario.secret_columns()
    delay = getattr(settings, "AUTOTEST_ROW_DELAY_MS", 300) / 1000
    stamp = run_stamp()
    status = TestRun.Status.DONE
    for index, (line_number, row) in enumerate(rows):
        if index and delay:
            time.sleep(delay)
        result = run_row(client, scenario, run.target_url, row, line_number, stamp, secret_columns)
        _save_result(run, line_number, row, result, secret_columns)
        if TestRun.objects.filter(pk=run.pk, status=TestRun.Status.CANCELLED).exists():
            status = TestRun.Status.CANCELLED
            break
    return _finish(run, status)
