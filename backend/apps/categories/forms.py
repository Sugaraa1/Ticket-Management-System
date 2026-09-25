from django import forms
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _

from .models import Category, Team


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Идэвхгүй хэрэглэгчийг сонголтоос хасна (одоо тохируулагдсан байгааг нь үлдээнэ).
        from django.db.models import Q

        for name in ("team_lead", "qa_tester"):
            current = getattr(self.instance, f"{name}_id", None)
            self.fields[name].queryset = self.fields[name].queryset.filter(
                Q(is_active=True) | Q(pk=current)
            ).distinct()


class TeamMembersForm(forms.Form):
    members = forms.ModelMultipleChoiceField(
        queryset=User.objects.filter(groups__name="Developer", is_active=True)
        .distinct()
        .order_by("username"),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label=_("Багийн гишүүд (Developer group-ийн хэрэглэгчид)"),
    )


class CategoryTeamsForm(forms.Form):
    teams = forms.ModelMultipleChoiceField(
        queryset=Team.objects.select_related("team_lead", "qa_tester").order_by("name"),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label=_("Багууд (routing энд очно)"),
        help_text=_(
            "Олон баг сонговол ticket тэдгээрээс хамгийн бага ачаалалтай багт автоматаар очно."
        ),
    )
