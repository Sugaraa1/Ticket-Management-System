"""
Эрхийн шалгалт: docs/workflow.md-ийн "Хийж болох эрх" баганатай тааруулсан.

Group нэрс нь apps/accounts/migrations/0001_create_groups.py-д
data migration-аар үүссэн 4 бүлэгтэй яг таарна.
"""
from django.db.models import Q
from django.utils.translation import gettext as _

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

# Developer эдгээр шилжилтийг зөвхөн ӨӨРТ нь оноогдсон ticket дээр хийнэ (бусдын
# ticket-ийг биш). Admin, мөн PM-ийн эрхтэй шилжилт дээр (татгалзах) PM / багийн
# Team Lead энэ хязгаарлалтаас чөлөөлөгдөнө.
ASSIGNEE_ONLY_TRANSITIONS = {
    ("assigned", "in_progress"),
    ("in_progress", "resolved"),
    ("in_progress", "rejected"),
    ("resolved", "qa_test"),
    ("reopened", "in_progress"),
}


QA_TEAM_TRANSITIONS = {("qa_test", "closed"), ("qa_test", "reopened")}
CLOSED_TICKET_STATUSES = ("closed", "rejected")


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
        return False, _("Энэ шилжилт зөвшөөрөгдөөгүй.")

    roles = user_roles(user)
    if is_team_lead_of(ticket, user):
        # Багийн Team Lead тухайн багийн ticket дээр PM-ийн эрхтэй (оноох, татгалзах,
        # дахин нээх) — PM group-т багтаагүй байсан ч.
        roles = roles | {ROLE_PM}
    if not roles & required_roles:
        return False, _("Танд энэ шилжилтийг хийх эрх байхгүй.")

    manager = ROLE_ADMIN in roles or (ROLE_PM in roles and ROLE_PM in required_roles)
    if key in ASSIGNEE_ONLY_TRANSITIONS and not manager:
        if ticket.assigned_to_id != user.id:
            return False, _("Зөвхөн танд оноогдсон ticket дээр энэ үйлдлийг хийж болно.")

    if key in QA_TEAM_TRANSITIONS and ROLE_ADMIN not in roles:
        # Багт QA Tester тохируулсан бол зөвхөн тэр хүн хаах/дахин нээх эрхтэй
        # (өөр багийн QA бусдын ticket-ийг хаахаас сэргийлнэ).
        # QA Tester идэвхгүй болсон бол хязгаарлахгүй (эс тэгвэл ticket гацна).
        team_qa = ticket.team.qa_tester if ticket.team_id else None
        if team_qa and team_qa.is_active and team_qa.id != user.id:
            return False, _("Зөвхөн энэ багийн QA Tester шалгалтын үр дүнг тэмдэглэнэ.")

    return True, ""


def can_user_reassign(ticket, user):
    """
    Оноогдсон ticket-ийн хариуцагчийг солих эрх: PM/Admin, эсвэл тухайн багийн
    Team Lead. Хаагдсан/татгалзсан болон хараахан оноогоогүй (NEW) ticket-д хамаарахгүй.
    """
    if ticket.status in (*CLOSED_TICKET_STATUSES, "new"):
        return False
    return can_user_assign(user, ticket)


def can_see_internal_notes(ticket, user):
    """
    Дотоод тэмдэглэл (internal note) харах/бичих эрх: PM/Admin, ticket-ийн хариуцагч,
    эсвэл тухайн багийн гишүүн / Team Lead / QA Tester. Мэдээлсэн хүн багт
    хамааралгүй бол харахгүй.
    """
    if user_roles(user) & {ROLE_PM, ROLE_ADMIN}:
        return True
    if ticket.assigned_to_id == user.id:
        return True
    team = ticket.team if ticket.team_id else None
    if team is None:
        return False
    return (
        user.id in (team.team_lead_id, team.qa_tester_id)
        or team.members.filter(pk=user.pk).exists()
    )


def can_use_bulk_actions(user):
    """Жагсаалтын бөөн үйлдэл (олон ticket-ийг нэг дор өөрчлөх) — зөвхөн PM / Admin."""
    return bool(user_roles(user) & {ROLE_PM, ROLE_ADMIN})


def can_user_edit_ticket(ticket, user):
    """
    Ticket-ийн үндсэн мэдээллийг (гарчиг, тайлбар, төрөл, төсөл, модуль, ангилал)
    засах эрх: мэдээлэгч, PM/Admin, эсвэл багийн Team Lead. Хаагдсан / татгалзсан
    ticket-ийг засахгүй.
    """
    if ticket.status in CLOSED_TICKET_STATUSES:
        return False
    return ticket.reported_by_id == user.id or can_user_assign(user, ticket)


def is_team_lead_of(ticket, user):
    return bool(ticket.team_id and ticket.team.team_lead_id == user.id)


def can_user_assign(user, ticket=None):
    """
    Хариуцагч сонгох / чухлын зэрэг өөрчлөх эрх: PM/Admin, эсвэл (ticket өгсөн бол)
    тухайн багийн Team Lead.
    """
    if user_roles(user) & {ROLE_PM, ROLE_ADMIN}:
        return True
    return ticket is not None and is_team_lead_of(ticket, user)


def has_global_reports(user):
    """
    Нийт (бүх багийн) dashboard/экспорт харах эрх: Admin, PM (баг ахалсан ч гэсэн).
    PM биш Team Lead зөвхөн өөрийн багийнхаа тайланг "Миний баг"-аас харна.
    """
    return bool(user_roles(user) & {ROLE_PM, ROLE_ADMIN})


def can_view_team_report(user, team):
    return team.team_lead_id == user.id or has_global_reports(user)


def export_ticket_scope(user):
    """
    Ticket жагсаалт татах эрхийн хүрээ: None — бүх ticket, list — зөвхөн эдгээр
    багийн ticket (Team Lead), False — татах эрхгүй.
    """
    if has_global_reports(user):
        return None
    team_ids = list(user.led_teams.values_list("id", flat=True))
    return team_ids or False


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

    # Идэвхгүй (нэвтрэх эрхгүй) хэрэглэгчид ticket оноохгүй.
    return team.members.filter(is_active=True).annotate(
        active_ticket_count=Count(
            "assigned_tickets",
            filter=Q(assigned_tickets__status__in=_ACTIVE_TICKET_STATUSES),
            distinct=True,
        )
    ).order_by("active_ticket_count", "username")


def assignable_developers():
    """'Developer' group-т багтсан хэрэглэгчид (assign хийхэд сонголт болгоно)."""
    from django.contrib.auth.models import User

    return User.objects.filter(
        Q(groups__name=ROLE_DEV) | Q(is_superuser=True), is_active=True
    ).distinct()
