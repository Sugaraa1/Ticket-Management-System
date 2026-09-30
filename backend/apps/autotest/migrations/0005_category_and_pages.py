"""
Апп, өгөгдлийн файл төслийн оронд ангилалд харьяалагдана; сценарийн замыг апп-ын
хуудас (Page) болгоно. Байгаа өгөгдлийг шилжүүлнэ:
  - апп, файл → эхний ангилал (ангилал байхгүй бол "Автомат тест" үүсгэнэ)
  - сценари бүрийн page_path → тухайн апп-ын Page (ижил замтай бол нэгийг хуваалцана)
"""
import django.db.models.deletion
from django.db import migrations, models


def forwards(apps, schema_editor):
    Category = apps.get_model("categories", "Category")
    TestApp = apps.get_model("autotest", "TestApp")
    DataFile = apps.get_model("autotest", "DataFile")
    Page = apps.get_model("autotest", "Page")
    Scenario = apps.get_model("autotest", "Scenario")

    if TestApp.objects.exists() or DataFile.objects.exists():
        category = Category.objects.order_by("name").first() or Category.objects.create(name="Автомат тест")
        # Өөр төслүүдэд ижил нэртэй апп байж болно — нэг ангилалд давхардахгүй болгоно.
        used = set()
        for app in TestApp.objects.order_by("pk"):
            name, n = app.name, 2
            while name.lower() in used:
                name, n = f"{app.name} {n}"[:150], n + 1
            used.add(name.lower())
            TestApp.objects.filter(pk=app.pk).update(category=category, name=name)
        DataFile.objects.update(category=category)

    for scenario in Scenario.objects.order_by("pk"):
        path = (scenario.page_path or "").strip()
        page = Page.objects.filter(app_id=scenario.app_id, path=path).first()
        if page is None:
            base = scenario.name or path or "/"
            name, n = base, 2
            while Page.objects.filter(app_id=scenario.app_id, name=name).exists():
                name, n = f"{base} {n}"[:150], n + 1
            page = Page.objects.create(app_id=scenario.app_id, name=name[:150], path=path)
        Scenario.objects.filter(pk=scenario.pk).update(page=page)


class Migration(migrations.Migration):

    dependencies = [
        ("categories", "0007_subcategory"),
        ("autotest", "0004_optional_page_path"),
    ]

    operations = [
        migrations.CreateModel(
            name="Page",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(help_text="Жишээ: Бүртгүүлэх", max_length=150, verbose_name="Хуудас")),
                ("path", models.CharField(
                    blank=True, help_text="Орчны хаягаас хойших зам. Хоосон бол орчны хаягийг шууд нээнэ.",
                    max_length=500, verbose_name="Зам",
                )),
                ("app", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name="pages", to="autotest.testapp",
                )),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.AddField(
            model_name="testapp",
            name="category",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT, related_name="test_apps",
                to="categories.category",
            ),
        ),
        migrations.AddField(
            model_name="testapp",
            name="subcategory",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="test_apps",
                to="categories.subcategory",
            ),
        ),
        migrations.AddField(
            model_name="datafile",
            name="category",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT, related_name="test_data_files",
                to="categories.category",
            ),
        ),
        migrations.AddField(
            model_name="scenario",
            name="page",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.RESTRICT, related_name="scenarios",
                to="autotest.page", verbose_name="Хуудас",
            ),
        ),
        migrations.RemoveConstraint(model_name="testapp", name="autotest_unique_app_name"),
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
