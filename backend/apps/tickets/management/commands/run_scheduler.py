"""
SLA болон идэвхгүй ticket-ийн шалгалтуудыг тогтмол давтамжтай ажиллуулах энгийн
scheduler (cron-гүй орчинд — docker-compose-ийн `scheduler` service үүнийг ажиллуулна).

    python manage.py run_scheduler                 # 15 мин тутам SLA, 60 мин тутам stale
    python manage.py run_scheduler --once          # нэг удаа ажиллуулаад гарна
"""
import time

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import close_old_connections

JOBS = (
    # (командын нэр, хэдэн минут тутам)
    ("check_sla_deadlines", 15),
    ("check_stale_tickets", 60),
)


class Command(BaseCommand):
    help = "check_sla_deadlines (15 мин) болон check_stale_tickets (60 мин)-ийг тогтмол ажиллуулна."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Нэг удаа ажиллуулаад гарна.")

    def handle(self, *args, once=False, **options):
        last_run = {}
        while True:
            now = time.monotonic()
            for name, minutes in JOBS:
                if once or now - last_run.get(name, float("-inf")) >= minutes * 60:
                    close_old_connections()
                    try:
                        call_command(name, stdout=self.stdout)
                    except Exception as exc:  # нэг алдаанаас болж scheduler зогсохгүй
                        self.stderr.write(f"{name} алдаа: {exc}")
                    last_run[name] = now
            if once:
                return
            time.sleep(30)
