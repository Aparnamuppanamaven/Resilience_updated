# Manual migration: add profile_image to Liaison for profile edit
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_merge_20260304_0531'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddField(
                    model_name='liaison',
                    name='profile_image',
                    field=models.CharField(
                        blank=True,
                        null=True,
                        max_length=255,
                        help_text='Path to profile photo in MEDIA',
                    ),
                ),
            ],
            database_operations=[
                # No-op at DB level: profile_image already exists on the
                # underlying liaison table in the legacy schema.
            ],
        ),
    ]
