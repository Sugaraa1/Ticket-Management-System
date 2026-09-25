from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("profile/avatar/", views.avatar_update, name="avatar_update"),
    path("users/", views.user_list, name="user_list"),
    path("users/new/", views.user_create, name="user_create"),
    path("users/<int:pk>/edit/", views.user_edit, name="user_edit"),
    path("users/<int:pk>/delete/", views.user_delete, name="user_delete"),
    path("users/<int:pk>/deactivate/", views.user_deactivate, name="user_deactivate"),
    path("users/<int:pk>/activate/", views.user_activate, name="user_activate"),
]
