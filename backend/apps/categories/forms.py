from django import forms
from django.contrib.auth.models import User

from .models import Category, CategoryTeamAssignment, Team


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "description"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }
        labels = {"name": "Нэр", "description": "Тайлбар"}


class TeamForm(forms.ModelForm):
    class Meta:
        model = Team
        fields = ["name"]
        widgets = {"name": forms.TextInput(attrs={"class": "form-control"})}
        labels = {"name": "Багийн нэр"}


class TeamMembersForm(forms.Form):
    members = forms.ModelMultipleChoiceField(
        queryset=User.objects.filter(groups__name="Developer").distinct().order_by("username"),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label="Багийн гишүүд (Developer group-ийн хэрэглэгчид)",
    )


class CategoryTeamAssignmentForm(forms.ModelForm):
    class Meta:
        model = CategoryTeamAssignment
        fields = ["team", "team_lead", "qa_tester"]
        widgets = {
            "team": forms.Select(attrs={"class": "form-select"}),
            "team_lead": forms.Select(attrs={"class": "form-select"}),
            "qa_tester": forms.Select(attrs={"class": "form-select"}),
        }
        labels = {
            "team": "Баг (routing энд очно)",
            "team_lead": "Team Lead",
            "qa_tester": "QA Tester",
        }
