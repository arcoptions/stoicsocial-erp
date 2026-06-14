import uuid

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0003_banktransaction_expense_invoice_invoicelineitem_and_more"),
    ]

    operations = [
        migrations.CreateModel(
            name="DeletedInventoryItem",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, primary_key=True, serialize=False, editable=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("record_type", models.CharField(choices=[("blank_sku", "Plain SKU"), ("printed_sku", "Printed SKU")], max_length=30)),
                ("source_model_id", models.CharField(max_length=64)),
                ("label", models.CharField(max_length=255)),
                ("payload", models.JSONField(default=dict)),
                ("restored_at", models.DateTimeField(blank=True, null=True)),
                (
                    "deleted_by",
                    models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="deleted_inventory_items", to=settings.AUTH_USER_MODEL),
                ),
            ],
            options={
                "ordering": ["-created_at"],
            },
        ),
    ]
