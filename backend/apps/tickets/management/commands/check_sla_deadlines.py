"""
Jira Service Management-ийн SLA policy-той адил: идэвхтэй (хаагдаагүй/татгалзаагүй)
бүх ticket-ийн 2 SLA metric-ийг (Time to First Response, Time to Resolution) шалгаж,
хугацаа дуусахад ойртсон/хэтэрсэн тохиолдолд холбогдох хэрэглэгчдэд email мэдэгдэл
(анхааруулга эсвэл escalation) илгээнэ.

Периодоор ажиллуулах ёстой (жишээ нь 15 минут тутамд cron-оор):
    */15 * * * * cd /path/to/backend && venv/bin/python manage.py check_sla_deadlines

Тухайн ticket бүрд давхар мэдэгдэл илгээхээс сэргийлэхийн тулд
sla_warning_sent_at / sla_breach_notified_at (мөн first_response-ийн хос) талбаруудыг
ашиглана — эдгээр нь аль хэдийн бичигдсэн бол дахин илгээхгүй.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.tickets.models import Ticket
from apps.tickets.notifications import (
    notify_first_response_breach,
    notify_first_response_warning,
    notify_resolution_breach,
    notify_resolution_warning,
)


class Command(BaseCommand):
    help = (
        "SLA (Time to First Response / Time to Resolution) хугацаанд ойртсон эсвэл "
        "хэтэрсэн ticket-үүдийг шалгаж, анхааруулга/escalation мэдэгдэл илгээнэ."
    )

    def handle(self, *args, **options):
        now = timezone.now()
        tickets = (
            Ticket.objects.exclude(status__in=Ticket._SLA_EXEMPT_STATUSES)
            .select_related("assigned_to", "reported_by", "team", "team__team_lead")
        )

        counts = {
            "first_response_warning": 0,
            "first_response_breach": 0,
            "resolution_warning": 0,
            "resolution_breach": 0,
        }

        for ticket in tickets:
            if (
                ticket.first_responded_at is None
                and ticket.first_response_due_at is not None
            ):
                # Хугацаа хэтэрсэн эсэхийг эхэлж шалгана — due_at өнгөрсний дараа
                # "анхааруулга" шат хэзээ ч дахин үнэлэгдэхгүй (breach аль хэдийн
                # илгээгдсэн эсэхээс үл хамааран).
                if now >= ticket.first_response_due_at:
                    if ticket.first_response_breach_notified_at is None:
                        notify_first_response_breach(ticket)
                        Ticket.objects.filter(pk=ticket.pk).update(
                            first_response_breach_notified_at=now
                        )
                        counts["first_response_breach"] += 1
                elif (
                    ticket.first_response_warning_sent_at is None
                    and ticket.first_response_warning_at is not None
                    and now >= ticket.first_response_warning_at
                ):
                    notify_first_response_warning(ticket)
                    Ticket.objects.filter(pk=ticket.pk).update(
                        first_response_warning_sent_at=now
                    )
                    counts["first_response_warning"] += 1

            if ticket.sla_due_at is not None:
                if now >= ticket.sla_due_at:
                    if ticket.sla_breach_notified_at is None:
                        notify_resolution_breach(ticket)
                        Ticket.objects.filter(pk=ticket.pk).update(sla_breach_notified_at=now)
                        counts["resolution_breach"] += 1
                elif (
                    ticket.sla_warning_sent_at is None
                    and ticket.sla_warning_at is not None
                    and now >= ticket.sla_warning_at
                ):
                    notify_resolution_warning(ticket)
                    Ticket.objects.filter(pk=ticket.pk).update(sla_warning_sent_at=now)
                    counts["resolution_warning"] += 1

        self.stdout.write(
            self.style.SUCCESS(
                "SLA шалгалт дууслаа: "
                "эхний хариу — {first_response_warning} анхааруулга / "
                "{first_response_breach} escalation; "
                "шийдвэрлэлт — {resolution_warning} анхааруулга / "
                "{resolution_breach} escalation.".format(**counts)
            )
        )
