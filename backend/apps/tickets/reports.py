"""
Reporting dashboard-ийн тооцоолол.

Бүх метрик нь сонгосон хугацааны (7/30/90 хоног) мэдээлэлд суурилна:
  * SLA compliance   — Time to First Response / Time to Resolution-ийн биелэлт %
  * Volume trend     — өдөр тутам үүссэн / хаагдсан ticket-ийн тоо
  * Agent performance — хариуцагч тус бүрийн ачаалал, хаасан тоо, дундаж хугацаа
  * Breakdown        — priority / category-аар задалсан тоо

Ticket хэзээ хаагдсаныг тусдаа талбар нэмэхгүйгээр `StatusHistory`-оос уншина
(тиймээс өмнө нь үүссэн өгөгдөлд ч зөв ажиллана).
"""
import math
from collections import defaultdict
from datetime import timedelta

from django.db.models import OuterRef, Subquery
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import StatusHistory, Ticket

ALLOWED_PERIODS = (7, 30, 90)
DEFAULT_PERIOD = 30

# SLA биелэлтийн үнэлгээний босго (%) — meter-ийн өнгийг тодорхойлно.
COMPLIANCE_GOOD = 90
COMPLIANCE_WARNING = 70


def clean_period(value):
    """GET параметрээс ирсэн хоногийн тоог зөвшөөрөгдсөн утга руу хөрвүүлнэ."""
    try:
        days = int(value)
    except (TypeError, ValueError):
        return DEFAULT_PERIOD
    return days if days in ALLOWED_PERIODS else DEFAULT_PERIOD


def _closed_at_subquery():
    # Дахин нээгдээд дахин хаагдсан бол хамгийн сүүлийн хаалтыг тооцно.
    return Subquery(
        StatusHistory.objects.filter(
            ticket=OuterRef("pk"), to_status=Ticket.Status.CLOSED
        )
        .order_by("-changed_at")
        .values("changed_at")[:1]
    )


def _compliance_percent(met, breached):
    """Биелэлт % — хүлээгдэж буй (хугацаа нь болоогүй) ticket тооцоонд орохгүй."""
    total = met + breached
    if not total:
        return None
    return round(met * 100 / total, 1)


def _compliance_level(percent):
    if percent is None:
        return "none"
    if percent >= COMPLIANCE_GOOD:
        return "good"
    if percent >= COMPLIANCE_WARNING:
        return "warning"
    return "critical"


def _first_response_stats(tickets, now):
    met = breached = pending = 0
    for ticket in tickets:
        if not ticket.first_response_due_at:
            continue
        if ticket.first_responded_at:
            if ticket.first_responded_at <= ticket.first_response_due_at:
                met += 1
            else:
                breached += 1
        elif ticket.first_response_due_at < now:
            breached += 1
        else:
            pending += 1
    percent = _compliance_percent(met, breached)
    return {
        "met": met,
        "breached": breached,
        "pending": pending,
        "percent": percent,
        "level": _compliance_level(percent),
    }


def _resolution_stats(tickets, now):
    met = breached = pending = 0
    for ticket in tickets:
        if not ticket.sla_due_at:
            continue
        if ticket.status == Ticket.Status.CLOSED:
            if ticket.closed_at and ticket.closed_at <= ticket.sla_due_at:
                met += 1
            else:
                breached += 1
        elif ticket.status == Ticket.Status.REJECTED:
            # Татгалзсан ticket SLA-ийн хэмжилтэд огт хамаарахгүй.
            continue
        elif ticket.sla_due_at < now:
            breached += 1
        else:
            pending += 1
    percent = _compliance_percent(met, breached)
    return {
        "met": met,
        "breached": breached,
        "pending": pending,
        "percent": percent,
        "level": _compliance_level(percent),
    }


def _is_sla_breached(ticket, now):
    """Аль нэг SLA metric нь зөрчигдсөн эсэх (agent хүснэгтэд ашиглана)."""
    if ticket.status == Ticket.Status.REJECTED:
        return False
    first_response_breached = (
        ticket.first_response_due_at is not None
        and (
            (ticket.first_responded_at or now) > ticket.first_response_due_at
        )
    )
    if ticket.status == Ticket.Status.CLOSED:
        resolution_breached = bool(
            ticket.sla_due_at
            and (not ticket.closed_at or ticket.closed_at > ticket.sla_due_at)
        )
    else:
        resolution_breached = bool(ticket.sla_due_at and ticket.sla_due_at < now)
    return first_response_breached or resolution_breached


def _agent_rows(tickets, now):
    grouped = {}
    for ticket in tickets:
        if not ticket.assigned_to_id:
            continue
        row = grouped.setdefault(
            ticket.assigned_to_id,
            {
                "user": ticket.assigned_to,
                "assigned": 0,
                "closed": 0,
                "active": 0,
                "breached": 0,
                "resolution_hours": [],
            },
        )
        row["assigned"] += 1
        if ticket.status == Ticket.Status.CLOSED:
            row["closed"] += 1
            if ticket.closed_at:
                row["resolution_hours"].append(
                    (ticket.closed_at - ticket.created_at).total_seconds() / 3600
                )
        elif ticket.status not in Ticket._SLA_EXEMPT_STATUSES:
            row["active"] += 1
        if _is_sla_breached(ticket, now):
            row["breached"] += 1

    rows = []
    for row in grouped.values():
        hours = row.pop("resolution_hours")
        row["avg_resolution_hours"] = round(sum(hours) / len(hours), 1) if hours else None
        rows.append(row)
    rows.sort(key=lambda r: (-r["assigned"], r["user"].username))
    return rows


def _daily_trend(period_tickets, since, now, days, team=None):
    created_per_day = defaultdict(int)
    for ticket in period_tickets:
        created_per_day[timezone.localtime(ticket.created_at).date()] += 1

    closed_per_day = defaultdict(int)
    closures = StatusHistory.objects.filter(
        to_status=Ticket.Status.CLOSED, changed_at__gte=since
    )
    if team:
        closures = closures.filter(ticket__team=team)
    closures = closures.values_list("changed_at", flat=True)
    for changed_at in closures:
        closed_per_day[timezone.localtime(changed_at).date()] += 1

    start_date = timezone.localtime(since).date()
    end_date = timezone.localtime(now).date()
    trend = []
    day = start_date
    while day <= end_date:
        trend.append(
            {
                "date": day.isoformat(),
                "label": day.strftime("%m-%d"),
                "created": created_per_day.get(day, 0),
                "closed": closed_per_day.get(day, 0),
            }
        )
        day += timedelta(days=1)
    return trend


def _nice_axis(max_value, tick_count=4):
    """Y тэнхлэгийн дээд утга болон алхмыг "цэвэрхэн" тоо болгож сонгоно."""
    if max_value <= 0:
        return tick_count, 1
    raw_step = max_value / tick_count
    magnitude = 10 ** math.floor(math.log10(raw_step))
    for multiplier in (1, 2, 2.5, 5, 10):
        step = multiplier * magnitude
        if step >= raw_step:
            break
    step = int(step) if step >= 1 else 1
    return step * tick_count, step


# SVG талбайн хэмжээс (viewBox-оор масштаблагдана).
CHART_WIDTH = 720
CHART_HEIGHT = 220
PAD_LEFT, PAD_RIGHT, PAD_TOP, PAD_BOTTOM = 38, 52, 14, 26


def _trend_chart(trend):
    """
    Trend өгөгдлийг SVG-д шууд буулгах координат болгоно (математикийг template-д
    биш, энд хийснээр тестлэх боломжтой болно).
    """
    plot_width = CHART_WIDTH - PAD_LEFT - PAD_RIGHT
    plot_height = CHART_HEIGHT - PAD_TOP - PAD_BOTTOM
    point_count = len(trend)
    max_value = max(
        [row["created"] for row in trend] + [row["closed"] for row in trend] or [0]
    )
    y_max, y_step = _nice_axis(max_value)

    def x_at(index):
        if point_count <= 1:
            return PAD_LEFT + plot_width / 2
        return PAD_LEFT + index * plot_width / (point_count - 1)

    def y_at(value):
        return PAD_TOP + plot_height * (1 - value / y_max)

    series = []
    for key, label in (("created", _("Үүссэн")), ("closed", _("Хаагдсан"))):
        points = [
            {
                "x": round(x_at(i), 2),
                "y": round(y_at(row[key]), 2),
                "value": row[key],
                "date_label": row["label"],
            }
            for i, row in enumerate(trend)
        ]
        series.append(
            {
                "key": key,
                "label": label,
                "polyline": " ".join(f"{p['x']},{p['y']}" for p in points),
                "points": points,
                "last": points[-1] if points else None,
                "total": sum(row[key] for row in trend),
            }
        )

    y_ticks = []
    value = 0
    while value <= y_max:
        y_ticks.append({"value": value, "y": round(y_at(value), 2)})
        value += y_step

    # Хамгийн ихдээ 6 шошго — бөөгнөрөхөөс сэргийлнэ.
    label_stride = max(1, math.ceil(point_count / 6))
    x_ticks = [
        {"label": row["label"], "x": round(x_at(i), 2)}
        for i, row in enumerate(trend)
        if i % label_stride == 0 or i == point_count - 1
    ]

    return {
        "width": CHART_WIDTH,
        "height": CHART_HEIGHT,
        "pad_left": PAD_LEFT,
        "plot_right": CHART_WIDTH - PAD_RIGHT,
        "plot_top": PAD_TOP,
        "plot_bottom": CHART_HEIGHT - PAD_BOTTOM,
        "series": series,
        "y_ticks": y_ticks,
        "x_ticks": x_ticks,
        "has_data": max_value > 0,
    }


def _breakdown(tickets, attribute, labels=None):
    counts = defaultdict(int)
    for ticket in tickets:
        counts[getattr(ticket, attribute)] += 1
    total = sum(counts.values())
    rows = []
    for key, count in counts.items():
        rows.append(
            {
                "key": key,
                "label": labels.get(key, key) if labels else key,
                "count": count,
                "percent": round(count * 100 / total, 1) if total else 0,
            }
        )
    rows.sort(key=lambda r: -r["count"])
    return rows


def build_report(days=DEFAULT_PERIOD, team=None):
    """`team` өгвөл зөвхөн тухайн багийн ticket-ээр тооцно (Team Lead-ийн dashboard)."""
    now = timezone.now()
    since = now - timedelta(days=days)
    scope = Ticket.objects.filter(team=team) if team else Ticket.objects.all()

    period_tickets = list(
        scope.filter(created_at__gte=since)
        .annotate(closed_at=_closed_at_subquery())
        .select_related("assigned_to", "category")
    )

    trend = _daily_trend(period_tickets, since, now, days, team)
    closed_in_period = sum(row["closed"] for row in trend)
    open_now = scope.exclude(status__in=Ticket._SLA_EXEMPT_STATUSES).count()

    priority_labels = dict(Ticket.Priority.choices)
    resolution_hours = [
        (t.closed_at - t.created_at).total_seconds() / 3600
        for t in period_tickets
        if t.status == Ticket.Status.CLOSED and t.closed_at
    ]

    return {
        "days": days,
        "team": team,
        "days_str": str(days),
        "since": since,
        "generated_at": now,
        "periods": ALLOWED_PERIODS,
        "created_count": len(period_tickets),
        "closed_count": closed_in_period,
        "open_count": open_now,
        "avg_resolution_hours": (
            round(sum(resolution_hours) / len(resolution_hours), 1)
            if resolution_hours
            else None
        ),
        "first_response": _first_response_stats(period_tickets, now),
        "resolution": _resolution_stats(period_tickets, now),
        "trend": trend,
        "chart": _trend_chart(trend),
        "agents": _agent_rows(period_tickets, now),
        "by_priority": _breakdown(period_tickets, "priority", priority_labels),
        "by_category": _breakdown(
            period_tickets, "category", {c: c.name for c in {t.category for t in period_tickets}}
        ),
    }
