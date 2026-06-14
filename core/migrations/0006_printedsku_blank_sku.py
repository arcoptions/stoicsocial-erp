from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_printedsku_is_active"),
    ]

    operations = [
        migrations.AddField(
            model_name="printedsku",
            name="blank_sku",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="printed_skus",
                help_text="Explicitly linked plain blank SKU. When set, overrides auto-resolution in print batch.",
                to="core.blanksku",
            ),
        ),
    ]
