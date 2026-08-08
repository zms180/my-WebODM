import django.contrib.postgres.fields.jsonb
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0051_init_basemaps'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='original_image_size',
            field=django.contrib.postgres.fields.jsonb.JSONField(blank=True, default=dict, help_text='Pixel dimensions of the original task images', verbose_name='Original Image Size'),
        ),
    ]
