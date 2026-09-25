from django.urls import path

from . import views

app_name = "projects"

urlpatterns = [
    path("projects/", views.project_list, name="project_list"),
    path("projects/new/", views.project_create, name="project_create"),
    path("projects/<int:pk>/", views.project_edit, name="project_edit"),
    path("projects/<int:pk>/delete/", views.project_delete, name="project_delete"),
    path("projects/<int:pk>/toggle-active/", views.project_toggle_active, name="project_toggle_active"),
    path("projects/<int:pk>/modules/new/", views.module_create, name="module_create"),
    path("projects/<int:pk>/modules/<int:module_pk>/edit/", views.module_edit, name="module_edit"),
    path("projects/<int:pk>/modules/<int:module_pk>/delete/", views.module_delete, name="module_delete"),
]
