from django.contrib import admin

from .models import DataFile, Environment, Scenario, TestApp, TestRun


class EnvironmentInline(admin.TabularInline):
    model = Environment
    extra = 0


@admin.register(TestApp)
class TestAppAdmin(admin.ModelAdmin):
    list_display = ("name", "project", "created_at")
    list_filter = ("project",)
    inlines = [EnvironmentInline]


@admin.register(Scenario)
class ScenarioAdmin(admin.ModelAdmin):
    list_display = ("name", "app", "page_path", "success_mode")
    list_filter = ("app",)


@admin.register(DataFile)
class DataFileAdmin(admin.ModelAdmin):
    list_display = ("name", "project", "row_count", "updated_at")
    list_filter = ("project",)


@admin.register(TestRun)
class TestRunAdmin(admin.ModelAdmin):
    list_display = ("id", "scenario", "environment_name", "status", "passed", "failed", "errored", "total", "created_at")
    list_filter = ("status",)
