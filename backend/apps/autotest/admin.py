from django.contrib import admin

from .models import DataFile, Environment, Page, Scenario, TestApp, TestRun


class EnvironmentInline(admin.TabularInline):
    model = Environment
    extra = 0


class PageInline(admin.TabularInline):
    model = Page
    extra = 0


@admin.register(TestApp)
class TestAppAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "created_at")
    list_filter = ("category",)
    inlines = [EnvironmentInline, PageInline]


@admin.register(Scenario)
class ScenarioAdmin(admin.ModelAdmin):
    list_display = ("name", "app", "page", "success_mode")
    list_filter = ("app",)


@admin.register(DataFile)
class DataFileAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "row_count", "updated_at")
    list_filter = ("category",)


@admin.register(TestRun)
class TestRunAdmin(admin.ModelAdmin):
    list_display = ("id", "scenario", "environment_name", "status", "passed", "failed", "errored", "total", "created_at")
    list_filter = ("status",)
