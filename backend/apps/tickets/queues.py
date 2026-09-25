"""Хэрэглэгч бүрийн "хийх ажил"-ын дараалал (Jira-ийн "Assigned to me" / queue-тэй адил).

- Developer: өөрт оноогдсон идэвхтэй ticket.
- QA Tester: өөрийн багийн "Чанарын шалгалтад" төлөвт ирсэн ticket.
- Team Lead: өөрийн багт ирсэн, хэнд ч оноогдоогүй (Шинэ) ticket.
"""
from django.db.models import Q

from .models import Ticket

CLOSED_STATUSES = [Ticket.Status.CLOSED, Ticket.Status.REJECTED]


def _base():
    return Ticket.objects.select_related("category", "assigned_to", "reported_by", "team")


def assigned_to_me(user):
    return (
        _base()
        .filter(assigned_to=user)
        .exclude(status__in=CLOSED_STATUSES + [Ticket.Status.QA_TEST])
    )


def qa_queue(user):
    return _base().filter(status=Ticket.Status.QA_TEST, team__qa_tester=user)


def lead_queue(user):
    return _base().filter(team__team_lead=user).filter(
        Q(status=Ticket.Status.NEW) | Q(status=Ticket.Status.REOPENED, assigned_to__isnull=True)
    )


def action_count(user):
    """Navbar-ийн badge: хэрэглэгчээс шууд үйлдэл хүлээж буй ticket-ийн тоо."""
    ids = set(assigned_to_me(user).values_list("id", flat=True))
    ids |= set(qa_queue(user).values_list("id", flat=True))
    ids |= set(lead_queue(user).values_list("id", flat=True))
    return len(ids)
