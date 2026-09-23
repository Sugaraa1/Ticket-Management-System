"""
Ticket-тэй холбоотой email мэдэгдлүүд.

Одоогийн хувилбарт зөвхөн Django-ийн `send_mail`-ээр илгээгдэнэ
(dev дээр console backend, prod дээр SMTP — config/settings-г үзнэ үү).
Илгээхэд алдаа гарвал хэрэглэгчийн үйлдлийг тасалдуулахгүйн тулд
`fail_silently=True` ашиглана.
"""
from django.conf import settings
from django.core.mail import send_mail


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


def notify_ticket_assigned(ticket, changed_by=None):
    """Ticket хариуцагчид (assigned_to) шинээр оноогдсоныг мэдэгдэнэ."""
    recipients = _recipient_emails([ticket.assigned_to], exclude_user=changed_by)
    if not recipients:
        return
    send_mail(
        subject=f"[Ticket #{ticket.pk}] Танд ticket оноогдлоо: {ticket.title}",
        message=(
            f"'{ticket.title}' ticket танд оноогдлоо.\n\n"
            f"Төрөл: {ticket.get_ticket_type_display()}\n"
            f"Чухлын зэрэг: {ticket.get_priority_display()}\n"
            f"Төлөв: {ticket.get_status_display()}\n"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=recipients,
        fail_silently=True,
    )


def notify_status_changed(ticket, from_status, to_status, changed_by=None):
    """Ticket-ийг мэдээллийн эзэн (reported_by) болон хариуцагчид (assigned_to) төлөв
    өөрчлөгдсөнийг мэдэгдэнэ (өөрчлөлт хийсэн хүнд давхар илгээхгүй)."""
    recipients = _recipient_emails(
        [ticket.reported_by, ticket.assigned_to], exclude_user=changed_by
    )
    if not recipients:
        return
    send_mail(
        subject=f"[Ticket #{ticket.pk}] Төлөв өөрчлөгдлөө: {ticket.title}",
        message=(
            f"'{ticket.title}' ticket-ийн төлөв өөрчлөгдлөө.\n\n"
            f"Хуучин төлөв: {from_status}\n"
            f"Шинэ төлөв: {to_status}\n"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=recipients,
        fail_silently=True,
    )


def _escalation_recipients(ticket):
    """Team Lead болон assignee-д escalate хийнэ (Jira Service Management-ийн SLA
    breach notification-той адил); аль аль нь байхгүй бол reported_by-д очно."""
    recipients = [ticket.assigned_to]
    if ticket.team_id and ticket.team.team_lead_id:
        recipients.append(ticket.team.team_lead)
    if not any(recipients):
        recipients = [ticket.reported_by]
    return _recipient_emails(recipients)


def notify_first_response_warning(ticket):
    """'Time to First Response' SLA дуусахад ойртсоныг хариуцагчид сануулна."""
    recipients = _recipient_emails([ticket.assigned_to or ticket.reported_by])
    if not recipients:
        return
    send_mail(
        subject=f"[Ticket #{ticket.pk}] Эхний хариу өгөх хугацаа дуусахад ойртлоо",
        message=(
            f"'{ticket.title}' ticket-д хариу өгөх (Time to First Response) SLA "
            f"хугацаа '{ticket.first_response_due_at:%Y-%m-%d %H:%M}'-д дуусна.\n"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=recipients,
        fail_silently=True,
    )


def notify_first_response_breach(ticket):
    """'Time to First Response' SLA хэтэрснийг Team Lead/assignee-д escalate хийнэ."""
    recipients = _escalation_recipients(ticket)
    if not recipients:
        return
    send_mail(
        subject=f"[Ticket #{ticket.pk}] SLA ЗӨРЧИГДЛӨӨ: Эхний хариу өгөх хугацаа хэтэрлээ",
        message=(
            f"'{ticket.title}' ticket-д хариу өгөх (Time to First Response) SLA хугацаа "
            f"хэтэрсэн байна (эцсийн хугацаа: {ticket.first_response_due_at:%Y-%m-%d %H:%M}).\n"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=recipients,
        fail_silently=True,
    )


def notify_resolution_warning(ticket):
    """'Time to Resolution' SLA дуусахад ойртсоныг хариуцагчид сануулна."""
    recipients = _recipient_emails([ticket.assigned_to or ticket.reported_by])
    if not recipients:
        return
    send_mail(
        subject=f"[Ticket #{ticket.pk}] SLA хугацаа дуусахад ойртлоо: {ticket.title}",
        message=(
            f"'{ticket.title}' ticket-ийг шийдвэрлэх (Time to Resolution) SLA хугацаа "
            f"'{ticket.sla_due_at:%Y-%m-%d %H:%M}'-д дуусна.\n"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=recipients,
        fail_silently=True,
    )


def notify_resolution_breach(ticket):
    """'Time to Resolution' SLA хэтэрснийг Team Lead/assignee-д escalate хийнэ."""
    recipients = _escalation_recipients(ticket)
    if not recipients:
        return
    send_mail(
        subject=f"[Ticket #{ticket.pk}] SLA ЗӨРЧИГДЛӨӨ: Шийдвэрлэх хугацаа хэтэрлээ",
        message=(
            f"'{ticket.title}' ticket-ийг шийдвэрлэх (Time to Resolution) SLA хугацаа "
            f"хэтэрсэн байна (эцсийн хугацаа: {ticket.sla_due_at:%Y-%m-%d %H:%M}).\n"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=recipients,
        fail_silently=True,
    )


def notify_ticket_routed(ticket):
    """Category-ийн дагуу автоматаар оноогдсон Team-ийн Team Lead-д шинэ ticket
    үүссэнийг мэдэгдэнэ."""
    if ticket.team_id is None or ticket.team.team_lead_id is None:
        return
    recipients = _recipient_emails([ticket.team.team_lead], exclude_user=ticket.reported_by)
    if not recipients:
        return
    send_mail(
        subject=f"[Ticket #{ticket.pk}] Шинэ ticket '{ticket.team.name}' багт ирлээ",
        message=(
            f"'{ticket.title}' ({ticket.get_ticket_type_display()}) шинэ ticket "
            f"'{ticket.team.name}' багт автоматаар чиглэгдлээ.\n\n"
            f"Чухлын зэрэг: {ticket.get_priority_display()}\n"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=recipients,
        fail_silently=True,
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
    recipient_emails = _recipient_emails(recipients)
    if not recipient_emails:
        return
    send_mail(
        subject=f"[Ticket #{ticket.pk}] Идэвхгүй байна: {ticket.title}",
        message=(
            f"'{ticket.title}' ticket-д сүүлийн {idle_hours} цагийн турш ямар ч "
            f"идэвх (comment, status шилжилт) бүртгэгдээгүй байна.\n\n"
            f"Төлөв: {ticket.get_status_display()}\n"
            f"Чухлын зэрэг: {ticket.get_priority_display()}\n"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=recipient_emails,
        fail_silently=True,
    )
