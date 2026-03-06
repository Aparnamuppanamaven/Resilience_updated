"""
Management command to create the tx_log table directly in the database.
Use this if migrations are not applied (e.g. due to conflicting migration history).
"""
from django.core.management.base import BaseCommand
from django.db import connection


# MySQL CREATE TABLE matching TxLog model (db_table='tx_log')
CREATE_TX_LOG_SQL = """
CREATE TABLE IF NOT EXISTS tx_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    tenant_id BIGINT NULL,
    entity VARCHAR(100) NOT NULL,
    actionby BIGINT NULL,
    actionon VARCHAR(255) NOT NULL DEFAULT '',
    action VARCHAR(50) NOT NULL,
    created_date DATETIME(6) NOT NULL
);
"""


class Command(BaseCommand):
    help = "Create the tx_log system log table in the database (if it does not exist)."

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute(CREATE_TX_LOG_SQL)
        self.stdout.write(self.style.SUCCESS("Table tx_log created successfully (or already exists)."))
