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


def add_tenant_id_columns(apps, schema_editor):
    add_column_if_not_exists("core_incident_shift_schedule", "tenant_id", "BIGINT NULL")
    add_column_if_not_exists("core_shiftpacket_history", "tenant_id", "BIGINT NULL")
    add_column_if_not_exists("core_agency_user_counter", "tenant_id", "BIGINT NULL")


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_shiftpacket_operationalupdate_incidents_alter"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name="incidentshiftschedule",
                    name="tenant_id",
                    field=models.BigIntegerField(
                        null=True, blank=True, db_column="tenant_id"
                    ),
                ),
                migrations.AddField(
                    model_name="shiftpackethistory",
                    name="tenant_id",
                    field=models.BigIntegerField(
                        null=True, blank=True, db_column="tenant_id"
                    ),
                ),
                migrations.AddField(
                    model_name="agencyusercounter",
                    name="tenant_id",
                    field=models.BigIntegerField(
                        null=True, blank=True, db_column="tenant_id"
                    ),
                ),
            ],
            database_operations=[],
        ),
        migrations.RunPython(add_tenant_id_columns, reverse_code=migrations.RunPython.noop),
    ]
