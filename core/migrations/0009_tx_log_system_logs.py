# System logs / audit trail: tx_log table
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_liaison_profile_image'),
    ]

    operations = [
        migrations.CreateModel(
            name='TxLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ('tenant_id', models.BigIntegerField(blank=True, db_column='tenant_id', null=True)),
                ('entity', models.CharField(help_text='Module or object affected, e.g. User, Incident, SituationUpdate', max_length=100)),
                ('actionby', models.BigIntegerField(blank=True, db_column='actionby', help_text='User ID who performed the action (auth User or UserCredentials)', null=True)),
                ('actionon', models.CharField(blank=True, db_column='actionon', help_text='ID or name of the entity on which action was performed', max_length=255)),
                ('action', models.CharField(choices=[('Create', 'Create'), ('Update', 'Update'), ('Delete', 'Delete'), ('Login', 'Login')], max_length=50)),
                ('created_date', models.DateTimeField(auto_now_add=True, db_column='created_date')),
            ],
            options={
                'verbose_name': 'System log',
                'verbose_name_plural': 'System logs',
                'db_table': 'tx_log',
                'ordering': ['-created_date'],
            },
        ),
    ]
