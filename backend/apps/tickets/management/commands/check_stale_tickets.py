"""
Zendesk/Jira-ийн "time-based automation"-той адил: идэвхтэй (хаагдаагүй/
татгалзаагүй) ticket бүрийн сүүлийн идэвхээс хойш хэдэн цаг өнгөрснийг шалгаж,
settings.STALE_TICKET_REMINDER_HOURS хугацаанд юу ч болоогүй бол хариуцагчид
(эсвэл байхгүй бол Team Lead-д) сануулга илгээнэ.

Ganц удаагийн SLA escalation-оос ялгаатай нь: идэвх гарахгүй л бол ижил
хугацаа тутамд ДАХИН давтан илгээгдэнэ ("N цаг хариугүй бол дахин мэдэгдэх").

Периодоор ажиллуулах ёстой (жишээ нь 15 минут тутамд cron-оор):
    */15 * * * * cd /path/to/backend && venv/bin/python manage.py check_stale_tickets
"""
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.tickets.models import Ticket
from apps.tickets.notifications import notify_stale_ticket_reminder


class Command(BaseCommand):
    help = (
        "Идэвхгүй байдал үргэлжилж буй ticket-үүдэд давтан сануулга илгээнэ "
        "(settings.STALE_TICKET_REMINDER_HOURS)."
    )

    def handle(self, *args, **options):
        now = timezone.now()
        threshold_hours = settings.STALE_TICKET_REMINDER_HOURS
        tickets = Ticket.objects.exclude(
            status__in=Ticket._SLA_EXEMPT_STATUSES
        ).select_related("assigned_to", "team", "team__team_lead")

        reminders_sent = 0

        for ticket in tickets:
            last_activity = ticket.last_activity_at or ticket.created_at
            idle_hours = (now - last_activity).total_seconds() / 3600
            if idle_hours < threshold_hours:
                continue

            if ticket.stale_reminder_sent_at is not None:
                hours_since_reminder = (
                    now - ticket.stale_reminder_sent_at
                ).total_seconds() / 3600
                if hours_since_reminder < threshold_hours:
                    continue

            notify_stale_ticket_reminder(ticket, idle_hours=int(idle_hours))
            Ticket.objects.filter(pk=ticket.pk).update(stale_reminder_sent_at=now)
            reminders_sent += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Идэвхгүй ticket-ийн шалгалт дууслаа: {reminders_sent} сануулга илгээв."
            )
        )
