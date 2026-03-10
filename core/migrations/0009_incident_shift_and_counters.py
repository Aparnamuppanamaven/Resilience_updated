from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0007_rename_countee_to_county"),
        ("core", "0008_liaison_profile_image"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="IncidentShiftSchedule",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        ("shift_hours", models.IntegerField()),
                        ("created_by", models.BigIntegerField()),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        (
                            "incident",
                            models.ForeignKey(
                                on_delete=models.deletion.CASCADE,
                                related_name="shift_schedules",
                                db_column="incident_id",
                                to="core.incident",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "core_incident_shift_schedule",
                        "ordering": ["-created_at"],
                    },
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        CREATE TABLE IF NOT EXISTS core_incident_shift_schedule (
                            id BIGINT PRIMARY KEY AUTO_INCREMENT,
                            incident_id BIGINT,
                            shift_hours INT,
                            created_by BIGINT,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                        );
                    """,
                    reverse_sql="""
                        DROP TABLE IF EXISTS core_incident_shift_schedule;
                    """,
                ),
            ],
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="AgencyUserCounter",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        ("admin_user_id", models.BigIntegerField()),
                        ("cnt_allowed", models.IntegerField(default=2)),
                        ("current_cnt", models.IntegerField(default=0)),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        (
                            "organization",
                            models.ForeignKey(
                                on_delete=models.deletion.CASCADE,
                                related_name="user_counters",
                                db_column="organization_id",
                                to="core.organization",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "core_agency_user_counter",
                        "ordering": ["-created_at"],
                    },
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        CREATE TABLE IF NOT EXISTS core_agency_user_counter (
                            id BIGINT PRIMARY KEY AUTO_INCREMENT,
                            organization_id BIGINT,
                            admin_user_id BIGINT,
                            cnt_allowed INT DEFAULT 2,
                            current_cnt INT DEFAULT 0,
                            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                        );
                    """,
                    reverse_sql="""
                        DROP TABLE IF EXISTS core_agency_user_counter;
                    """,
                ),
            ],
        ),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.CreateModel(
                    name="ShiftPacketHistory",
                    fields=[
                        (
                            "id",
                            models.BigAutoField(
                                auto_created=True,
                                primary_key=True,
                                serialize=False,
                                verbose_name="ID",
                            ),
                        ),
                        ("input", models.TextField(blank=True)),
                        ("what_happened", models.TextField(blank=True)),
                        ("next_steps", models.TextField(blank=True)),
                        ("tx_type", models.CharField(max_length=20)),
                        (
                            "created_by",
                            models.BigIntegerField(blank=True, null=True),
                        ),
                        (
                            "updated_by",
                            models.BigIntegerField(blank=True, null=True),
                        ),
                        ("created_at", models.DateTimeField(auto_now_add=True)),
                        ("updated_at", models.DateTimeField(auto_now=True)),
                        (
                            "incident",
                            models.ForeignKey(
                                on_delete=models.deletion.SET_NULL,
                                related_name="shiftpacket_history",
                                null=True,
                                blank=True,
                                db_column="incident_id",
                                to="core.incident",
                            ),
                        ),
                        (
                            "shift",
                            models.BigIntegerField(
                                null=True,
                                blank=True,
                                db_column="shift_id",
                            ),
                        ),
                        (
                            "shiftpacket",
                            models.ForeignKey(
                                on_delete=models.deletion.CASCADE,
                                related_name="history",
                                db_column="shiftpacket_id",
                                to="core.shiftpacket",
                            ),
                        ),
                    ],
                    options={
                        "db_table": "core_shiftpacket_history",
                        "ordering": ["-created_at"],
                    },
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="""
                        CREATE TABLE IF NOT EXISTS core_shiftpacket_history (
                            id BIGINT PRIMARY KEY AUTO_INCREMENT,
                            shiftpacket_id BIGINT,
                            incident_id BIGINT,
                            shift_id BIGINT,
                            input TEXT,
                            what_happened TEXT,
                            next_steps TEXT,
                            tx_type VARCHAR(20),
                            created_by BIGINT,
                            updated_by BIGINT,
                            created_at DATETIME,
                            updated_at DATETIME
                        );
                    """,
                    reverse_sql="""
                        DROP TABLE IF EXISTS core_shiftpacket_history;
                    """,
                ),
            ],
        ),
    ]

