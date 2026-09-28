from django.contrib import admin

from .models import Category, CategoryTeamAssignment, Subcategory, Team


class SubcategoryInline(admin.TabularInline):
    model = Subcategory
    extra = 0


class CategoryTeamAssignmentInline(admin.StackedInline):
    model = CategoryTeamAssignment
    extra = 0


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "description")
    search_fields = ("name",)
    inlines = [SubcategoryInline, CategoryTeamAssignmentInline]


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "team_lead", "qa_tester")
    search_fields = ("name",)


@admin.register(CategoryTeamAssignment)
class CategoryTeamAssignmentAdmin(admin.ModelAdmin):
    list_display = ("category", "team")
    list_filter = ("team",)
