from django.urls import path

from . import views

app_name = "categories"

urlpatterns = [
    path("categories/", views.category_list, name="category_list"),
    path("categories/new/", views.category_create, name="category_create"),
    path("categories/<int:pk>/edit/", views.category_edit, name="category_edit"),
    path("teams/", views.team_list, name="team_list"),
    path("teams/<int:pk>/", views.team_detail, name="team_detail"),
]
