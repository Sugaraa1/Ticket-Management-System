from django.urls import path

from . import views

app_name = "projects"

urlpatterns = [
    path("projects/", views.project_list, name="project_list"),
    path("projects/new/", views.project_create, name="project_create"),
    path("projects/<int:pk>/", views.project_edit, name="project_edit"),
    path("projects/<int:pk>/modules/new/", views.module_create, name="module_create"),
]
