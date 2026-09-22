"""
Эрхийн шалгалт: docs/workflow.md-ийн "Хийж болох эрх" баганатай тааруулсан.

Group нэрс нь apps/accounts/migrations/0001_create_groups.py-д
data migration-аар үүссэн 4 бүлэгтэй яг таарна.
"""
from django.db.models import Q

ROLE_ADMIN = "Admin"
ROLE_PM = "Project Manager"
ROLE_QA = "QA Tester"
ROLE_DEV = "Developer"

# (current_status, new_status) -> тухайн шилжилтийг хийж болох group-ууд
TRANSITION_PERMISSIONS = {
    ("new", "assigned"): {ROLE_PM, ROLE_ADMIN},
    ("assigned", "in_progress"): {ROLE_DEV, ROLE_ADMIN},
    ("in_progress", "resolved"): {ROLE_DEV, ROLE_ADMIN},
    ("in_progress", "rejected"): {ROLE_DEV, ROLE_PM, ROLE_ADMIN},
    ("resolved", "qa_test"): {ROLE_DEV, ROLE_ADMIN},
    ("qa_test", "closed"): {ROLE_QA, ROLE_ADMIN},
    ("qa_test", "reopened"): {ROLE_QA, ROLE_ADMIN},
    ("reopened", "in_progress"): {ROLE_DEV, ROLE_ADMIN},
    ("rejected", "reopened"): {ROLE_PM, ROLE_ADMIN},
}

# Эдгээр шилжилтийг зөвхөн тухайн ticket-т ОНООГДСОН Developer хийж болно
# (өөр Developer биш). Admin group-ийнхэн энэ хязгаарлалтаас чөлөөлөгдөнө.
ASSIGNEE_ONLY_TRANSITIONS = {
    ("assigned", "in_progress"),
    ("in_progress", "resolved"),
    ("in_progress", "rejected"),
    ("reopened", "in_progress"),
}


def user_roles(user):
    """Хэрэглэгчийн group-уудыг нэрээр нь буцаана. Superuser бүх эрхтэй."""
    if user.is_superuser:
        return {ROLE_ADMIN, ROLE_PM, ROLE_QA, ROLE_DEV}
    return set(user.groups.values_list("name", flat=True))


def can_user_transition(ticket, new_status, user):
    """
    (зөвшөөрөгдсөн эсэх: bool, алдааны текст: str) хос буцаана.
    Workflow дараалал зөв эсэхийг apps.tickets.models.can_transition тусад нь шалгадаг;
    энэ функц зөвхөн "ХЭН хийж болох" эрхийг шалгана.
    """
    key = (ticket.status, new_status)
    required_roles = TRANSITION_PERMISSIONS.get(key)
    if required_roles is None:
        return False, "Энэ шилжилт зөвшөөрөгдөөгүй."

    roles = user_roles(user)
    if not roles & required_roles:
        return False, "Танд энэ шилжилтийг хийх эрх байхгүй."

    if key in ASSIGNEE_ONLY_TRANSITIONS and ROLE_ADMIN not in roles:
        if ticket.assigned_to_id != user.id:
            return False, "Зөвхөн танд оноогдсон ticket дээр энэ үйлдлийг хийж болно."

    return True, ""


def can_user_assign(user):
    """NEW -> ASSIGNED шилжилтийн үед хариуцагч сонгох эрхтэй эсэх (PM/Admin)."""
    return bool(user_roles(user) & {ROLE_PM, ROLE_ADMIN})


# Эдгээр статустай ticket "идэвхтэй ажил" гэж тооцогдоно (ачаалал тооцоход ашиглана)
_ACTIVE_TICKET_STATUSES = ["assigned", "in_progress", "resolved", "qa_test", "reopened"]


def team_members_with_workload(team):
    """
    Багийн гишүүдийг идэвхтэй (хаагдаагүй/татгалзаагүй) ticket-ийн тоотой нь хамт
    буцаана — багатай ачаалалтай гишүүнд шинэ ticket-ийг илүү амархан даатгах боломж
    олгоно. Хамгийн бага ачаалалтай хүн эхэнд гарна.
    """
    if team is None:
        return []

    from django.db.models import Count, Q

    return team.members.annotate(
        active_ticket_count=Count(
            "assigned_tickets",
            filter=Q(assigned_tickets__status__in=_ACTIVE_TICKET_STATUSES),
            distinct=True,
        )
    ).order_by("active_ticket_count", "username")


def assignable_developers():
    """'Developer' group-т багтсан хэрэглэгчид (assign хийхэд сонголт болгоно)."""
    from django.contrib.auth.models import User

    return User.objects.filter(Q(groups__name=ROLE_DEV) | Q(is_superuser=True)).distinct()
