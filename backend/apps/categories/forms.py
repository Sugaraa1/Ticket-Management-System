from django import forms
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _

from .models import Category, CategoryTeamAssignment, Team


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "description"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }
        labels = {"name": _("Нэр"), "description": _("Тайлбар")}


class TeamForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ["name", "team_lead", "qa_tester"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "team_lead": forms.Select(attrs={"class": "form-select"}),
            "qa_tester": forms.Select(attrs={"class": "form-select"}),
        }
        labels = {
            "name": _("Багийн нэр"),
            "team_lead": "Team Lead",
            "qa_tester": "QA Tester",
        }


class TeamMembersForm(forms.Form):
    members = forms.ModelMultipleChoiceField(
        queryset=User.objects.filter(groups__name="Developer").distinct().order_by("username"),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label=_("Багийн гишүүд (Developer group-ийн хэрэглэгчид)"),
    )


class CategoryTeamAssignmentForm(forms.ModelForm):
    class Meta:
        model = CategoryTeamAssignment
        fields = ["team"]
        widgets = {
            "team": forms.Select(attrs={"class": "form-select"}),
        }
        labels = {
            "team": _("Баг (routing энд очно)"),
        }
