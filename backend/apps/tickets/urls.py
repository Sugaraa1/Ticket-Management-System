from django.urls import path

from . import views

app_name = "tickets"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("tickets/", views.ticket_list, name="ticket_list"),
    path("tickets/new/", views.ticket_create, name="ticket_create"),
    path("tickets/<int:pk>/", views.ticket_detail, name="ticket_detail"),
    path("reports/", views.reports, name="reports"),
    path("sla/check/", views.run_sla_check, name="run_sla_check"),
    path("automation/stale-check/", views.run_stale_check, name="run_stale_check"),
]
