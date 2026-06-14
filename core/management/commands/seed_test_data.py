"""
Management command to seed test data for local development and testing.

Usage:
    python manage.py seed_test_data --full    # Full seed with all data
    python manage.py seed_test_data --designs  # Only designs
    python manage.py seed_test_data --clean    # Clear all data first
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import Design, DesignAsset, PrintedSKU, Vendor, BlankSKU, Order, OrderLine


class Command(BaseCommand):
    help = "Seed test data for BoldERP application"

    def add_arguments(self, parser):
        parser.add_argument(
            "--clean",
            action="store_true",
            help="Clear all data before seeding",
        )
        parser.add_argument(
            "--designs",
            action="store_true",
            help="Only seed designs and assets",
        )
        parser.add_argument(
            "--full",
            action="store_true",
            help="Seed all data including designs, SKUs, and orders",
        )

    def log(self, msg: str, style_func=None):
        if style_func:
            self.stdout.write(style_func(msg))
        else:
            self.stdout.write(msg)

    def create_designs(self):
        """Create sample designs with assets."""
        designs_data = [
            {
                "name": "Classic Tee",
                "material": "100% Cotton",
                "fit": Design.Fit.REGULAR,
                "assets": [
                    {
                        "colour": "Black",
                        "colour_hex": "#1b1b1b",
                        "blank_fabric": "Gildan 18000 - Black",
                    },
                    {
                        "colour": "White",
                        "colour_hex": "#ffffff",
                        "blank_fabric": "Gildan 18000 - White",
                    },
                    {
                        "colour": "Navy",
                        "colour_hex": "#000080",
                        "blank_fabric": "Gildan 18000 - Navy",
                    },
                ],
            },
            {
                "name": "Premium Fit",
                "material": "100% Cotton",
                "fit": Design.Fit.REGULAR,
                "assets": [
                    {
                        "colour": "Charcoal",
                        "colour_hex": "#36454f",
                        "blank_fabric": "Bella+Canvas 3001 - Charcoal",
                    },
                    {
                        "colour": "Heather Grey",
                        "colour_hex": "#d3d3d3",
                        "blank_fabric": "Bella+Canvas 3001 - Heather Grey",
                    },
                ],
            },
            {
                "name": "Oversized Drop Shoulder",
                "material": "100% Cotton",
                "fit": Design.Fit.OVERSIZED,
                "assets": [
                    {
                        "colour": "Black",
                        "colour_hex": "#1b1b1b",
                        "blank_fabric": "Gildan Heavy Cotton - Black",
                    },
                ],
            },
        ]

        created_designs = []
        for design_data in designs_data:
            assets = design_data.pop("assets")
            design, created = Design.objects.get_or_create(
                name=design_data["name"],
                defaults=design_data,
            )
            if created:
                self.log(f"✓ Created design: {design.name}", self.style.SUCCESS)
            else:
                self.log(f"→ Design already exists: {design.name}", self.style.WARNING)

            for asset_data in assets:
                asset_data.setdefault("artwork_url", "https://via.placeholder.com/800x800?text=Artwork")
                asset_data.setdefault("mockup_url", "https://via.placeholder.com/500x500?text=Mockup")
                asset_data.setdefault("print_areas", "Front (Chest)")

                asset, _ = DesignAsset.objects.get_or_create(
                    design=design,
                    colour=asset_data["colour"],
                    defaults=asset_data,
                )
                if _:
                    self.log(f"  ✓ Created asset: {design.name} / {asset.colour}", self.style.SUCCESS)

            created_designs.append(design)

        return created_designs

    def create_printed_skus(self, designs):
        """Create sample printed SKUs for designs."""
        sizes = ["XS", "S", "M", "L", "XL", "XXL"]
        created_skus = []

        for design in designs:
            for asset in design.assets.all():
                for size in sizes:
                    sku, created = PrintedSKU.objects.get_or_create(
                        design=design,
                        colour=asset.colour,
                        size=size,
                        defaults={
                            "on_hand": 50,  # Start with 50 of each
                            "reserved": 0,
                            "buffer_min": 5,
                            "buffer_target": 15,
                            "buffer_max": 30,
                        },
                    )
                    if created:
                        self.log(
                            f"  ✓ Created printed SKU: {design.name} / {asset.colour} / {size}",
                            self.style.SUCCESS,
                        )
                    created_skus.append(sku)

        return created_skus

    def create_blank_skus(self):
        """Create sample blank SKUs."""
        blanks_data = [
            {"fabric": "Gildan 18000", "colour": "Black", "sizes": ["S", "M", "L", "XL", "XXL"]},
            {"fabric": "Gildan 18000", "colour": "White", "sizes": ["S", "M", "L", "XL", "XXL"]},
            {"fabric": "Gildan 18000", "colour": "Navy", "sizes": ["S", "M", "L", "XL", "XXL"]},
            {"fabric": "Bella+Canvas 3001", "colour": "Charcoal", "sizes": ["S", "M", "L", "XL"]},
            {"fabric": "Bella+Canvas 3001", "colour": "Heather Grey", "sizes": ["S", "M", "L", "XL"]},
        ]

        for blank_data in blanks_data:
            sizes = blank_data.pop("sizes")
            for size in sizes:
                sku, created = BlankSKU.objects.get_or_create(
                    fabric=blank_data["fabric"],
                    colour=blank_data["colour"],
                    size=size,
                    defaults={
                        "on_hand": 200,
                        "reserved": 0,
                        "reorder_min": 50,
                        "reorder_target": 150,
                    },
                )
                if created:
                    self.log(
                        f"  ✓ Created blank SKU: {blank_data['fabric']} / {blank_data['colour']} / {size}",
                        self.style.SUCCESS,
                    )

    def create_sample_orders(self, printed_skus):
        """Create sample orders for testing."""
        orders_data = [
            {
                "shopify_order_id": "4712345678901",
                "order_no": "#1001",
                "customer_name": "John Doe",
                "email": "john@example.com",
                "lines": [
                    {
                        "shopify_line_id": "1234567890",
                        "product_name": "Classic Tee",
                        "quantity": 2,
                        "size": "M",
                        "variant": None,
                    }
                ],
            },
            {
                "shopify_order_id": "4712345678902",
                "order_no": "#1002",
                "customer_name": "Jane Smith",
                "email": "jane@example.com",
                "lines": [
                    {
                        "shopify_line_id": "1234567891",
                        "product_name": "Premium Fit",
                        "quantity": 1,
                        "size": "L",
                        "variant": None,
                    },
                    {
                        "shopify_line_id": "1234567892",
                        "product_name": "Classic Tee",
                        "quantity": 3,
                        "size": "S",
                        "variant": None,
                    },
                ],
            },
            {
                "shopify_order_id": "4712345678903",
                "order_no": "#1003",
                "customer_name": "Bob Johnson",
                "email": "bob@example.com",
                "lines": [
                    {
                        "shopify_line_id": "1234567893",
                        "product_name": "Oversized Drop Shoulder",
                        "quantity": 2,
                        "size": "XL",
                        "variant": None,
                    }
                ],
            },
        ]

        for order_data in orders_data:
            lines_data = order_data.pop("lines")
            order, created = Order.objects.get_or_create(
                shopify_order_id=order_data["shopify_order_id"],
                defaults={**order_data, "status": Order.STATUS_NEEDS_PRINTING},
            )

            if created:
                self.log(f"✓ Created order: {order.order_no} ({order.shopify_order_id})", self.style.SUCCESS)

                for line_data in lines_data:
                    product_name = line_data["product_name"]
                    size = line_data["size"]

                    # Find matching printed SKU
                    printed_sku = PrintedSKU.objects.filter(
                        design__name__iexact=product_name,
                        size__iexact=size,
                    ).first()

                    line, _ = OrderLine.objects.get_or_create(
                        shopify_line_id=line_data["shopify_line_id"],
                        defaults={
                            "order": order,
                            "product_name": product_name,
                            "quantity": line_data["quantity"],
                            "size": size,
                            "printed_sku": printed_sku,
                            "status": OrderLine.STATUS_TO_BE_PRINTED if not printed_sku else OrderLine.STATUS_READY_SHIP,
                        },
                    )
                    self.log(
                        f"  ✓ Created order line: {product_name} x {line_data['quantity']} ({size})",
                        self.style.SUCCESS,
                    )

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("BoldERP Test Data Seeding")
        self.stdout.write("=" * 60 + "\n")

        # Clean if requested
        if options["clean"]:
            self.log("🗑️  Clearing all data...", self.style.WARNING)
            Order.objects.all().delete()
            PrintedSKU.objects.all().delete()
            DesignAsset.objects.all().delete()
            Design.objects.all().delete()
            BlankSKU.objects.all().delete()
            self.log("✓ All data cleared\n", self.style.SUCCESS)

        # Create designs
        self.log("Creating Designs...", self.style.HTTP_INFO)
        designs = self.create_designs()
        self.log(f"✓ {len(designs)} design(s) ready\n", self.style.SUCCESS)

        # Skip further seeding if only designs requested
        if options["designs"]:
            self.log("✓ Design-only seed complete\n", self.style.SUCCESS)
            return

        # Create blank SKUs
        self.log("Creating Blank SKUs...", self.style.HTTP_INFO)
        self.create_blank_skus()
        self.log("✓ Blank SKUs ready\n", self.style.SUCCESS)

        # Create printed SKUs
        self.log("Creating Printed SKUs...", self.style.HTTP_INFO)
        printed_skus = self.create_printed_skus(designs)
        self.log(f"✓ {len(printed_skus)} printed SKU(s) ready\n", self.style.SUCCESS)

        # Create sample orders if full seed requested
        if options["full"]:
            self.log("Creating Sample Orders...", self.style.HTTP_INFO)
            self.create_sample_orders(printed_skus)
            self.log("✓ Sample orders created\n", self.style.SUCCESS)

        # Summary
        self.stdout.write("\n" + "=" * 60)
        self.log("✅ Data seeding complete!", self.style.SUCCESS)
        self.stdout.write("=" * 60 + "\n")

        self.log("Next Steps:", self.style.HTTP_INFO)
        self.log("1. Log in to Django Admin: /admin/", self.style.WARNING)
        self.log("2. View designs at: /admin/core/design/", self.style.WARNING)
        self.log("3. View orders at: /ops/inventory/orders/", self.style.WARNING)
        self.log("4. Configure Shopify webhooks to send to: /webhooks/shopify/", self.style.WARNING)
        self.stdout.write("")
