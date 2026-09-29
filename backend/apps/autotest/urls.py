from django.urls import path

from . import views

app_name = "autotest"

urlpatterns = [
    path("", views.home, name="home"),
    path("apps/new/", views.app_create, name="app_create"),
    path("apps/<int:pk>/", views.app_detail, name="app_detail"),
    path("apps/<int:pk>/delete/", views.app_delete, name="app_delete"),
    path("apps/<int:pk>/environments/new/", views.env_create, name="env_create"),
    path("apps/<int:pk>/environments/<int:env_pk>/delete/", views.env_delete, name="env_delete"),
    path("apps/<int:pk>/scenarios/new/", views.scenario_create, name="scenario_create"),
    path("apps/<int:pk>/scan/", views.scan_create, name="scan_create"),
    path("apps/<int:pk>/scans/<int:scan_pk>/generate/", views.scan_generate, name="scan_generate"),
    path("scans/<int:pk>/", views.scan_status, name="scan_status"),
    path("files/", views.datafile_list, name="datafile_list"),
    path("files/new/", views.datafile_create, name="datafile_create"),
    path("files/template/", views.template_download, name="template_download"),
    path("files/<int:pk>/", views.datafile_detail, name="datafile_detail"),
    path("files/<int:pk>/replace/", views.datafile_replace, name="datafile_replace"),
    path("files/<int:pk>/delete/", views.datafile_delete, name="datafile_delete"),
    path("files/<int:pk>/rows/", views.datafile_save_rows, name="datafile_save_rows"),
    path("files/<int:pk>/preview/", views.datafile_preview, name="datafile_preview"),
    path("files/<int:pk>/mapping/", views.datafile_mapping, name="datafile_mapping"),
    path("files/<int:pk>/download/", views.datafile_download, name="datafile_download"),
    path("scenarios/<int:pk>/", views.scenario_detail, name="scenario_detail"),
    path("scenarios/<int:pk>/edit/", views.scenario_edit, name="scenario_edit"),
    path("scenarios/<int:pk>/delete/", views.scenario_delete, name="scenario_delete"),
    path("scenarios/<int:pk>/run/", views.run_create, name="run_create"),
    path("runs/<int:pk>/", views.run_detail, name="run_detail"),
    path("runs/<int:pk>/status/", views.run_status, name="run_status"),
    path("runs/<int:pk>/cancel/", views.run_cancel, name="run_cancel"),
    path("runs/<int:pk>/rerun/", views.run_rerun, name="run_rerun"),
    path("runs/<int:pk>/export/", views.run_export, name="run_export"),
    path("runs/<int:pk>/bug-ticket/", views.bug_ticket, name="bug_ticket"),
    path("results/<int:pk>/screenshot/", views.result_screenshot, name="result_screenshot"),
]
