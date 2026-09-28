"""
Автомат тестийн дарааллыг (хуудас шалгах, сценари ажиллуулах) гүйцэтгэх worker.
docker-compose-ийн `autotest_worker` service үүнийг ажиллуулна (Chromium зөвхөн тэнд суусан).

    python manage.py run_autotest_worker           # дараалал хүлээж тасралтгүй ажиллана
    python manage.py run_autotest_worker --once    # байгаа ажлуудыг дуусгаад гарна
"""
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.autotest.models import PageScan, TestRun

IDLE_SLEEP_SECONDS = 2


class Command(BaseCommand):
    help = "Автомат тестийн дараалалд байгаа ажлуудыг Playwright-аар гүйцэтгэнэ."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Байгаа ажлуудыг дуусгаад гарна.")

    def handle(self, *args, once=False, **options):
        from apps.autotest import runner

        if not once:
            self._fail_interrupted_runs()
        while True:
            close_old_connections()
            job = self._claim_scan() or self._claim_run()
            if job is None:
                if once:
                    return
                time.sleep(IDLE_SLEEP_SECONDS)
                continue
            try:
                if isinstance(job, PageScan):
                    runner.execute_scan(job)
                else:
                    self.stdout.write(f"Run #{job.pk}: {job.scenario} ({job.data_file_name})")
                    runner.execute_run(job)
                    self.stdout.write(f"Run #{job.pk}: {job.status} {job.passed}/{job.total}")
            except Exception as exc:  # нэг ажлын алдаанаас болж worker зогсохгүй
                self.stderr.write(f"{job!r} алдаа: {exc}")
                self._mark_failed(job, exc)

    def _claim_scan(self):
        # Хуудас шалгах нь QA дэлгэцийн өмнө хүлээж байгаа тул түрүүлж хийнэ.
        scan = PageScan.objects.filter(status=PageScan.Status.QUEUED).order_by("created_at").first()
        return scan

    def _claim_run(self):
        for run in TestRun.objects.filter(status=TestRun.Status.QUEUED).order_by("created_at")[:5]:
            # Олон worker зэрэг ажиллавал нэг run-ийг хоёр удаа авахаас сэргийлнэ.
            if TestRun.objects.filter(pk=run.pk, status=TestRun.Status.QUEUED).update(
                status=TestRun.Status.RUNNING
            ):
                run.status = TestRun.Status.RUNNING
                return run
        return None

    def _mark_failed(self, job, exc):
        if isinstance(job, PageScan):
            job.status, job.error_message = PageScan.Status.FAILED, str(exc)[:500]
            job.save()
        else:
            job.status, job.error_message = TestRun.Status.FAILED, str(exc)[:500]
            job.finished_at = timezone.now()
            job.save()

    def _fail_interrupted_runs(self):
        """Worker дахин асахад өмнө нь тасарсан (running хэвээр үлдсэн) ажлуудыг хаана."""
        TestRun.objects.filter(status=TestRun.Status.RUNNING).update(
            status=TestRun.Status.FAILED,
            error_message=_("Worker дахин эхэлсэн тул ажиллуулалт тасарсан. Дахин ажиллуулна уу."),
            finished_at=timezone.now(),
        )
