from django.db import models

from apps.core.models import TimeStampedModel


class Project(TimeStampedModel):
    name = models.CharField(max_length=150, unique=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Module(TimeStampedModel):
    project = models.ForeignKey(Project, related_name="modules", on_delete=models.CASCADE)
    name = models.CharField(max_length=150)

    class Meta:
        unique_together = ("project", "name")
        ordering = ["project__name", "name"]

    def __str__(self):
        return f"{self.project.name} / {self.name}"
