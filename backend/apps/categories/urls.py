from django.urls import path

from . import views

app_name = "categories"

urlpatterns = [
    path("categories/", views.category_list, name="category_list"),
    path("categories/new/", views.category_create, name="category_create"),
    path("categories/<int:pk>/edit/", views.category_edit, name="category_edit"),
    path("categories/<int:pk>/delete/", views.category_delete, name="category_delete"),
    path("categories/<int:pk>/subcategories/", views.subcategory_create, name="subcategory_create"),
    path(
        "categories/<int:pk>/subcategories/<int:sub_pk>/delete/",
        views.subcategory_delete,
        name="subcategory_delete",
    ),
    path("teams/", views.team_list, name="team_list"),
    path("teams/<int:pk>/", views.team_detail, name="team_detail"),
]
