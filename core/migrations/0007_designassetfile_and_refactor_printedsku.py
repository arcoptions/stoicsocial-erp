# Generated migration for schema refactor

from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_printedsku_blank_sku"),
    ]

    operations = [
        # 1. Add blank_sku_id to DesignAsset
        migrations.AddField(
            model_name="designasset",
            name="blank_sku",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="design_assets",
                to="core.blanksku",
                help_text="Linked plain blank SKU for this design+colour. All sizes of this design will use this blank SKU.",
            ),
        ),
        
        # 2. Create DesignAssetFile model for mockup tracking
        migrations.CreateModel(
            name="DesignAssetFile",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "file_type",
                    models.CharField(
                        choices=[
                            ("mockup", "Mockup Image (Preview)"),
                            ("print_file", "Print File (Production)"),
                            ("artwork", "Artwork Source"),
                        ],
                        help_text="Type of file: mockup for preview, print_file for actual printing",
                        max_length=30,
                    ),
                ),
                (
                    "placement",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("front", "Front"),
                            ("back", "Back"),
                            ("sleeve", "Sleeve"),
                            ("full", "Full Print"),
                        ],
                        help_text="Where this file applies (front, back, sleeve, etc.)",
                        max_length=30,
                    ),
                ),
                ("file_url", models.URLField(max_length=600, help_text="URL or path to the file")),
                (
                    "design_asset",
                    models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="files", to="core.designasset"),
                ),
            ],
            options={
                "abstract": False,
            },
        ),
        
        # 3. Add design_asset_id and is_test_data to PrintedSKU
        migrations.AddField(
            model_name="printedsku",
            name="design_asset",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="printed_skus",
                to="core.designasset",
                help_text="Reference to the design+colour asset. Preferred over design+colour fields.",
            ),
        ),
        migrations.AddField(
            model_name="printedsku",
            name="is_test_data",
            field=models.BooleanField(
                default=False,
                help_text="Mark as test data to enable cleanup/filtering of test orders and inventory",
            ),
        ),
        
        # 4. Add is_test_data to Order
        migrations.AddField(
            model_name="order",
            name="is_test_data",
            field=models.BooleanField(
                default=False,
                help_text="Mark as test data to enable cleanup/filtering of test orders",
            ),
        ),
    ]

