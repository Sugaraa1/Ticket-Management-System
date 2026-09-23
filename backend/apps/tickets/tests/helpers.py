"""Ticket app-ийн тестүүдэд ашиглагдах туслах fixture функцууд."""
from django.contrib.auth.models import Group, User

from apps.categories.models import Category, CategoryTeamAssignment, Team
from apps.projects.models import Project


def make_user(username, group_name=None, **kwargs):
    kwargs.setdefault("password", "pass1234")
    user = User.objects.create_user(username=username, **kwargs)
    if group_name:
        group, _ = Group.objects.get_or_create(name=group_name)
        user.groups.add(group)
    return user


def make_routed_category(team_lead=None, qa_tester=None, members=None, name="Backend API"):
    """Team + Category + CategoryTeamAssignment-ийг холбож үүсгэнэ."""
    team = Team.objects.create(
        name=f"{name} Team", team_lead=team_lead, qa_tester=qa_tester
    )
    if members:
        team.members.set(members)
    category = Category.objects.create(name=name)
    CategoryTeamAssignment.objects.create(category=category, team=team)
    return category, team


def make_project(name="Demo Project"):
    return Project.objects.create(name=name)
