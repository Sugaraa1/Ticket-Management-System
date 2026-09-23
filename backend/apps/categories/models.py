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
        limit_choices_to=Q(groups__name="Project Manager") | Q(is_superuser=True),
        help_text=_("'Project Manager' group-т багтсан (эсвэл superuser) хэрэглэгчид л сонголтод гарна."),
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
    Category бүрийг аль Team рүү автоматаар chиглүүлэхийг тодорхойлно.
    Team Lead / QA Tester нь Team дээр тохируулагдана.

    Нэг Category зөвхөн нэг Team-тэй холбогдоно (routing-ийг энгийн байлгах үүднээс).
    """

    category = models.OneToOneField(
        Category, related_name="team_assignment", on_delete=models.CASCADE
    )
    team = models.ForeignKey(
        Team, related_name="category_assignments", on_delete=models.PROTECT
    )

    class Meta:
        verbose_name = "Category → Team Assignment"
        verbose_name_plural = "Category → Team Assignments"

    def __str__(self):
        return f"{self.category.name} → {self.team.name}"
