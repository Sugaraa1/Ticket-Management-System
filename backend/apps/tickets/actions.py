"""
Ticket дээрх үйлдлүүд (оноох, хариуцагч солих, чухлын зэрэг, төлөв шилжүүлэх)
эрхийн шалгалт, мэдэгдлийн хамт нэг газарт.

Ticket-ийн хуудас болон жагсаалтын "бөөнөөр үйлдэл" хоёулаа эндээс дуудна —
тиймээс хоёр замаар ижил дүрэм үйлчилнэ. Амжилтгүй бол `ActionError` (хэрэглэгчид
харуулах тексттэй) шиднэ.
"""
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from .models import Comment, Ticket
from .notifications import notify_status_changed, notify_ticket_assigned
from .permissions import (
    can_user_assign,
    can_user_reassign,
    can_user_transition,
    team_members_with_workload,
)


class ActionError(Exception):
    pass


def _team_member(ticket, user_id):
    members = {str(u.id): u for u in team_members_with_workload(ticket.team)}
    member = members.get(str(user_id or ""))
    if member is None:
        raise ActionError(_("Сонгосон хэрэглэгч энэ ticket-ийн багийн идэвхтэй гишүүн биш байна."))
    return member


def transition(ticket, new_status, user, comment="", assignee_id=None):
    """Төлөв шилжүүлнэ. "Оноогдсон" руу шилжүүлэхэд `assignee_id` заавал."""
    allowed, error = can_user_transition(ticket, new_status, user)
    if not allowed:
        raise ActionError(error)
    if new_status == Ticket.Status.ASSIGNED:
        if not assignee_id:
            raise ActionError(_("Хариуцах хэрэглэгчийг сонгоно уу."))
        if ticket.team_id is None:
            raise ActionError(_("Энэ ticket-ийн ангилалд баг тохируулаагүй тул оноох боломжгүй."))
        ticket.assigned_to = _team_member(ticket, assignee_id)

    previous = ticket.status
    try:
        ticket.transition_to(new_status, user=user, comment=comment)
    except ValidationError as exc:
        raise ActionError("; ".join(exc.messages))
    notify_status_changed(ticket, previous, new_status, changed_by=user)
    if new_status == Ticket.Status.ASSIGNED:
        notify_ticket_assigned(ticket, changed_by=user)


def reassign(ticket, assignee_id, user):
    """Оноогдсон ticket-ийн хариуцагчийг солино. Өөрчлөгдсөн бол True."""
    if not can_user_reassign(ticket, user):
        raise ActionError(_("Танд хариуцагч солих эрх байхгүй."))
    member = _team_member(ticket, assignee_id)
    if member.id == ticket.assigned_to_id:
        return False
    old_name = ticket.assigned_to.username if ticket.assigned_to else _("Оноогдоогүй")
    ticket.assigned_to = member
    ticket.save(update_fields=["assigned_to", "updated_at"])
    Comment.objects.create(
        ticket=ticket,
        author=user,
        body=_("Хариуцагч солигдлоо: %(old)s → %(new)s") % {"old": old_name, "new": member.username},
    )
    ticket.mark_activity()
    notify_ticket_assigned(ticket, changed_by=user)
    return True


def assign(ticket, assignee_id, user):
    """Шинэ ticket-ийг оноох, эсвэл аль хэдийн оноогдсоных бол хариуцагчийг солих."""
    if ticket.status == Ticket.Status.NEW:
        transition(ticket, Ticket.Status.ASSIGNED, user, assignee_id=assignee_id)
        return True
    return reassign(ticket, assignee_id, user)


def change_priority(ticket, priority, user):
    if not can_user_assign(user, ticket):
        raise ActionError(_("Чухлын зэргийг зөвхөн PM/Admin эсвэл багийн Team Lead өөрчилнө."))
    if ticket.status in ("closed", "rejected"):
        raise ActionError(_("Хаагдсан / татгалзсан ticket-ийн чухлын зэргийг өөрчлөхгүй."))
    if priority not in Ticket.Priority.values:
        raise ActionError(_("Буруу чухлын зэрэг."))
    return ticket.change_priority(priority, user=user)
