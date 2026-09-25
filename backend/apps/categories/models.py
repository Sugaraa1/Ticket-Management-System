from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from apps.core.models import TimeStampedModel


class Team(TimeStampedModel):
    """Ticket шийдвэрлэдэг хөгжүүлэлтийн баг."""

    name = models.CharField(max_length=100, unique=True)
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="teams",
        blank=True,
        limit_choices_to=Q(groups__name="Developer") | Q(is_superuser=True),
        help_text=_(
            "Энэ багт харьяалагдах ажилчид. Ticket assign хийхэд зөвхөн эдгээр "
            "хэрэглэгчид сонголтод гарна."
        ),
    )
    team_lead = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="led_teams",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"is_active": True},
        help_text=_(
            "Ямар ч идэвхтэй хэрэглэгчийг томилж болно. Team Lead нь өөрийн багийн "
            "ticket-ийг оноох, хариуцагч солих, багийн dashboard харах эрхтэй."
        ),
    )
    qa_tester = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="qa_teams",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to=Q(groups__name="QA Tester") | Q(is_superuser=True),
        help_text=_("'QA Tester' group-т багтсан (эсвэл superuser) хэрэглэгчид л сонголтод гарна."),
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Category(TimeStampedModel):
    """Ticket-ийн ангилал (ж: Backend API, UI/UX, Database)."""

    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class CategoryTeamAssignment(TimeStampedModel):
    """
    Category бүрийг аль Team(үүд) рүү автоматаар чиглүүлэхийг тодорхойлно.
    Team Lead / QA Tester нь Team дээр тохируулагдана.

    Нэг Category олон Team-тэй холбогдож болно — ticket үүсэхэд тэдгээрээс
    хамгийн бага идэвхтэй ачаалалтай багт автоматаар чиглэнэ.
    """

    category = models.ForeignKey(
        Category, related_name="team_assignments", on_delete=models.CASCADE
    )
    team = models.ForeignKey(
        Team, related_name="category_assignments", on_delete=models.PROTECT
    )

    class Meta:
        unique_together = [("category", "team")]
        verbose_name = "Category → Team Assignment"
        verbose_name_plural = "Category → Team Assignments"

    def __str__(self):
        return f"{self.category.name} → {self.team.name}"


def route_team_for_category(category_id):
    """Category-ийн багуудаас хамгийн цөөн идэвхтэй ticket-тэй багийг буцаана."""
    from django.db.models import Count, Q

    active = ["new", "assigned", "in_progress", "resolved", "qa_test", "reopened"]
    return (
        Team.objects.filter(category_assignments__category_id=category_id)
        .annotate(load=Count("tickets", filter=Q(tickets__status__in=active)))
        .order_by("load", "id")
        .first()
    )
