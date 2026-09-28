"""
Тест бүрийг дугаарлаж, аль хэсгийг юуг шалгасныг нь дэлгэрэнгүй хэвлэдэг test runner.

    [  1/221] ✅ PASS   Categories/Teams › CategoryDeleteTests › pm cannot delete  (0.02s)
    [  2/221] ❌ FAIL   Tickets › ReviewFixTests › team qa can close  (0.05s)

Тестийн docstring байвал түүний эхний мөрийг тайлбар болгоно, үгүй бол нэрээс нь гаргана.
Дуусахад хэсэг тус бүрийн дүн хэвлэж, бүх гаралтыг test-logs/<огноо>_<PASS|FAIL>.log-д хадгална
(хамгийн сүүлийн 5-ыг үлдээнэ — settings.TEST_LOG_KEEP-ээр өөрчилнө).
"""
import time
import unittest
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.test.runner import DiscoverRunner

# Өөр төсөлд settings.TEST_SECTION_NAMES = {"app_label": "Харуулах нэр"} гэж өөрчилж болно.
DEFAULT_SECTION_NAMES = {
    "accounts": "Accounts",
    "categories": "Categories/Teams",
    "core": "Core",
    "projects": "Projects",
    "tickets": "Tickets",
    "autotest": "Автомат тест",
    "e2e": "E2E (browser)",
}

STATUS_LABELS = {
    "pass": "✅ PASS ",
    "fail": "❌ FAIL ",
    "error": "💥 ERROR",
    "skip": "⏭️ SKIP ",
    "xfail": "✅ XFAIL",
    "xpass": "❌ XPASS",
}


def describe(test):
    """(хэсэг, тайлбар) — ж: ("Ангилал / Баг", "CategoryDeleteTests › pm cannot delete")."""
    module = type(test).__module__.split(".")
    app = module[1] if module[0] == "apps" and len(module) > 1 else module[0]
    names = getattr(settings, "TEST_SECTION_NAMES", DEFAULT_SECTION_NAMES)
    section = names.get(app, app)
    method = getattr(test, "_testMethodName", str(test))
    doc = (getattr(test, "_testMethodDoc", None) or "").strip().splitlines()
    text = doc[0] if doc else method.removeprefix("test_").replace("_", " ")
    return section, f"{type(test).__name__} › {text}"


class DetailedTestResult(unittest.TextTestResult):
    total = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.index = 0
        self.lines = []
        self.sections = defaultdict(lambda: defaultdict(int))
        self._started = {}

    def startTest(self, test):
        self._started[test.id()] = time.monotonic()
        unittest.TestResult.startTest(self, test)  # TextTestResult-ийн "..." хэвлэлтийг алгасна

    def _report(self, test, status):
        self.index += 1
        section, text = describe(test)
        self.sections[section][status] += 1
        elapsed = time.monotonic() - self._started.pop(test.id(), time.monotonic())
        width = len(str(self.total or self.index))
        # --parallel горимд үр дүн дараа нь нэг дор ирдэг тул хугацаа хэмжигдэхгүй — харуулахгүй.
        timing = f"  ({elapsed:.2f}s)" if elapsed >= 0.005 else ""
        line = (
            f"[{self.index:>{width}}/{self.total or '?'}] {STATUS_LABELS[status]}  "
            f"{section} › {text}{timing}"
        )
        self.lines.append(line)
        self.stream.writeln(line)
        self.stream.flush()

    # TextTestResult-ийн өөрийн хэвлэлтийг алгасахын тулд unittest.TestResult-ийг шууд дуудна.
    def addSuccess(self, test):
        unittest.TestResult.addSuccess(self, test)
        self._report(test, "pass")

    def addFailure(self, test, err):
        unittest.TestResult.addFailure(self, test, err)
        self._report(test, "fail")

    def addError(self, test, err):
        unittest.TestResult.addError(self, test, err)
        self._report(test, "error")

    def addSubTest(self, test, subtest, err):
        # subTest унавал unittest addFailure/addSuccess-ийг дууддаггүй — тестийг нэг л удаа FAIL гэж тоолно.
        unittest.TestResult.addSubTest(self, test, subtest, err)
        if err is not None and test.id() in self._started:
            is_failure = issubclass(err[0], test.failureException)
            self._report(test, "fail" if is_failure else "error")

    def addSkip(self, test, reason):
        unittest.TestResult.addSkip(self, test, reason)
        self._report(test, "skip")

    def addExpectedFailure(self, test, err):
        unittest.TestResult.addExpectedFailure(self, test, err)
        self._report(test, "xfail")

    def addUnexpectedSuccess(self, test):
        unittest.TestResult.addUnexpectedSuccess(self, test)
        self._report(test, "xpass")

    def summary_lines(self):
        lines = ["", "Summary by section:"]
        for section, counts in sorted(self.sections.items()):
            ok = counts["pass"] + counts["xfail"]
            bad = counts["fail"] + counts["error"] + counts["xpass"]
            mark = "✅" if not bad else "❌"
            extra = f", {bad} failed" if bad else ""
            extra += f", {counts['skip']} skipped" if counts["skip"] else ""
            lines.append(f"  {mark} {section}: {ok}/{sum(counts.values())} passed{extra}")
        return lines


class DetailedTestRunner(DiscoverRunner):
    def get_resultclass(self):
        # --debug-sql / --pdb горимд Django-гийн өөрийн result класс хэрэгтэй.
        return super().get_resultclass() or DetailedTestResult

    def run_suite(self, suite, **kwargs):
        DetailedTestResult.total = suite.countTestCases()
        self._started_at = datetime.now()
        result = super().run_suite(suite, **kwargs)
        if isinstance(result, DetailedTestResult):
            self._finish(result)
        return result

    def _finish(self, result):
        summary = result.summary_lines()
        for line in summary:
            result.stream.writeln(line)

        status = "PASS" if result.wasSuccessful() else "FAIL"
        failed = len(result.failures) + len(result.errors) + len(result.unexpectedSuccesses)
        headline = (
            f"{'✅' if status == 'PASS' else '❌'} {status}: "
            f"{result.testsRun - failed}/{result.testsRun} passed"
            f"{f', {failed} failed' if failed else ''} "
            f"({(datetime.now() - self._started_at).total_seconds():.1f}s)"
        )
        result.stream.writeln(headline)

        log_dir = Path(settings.BASE_DIR) / "test-logs"
        log_dir.mkdir(exist_ok=True)
        path = log_dir / f"{self._started_at:%Y-%m-%d_%H-%M-%S}_{status}.log"
        details = [
            f"{kind}: {test.id()}\n{trace}"
            for kind, items in (("FAIL", result.failures), ("ERROR", result.errors))
            for test, trace in items
        ]
        path.write_text(
            "\n".join([headline, "", *result.lines, *summary, "", *details]) + "\n",
            encoding="utf-8",
        )
        # Хамгийн сүүлийн TEST_LOG_KEEP (анхдагч 5) файлыг л үлдээж, хуучнуудыг устгана.
        keep = getattr(settings, "TEST_LOG_KEEP", 5)
        for old in sorted(log_dir.glob("*.log"), reverse=True)[keep:]:
            old.unlink(missing_ok=True)
        result.stream.writeln(f"Log: {path}")
