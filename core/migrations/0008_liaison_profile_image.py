# Manual migration: add profile_image to Liaison for profile edit
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_merge_20260304_0531'),
    ]

    operations = [
        migrations.AddField(
            model_name='liaison',
            name='profile_image',
            field=models.CharField(blank=True, help_text='Path to profile photo in MEDIA', max_length=255, null=True),
        ),
    ]
