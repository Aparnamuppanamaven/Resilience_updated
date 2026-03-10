from django.db import migrations, models, connection


def add_column_if_not_exists(table_name, column_name, column_def):
    """Safely add a column if it doesn't already exist."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = %s
              AND COLUMN_NAME = %s
            """,
            [table_name, column_name],
        )
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_def}"
            )


def alter_core_shiftpacket(apps, schema_editor):
    add_column_if_not_exists("core_shiftpacket", "previous_shift_info", "TEXT")
    add_column_if_not_exists("core_shiftpacket", "what_happened", "TEXT")
    add_column_if_not_exists("core_shiftpacket", "next_steps", "TEXT")
    add_column_if_not_exists("core_shiftpacket", "tx_type", "VARCHAR(20)")
    add_column_if_not_exists("core_shiftpacket", "updated_at", "DATETIME")


def alter_core_operationalupdate(apps, schema_editor):
    add_column_if_not_exists("core_operationalupdate", "status", "VARCHAR(20)")


def alter_core_incidents(apps, schema_editor):
    add_column_if_not_exists("core_incidents", "severity", "VARCHAR(20)")
    add_column_if_not_exists("core_incidents", "status", "VARCHAR(20)")
    add_column_if_not_exists("core_incidents", "resolved_at", "DATETIME")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_incident_shift_and_counters"),
    ]

    operations = [
        # 1) core_shiftpacket: add previous_shift_info, what_happened,
        #    next_steps, tx_type, updated_at
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="shiftpacket",
                    name="previous_shift_info",
                    field=models.TextField(blank=True),
                ),
                migrations.AddField(
                    model_name="shiftpacket",
                    name="what_happened",
                    field=models.TextField(blank=True),
                ),
                migrations.AddField(
                    model_name="shiftpacket",
                    name="next_steps",
                    field=models.TextField(blank=True),
                ),
                migrations.AddField(
                    model_name="shiftpacket",
                    name="tx_type",
                    field=models.CharField(
                        max_length=20,
                        blank=True,
                        choices=[
                            ("AI", "AI"),
                            ("Manual", "Manual"),
                        ],
                    ),
                ),
                migrations.AddField(
                    model_name="shiftpacket",
                    name="updated_at",
                    field=models.DateTimeField(auto_now=True),
                ),
            ],
            database_operations=[],
        ),
        migrations.RunPython(
            alter_core_shiftpacket,
            reverse_code=migrations.RunPython.noop,
        ),
        # 2) core_operationalupdate: add status
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="incident",
                    name="status",
                    field=models.CharField(
                        max_length=20,
                        default="Open",
                        choices=[
                            ("Open", "Open"),
                            ("Investigating", "Investigating"),
                            ("Resolved", "Resolved"),
                        ],
                    ),
                ),
                migrations.AddField(
                    model_name="operationalupdate",
                    name="status",
                    field=models.CharField(
                        max_length=20,
                        default="Open",
                        choices=[
                            ("Open", "Open"),
                            ("Investigating", "Investigating"),
                            ("Resolved", "Resolved"),
                        ],
                    ),
                ),
            ],
            database_operations=[],
        ),
        migrations.RunPython(
            alter_core_operationalupdate,
            reverse_code=migrations.RunPython.noop,
        ),
        # 3) core_incidents: add severity, status, resolved_at (DB only).
        # We keep model changes in code only and avoid state_operations here
        # because IncidentCapture is a managed=False legacy mapping.
        migrations.RunPython(
            alter_core_incidents,
            reverse_code=migrations.RunPython.noop,
        ),
    ]

