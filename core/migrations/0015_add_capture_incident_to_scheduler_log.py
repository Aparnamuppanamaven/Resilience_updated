from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_shiftpacket_scheduler_log"),
    ]

    operations = [
        migrations.AddField(
            model_name="shiftpacketschedulerlog",
            name="capture_incident",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.SET_NULL,
                related_name="scheduler_logs",
                to="core.incidentcapture",
                db_column="capture_incident_id",
                help_text="Reference to core_incidents (capture incident).",
            ),
        ),
    ]
