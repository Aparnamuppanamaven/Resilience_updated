from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_department_incidentcapture_shift_situationupdate_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="Agency",
            fields=[
                ("agency_id", models.CharField(db_column="agency_id", max_length=50, primary_key=True, serialize=False)),
                ("agency_name", models.CharField(db_column="agency_name", max_length=255)),
                ("admin_user_id", models.CharField(blank=True, db_column="admin_user_id", default="", max_length=255)),
                ("allowed_users", models.PositiveIntegerField(db_column="allowed_users", default=25)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_column="created_at")),
            ],
            options={
                "db_table": "core_agency",
                "ordering": ["agency_name"],
            },
        ),
    ]

