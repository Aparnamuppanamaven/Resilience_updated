from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_department_incidentcapture_shift_situationupdate_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="ShiftPacketSchedulerLog",
            fields=[
                ("run_id", models.BigAutoField(primary_key=True, serialize=False)),
                (
                    "incident",
                    models.ForeignKey(
                        on_delete=models.CASCADE,
                        related_name="scheduler_logs",
                        to="core.incident",
                        db_column="incident_id",
                    ),
                ),
                ("triggered_at", models.DateTimeField()),
                ("next_scheduled", models.DateTimeField()),
                (
                    "schedule_status",
                    models.CharField(
                        choices=[("generated", "Generated"), ("failed", "Failed")],
                        max_length=20,
                    ),
                ),
                ("message", models.TextField(blank=True, null=True)),
            ],
            options={
                "db_table": "core_shiftpacket_scheduler_log",
                "ordering": ["-triggered_at"],
            },
        ),
    ]
