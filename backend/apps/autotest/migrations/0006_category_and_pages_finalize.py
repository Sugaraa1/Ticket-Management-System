from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    """0005-ийн өгөгдөл шилжүүлсний дараа — тусдаа transaction (Postgres: pending trigger events)."""

    dependencies = [
        ("autotest", "0005_category_and_pages"),
    ]

    operations = [
        migrations.AlterField(
            model_name="testapp",
            name="category",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="test_apps", to="categories.category",
            ),
        ),
        migrations.AlterField(
            model_name="datafile",
            name="category",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT, related_name="test_data_files",
                to="categories.category",
            ),
        ),
        migrations.AlterField(
            model_name="scenario",
            name="page",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.RESTRICT, related_name="scenarios", to="autotest.page",
                verbose_name="Хуудас",
            ),
        ),
        migrations.RemoveField(model_name="testapp", name="project"),
        migrations.RemoveField(model_name="datafile", name="project"),
        migrations.RemoveField(model_name="scenario", name="page_path"),
        migrations.AddConstraint(
            model_name="testapp",
            constraint=models.UniqueConstraint(fields=("category", "name"), name="autotest_unique_app_name"),
        ),
        migrations.AddConstraint(
            model_name="page",
            constraint=models.UniqueConstraint(fields=("app", "name"), name="autotest_unique_page_name"),
        ),
        migrations.AddConstraint(
            model_name="page",
            constraint=models.UniqueConstraint(fields=("app", "path"), name="autotest_unique_page_path"),
        ),
    ]
