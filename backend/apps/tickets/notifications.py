"""
Ticket-тэй холбоотой email мэдэгдлүүд.

Мэдэгдэл бүр `_deliver()`-ээр дамжина: идэвхтэй, и-мэйлтэй хүлээн авагчдад нэг
мэйл илгээнэ (.env-д EMAIL_HOST заасан бол SMTP, үгүй бол console). Илгээхэд алдаа гарвал хэрэглэгчийн үйлдлийг тасалдуулахгүй,
лог руу бичнэ. Хэнд очихыг STATUS_NOTIFICATION_RULES тодорхойлно.
"""
import logging
import re

from django.conf import settings
from django.core.mail import send_mail as _django_send_mail

logger = logging.getLogger(__name__)


def send_mail(**kwargs):
    """
    Мэйл илгээхэд алдаа гарвал хэрэглэгчийн үйлдлийг тасалдуулахгүй, харин
    лог руу бичнэ (өмнө нь fail_silently=True алдааг бүрэн нууж байсан).
    """
    kwargs.pop("fail_silently", None)
    try:
        _django_send_mail(fail_silently=False, **kwargs)
    except Exception:
        logger.exception("Мэйл илгээж чадсангүй: %s → %s", kwargs.get("subject"), kwargs.get("recipient_list"))


def ticket_url(ticket):
    from django.urls import reverse

    return settings.SITE_URL.rstrip("/") + reverse("tickets:ticket_detail", args=[ticket.pk])


def _recipient_emails(users, exclude_user=None):
    emails = []
    seen = set()
    for user in users:
        if not user or not user.email:
            continue
        if exclude_user is not None and user.id == exclude_user.id:
            continue
        if user.email in seen:
            continue
        seen.add(user.email)
        emails.append(user.email)
    return emails


def _deliver(users, ticket, title, message, exclude_user=None):
    """
    И-мэйлтэй хүлээн авагчдад мэйл илгээнэ. Давхардсан, идэвхгүй хүн болон
    үйлдэл хийсэн хүнийг (exclude_user) алгасна.
    """
    recipients, seen = [], set()
    for user in users:
        if not user or not user.is_active or user.id in seen:
            continue
        if exclude_user is not None and user.id == exclude_user.id:
            continue
        seen.add(user.id)
        recipients.append(user)
    emails = _recipient_emails(recipients)
    if emails:
        send_mail(
            subject=f"[{ticket.code}] {title}",
            message=f"{message}\n\n{ticket_url(ticket)}\n",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=emails,
        )


def notify_ticket_assigned(ticket, changed_by=None):
    """Ticket хариуцагчид (assigned_to) шинээр оноогдсоныг мэдэгдэнэ."""
    _deliver(
        [ticket.assigned_to], ticket,
        title=f"Танд ticket оноогдлоо: {ticket.title}",
        message=(
            f"'{ticket.title}' ticket танд оноогдлоо.\n\n"
            f"Төрөл: {ticket.get_ticket_type_display()}\n"
            f"Чухлын зэрэг: {ticket.get_priority_display()}\n"
            f"Төлөв: {ticket.get_status_display()}"
        ),
        exclude_user=changed_by,
    )


# Төлөв бүрт "дараагийн алхмыг хийх хүн"-д мэйл очно (Jira / Zendesk-ийн notification
# scheme-тэй адил). Мэдээлэгч (reported_by) зөвхөн эцсийн үр дүнг (хаагдсан /
# татгалзсан) авна. "assigned"-ийн мэйлийг notify_ticket_assigned тусад нь илгээнэ.
STATUS_NOTIFICATION_RULES = {
    "qa_test": (("qa_tester",), "Шалгалт хийнэ үү — ticket QA шалгалтад ирлээ."),
    "reopened": (("assignee", "team_lead"), "Ticket дахин нээгдлээ — дахин засах шаардлагатай."),
    "closed": (("reporter", "team_lead"), "Ticket шийдэгдэж, QA баталгаажуулан хаалаа."),
    "rejected": (("reporter", "team_lead"), "Ticket татгалзагдлаа."),
}


def status_change_recipients(ticket, to_status):
    rule = STATUS_NOTIFICATION_RULES.get(to_status)
    if not rule:
        return []
    team = ticket.team if ticket.team_id else None
    people = {
        "reporter": ticket.reported_by,
        "assignee": ticket.assigned_to,
        "team_lead": team.team_lead if team else None,
        # Багт QA тохируулаагүй (эсвэл идэвхгүй) бол Team Lead QA-д хэнийг явуулахыг шийднэ.
        "qa_tester": (
            team.qa_tester if team.qa_tester and team.qa_tester.is_active else team.team_lead
        ) if team else None,
    }
    return [people[role] for role in rule[0]]


def notify_status_changed(ticket, from_status, to_status, changed_by=None):
    """Төлөв өөрчлөгдөхөд дүрмийн дагуу дараагийн алхмыг хийх хүнд мэдэгдэнэ
    (өөрчлөлт хийсэн хүнд илгээхгүй)."""
    people = status_change_recipients(ticket, to_status)
    labels = dict(ticket.Status.choices)
    actor = (changed_by.get_full_name() or changed_by.username) if changed_by else "—"
    rule = STATUS_NOTIFICATION_RULES.get(to_status)
    _deliver(
        people, ticket,
        title=f"{labels.get(to_status, to_status)}: {ticket.title}",
        message=(
            f"{rule[1] if rule else 'Ticket-ийн төлөв өөрчлөгдлөө.'}\n\n"
            f"Ticket: {ticket.code} — {ticket.title}\n"
            f"Төлөв: {labels.get(from_status, from_status)} → {labels.get(to_status, to_status)}\n"
            f"Өөрчилсөн: {actor}\n"
            f"Хариуцагч: {ticket.assigned_to.username if ticket.assigned_to else '—'}"
        ),
        exclude_user=changed_by,
    )


def _escalation_recipients(ticket):
    """Team Lead болон assignee-д escalate хийнэ (Jira Service Management-ийн SLA
    breach notification-той адил); аль аль нь байхгүй бол reported_by-д очно."""
    recipients = [ticket.assigned_to]
    if ticket.team_id and ticket.team.team_lead_id:
        recipients.append(ticket.team.team_lead)
    if not any(recipients):
        recipients = [ticket.reported_by]
    return recipients


def notify_first_response_warning(ticket):
    """'Time to First Response' SLA дуусахад ойртсоныг хариуцагчид сануулна."""
    _deliver(
        [ticket.assigned_to or ticket.reported_by], ticket,
        title="Эхний хариу өгөх хугацаа дуусахад ойртлоо",
        message=(
            f"'{ticket.title}' ticket-д хариу өгөх (Time to First Response) SLA "
            f"хугацаа '{ticket.first_response_due_at:%Y-%m-%d %H:%M}'-д дуусна."
        ),
    )


def notify_first_response_breach(ticket):
    """'Time to First Response' SLA хэтэрснийг Team Lead/assignee-д escalate хийнэ."""
    _deliver(
        _escalation_recipients(ticket), ticket,
        title="SLA ЗӨРЧИГДЛӨӨ: Эхний хариу өгөх хугацаа хэтэрлээ",
        message=(
            f"'{ticket.title}' ticket-д хариу өгөх (Time to First Response) SLA хугацаа "
            f"хэтэрсэн байна (эцсийн хугацаа: {ticket.first_response_due_at:%Y-%m-%d %H:%M})."
        ),
    )


def notify_resolution_warning(ticket):
    """'Time to Resolution' SLA дуусахад ойртсоныг хариуцагчид сануулна."""
    _deliver(
        [ticket.assigned_to or ticket.reported_by], ticket,
        title=f"SLA хугацаа дуусахад ойртлоо: {ticket.title}",
        message=(
            f"'{ticket.title}' ticket-ийг шийдвэрлэх (Time to Resolution) SLA хугацаа "
            f"'{ticket.sla_due_at:%Y-%m-%d %H:%M}'-д дуусна."
        ),
    )


def notify_resolution_breach(ticket):
    """'Time to Resolution' SLA хэтэрснийг Team Lead/assignee-д escalate хийнэ."""
    _deliver(
        _escalation_recipients(ticket), ticket,
        title="SLA ЗӨРЧИГДЛӨӨ: Шийдвэрлэх хугацаа хэтэрлээ",
        message=(
            f"'{ticket.title}' ticket-ийг шийдвэрлэх (Time to Resolution) SLA хугацаа "
            f"хэтэрсэн байна (эцсийн хугацаа: {ticket.sla_due_at:%Y-%m-%d %H:%M})."
        ),
    )


def notify_ticket_routed(ticket):
    """Category-ийн дагуу автоматаар оноогдсон Team-ийн Team Lead-д шинэ ticket
    үүссэнийг мэдэгдэнэ."""
    if ticket.team_id is None or ticket.team.team_lead_id is None:
        return
    _deliver(
        [ticket.team.team_lead], ticket,
        title=f"Шинэ ticket '{ticket.team.name}' багт ирлээ",
        message=(
            f"'{ticket.title}' ({ticket.get_ticket_type_display()}) шинэ ticket "
            f"'{ticket.team.name}' багт автоматаар чиглэгдлээ — хариуцагч сонгож оноогоно уу.\n\n"
            f"Чухлын зэрэг: {ticket.get_priority_display()}"
        ),
        exclude_user=ticket.reported_by,
    )


def notify_stale_ticket_reminder(ticket, idle_hours):
    """
    'Automation rule' — идэвхгүй байдал үргэлжилж байгаа ticket-ийн тухай
    хариуцагчид (эсвэл байхгүй бол Team Lead-д) давтан сануулга илгээнэ
    (Zendesk/Jira-ийн time-based automation-той адил).
    """
    recipients = [ticket.assigned_to]
    if not any(recipients) and ticket.team_id and ticket.team.team_lead_id:
        recipients = [ticket.team.team_lead]
    _deliver(
        recipients, ticket,
        title=f"Идэвхгүй байна: {ticket.title}",
        message=(
            f"'{ticket.title}' ticket-д сүүлийн {idle_hours} цагийн турш ямар ч "
            f"идэвх (comment, status шилжилт) бүртгэгдээгүй байна.\n\n"
            f"Төлөв: {ticket.get_status_display()}\n"
            f"Чухлын зэрэг: {ticket.get_priority_display()}"
        ),
    )


MENTION_RE = re.compile(r"(?<![\w@])@([\w.+-]+)")


def mentioned_users(text):
    """Сэтгэгдэл доторх @username-уудаас идэвхтэй хэрэглэгчдийг олно."""
    from django.contrib.auth import get_user_model

    names = {name.rstrip(".") for name in MENTION_RE.findall(text or "")}
    if not names:
        return []
    return list(get_user_model().objects.filter(username__in=names, is_active=True))


def notify_comment(ticket, comment):
    """
    Шинэ сэтгэгдлийг @дурдагдсан хүмүүс, мэдээлэгч, хариуцагчид мэдэгдэнэ. Дотоод тэмдэглэлийг зөвхөн харах эрхтэй хүмүүст илгээнэ.
    """
    from .permissions import can_see_internal_notes

    author = comment.author

    def allowed(user):
        return not comment.is_internal or can_see_internal_notes(ticket, user)

    name = (author.get_full_name() or author.username) if author else "—"
    preview = comment.body if len(comment.body) <= 500 else comment.body[:500] + "…"
    lock = " 🔒" if comment.is_internal else ""

    mentioned = [u for u in mentioned_users(comment.body) if allowed(u)]
    _deliver(
        mentioned, ticket,
        title=f"{name} таныг дурдлаа{lock}: {ticket.title}",
        message=f"{name} {ticket.code} ticket-ийн сэтгэгдэлд таныг дурдлаа:\n\n{preview}",
        exclude_user=author,
    )
    mentioned_ids = {u.id for u in mentioned}
    others = [
        u for u in [ticket.reported_by, ticket.assigned_to]
        if u and u.id not in mentioned_ids and allowed(u)
    ]
    _deliver(
        others, ticket,
        title=f"Шинэ сэтгэгдэл{lock}: {ticket.title}",
        message=f"{name} {ticket.code} ticket дээр сэтгэгдэл бичлээ:\n\n{preview}",
        exclude_user=author,
    )
