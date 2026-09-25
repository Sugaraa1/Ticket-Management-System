from django.urls import path

from . import views

app_name = "tickets"

urlpatterns = [
    path("", views.ticket_list, name="ticket_list"),
    path("my-work/", views.dashboard, name="dashboard"),
    path("my-team/", views.my_team, name="my_team"),
    path("my-team/<int:pk>/dashboard/", views.team_report, name="team_report"),
    path("tickets/new/", views.ticket_create, name="ticket_create"),
    path("tickets/bulk/", views.ticket_bulk, name="ticket_bulk"),
    path("tickets/<int:pk>/", views.ticket_detail, name="ticket_detail"),
    path("tickets/<int:pk>/edit/", views.ticket_edit, name="ticket_edit"),
    path("dashboard/", views.reports, name="reports"),
    path("attachments/<int:pk>/", views.attachment_download, name="attachment_download"),
]
