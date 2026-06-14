from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0004_deletedinventoryitem"),
    ]

    operations = [
        migrations.AddField(
            model_name="printedsku",
            name="is_active",
            field=models.BooleanField(default=True),
        ),
    ]
