from __future__ import annotations

from dataclasses import dataclass

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db import transaction
from django.utils import timezone

from core.models import (
    BankTransaction,
    BlankSKU,
    DeletedInventoryItem,
    Design,
    DesignAsset,
    DesignAssetFile,
    Expense,
    Invoice,
    InvoiceLineItem,
    Order,
    OrderLine,
    OrderLineComponent,
    PrintBatch,
    PrintJob,
    PrintJobLine,
    PrintedSKU,
    Reconciliation,
    ReprintTask,
    StockMovement,
    Vendor,
    WebhookEvent,
)
from core.services import pdf


@dataclass(frozen=True)
class SeedLine:
    design_name: str
    variant: str | None
    colour: str
    size: str
    quantity: int


class Command(BaseCommand):
    help = "Delete all core operational data and seed a consistent sample baseline."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Required safety flag. Confirms full data reset.",
        )
        parser.add_argument(
            "--build-print-pack",
            action="store_true",
            help="Generate sample print pack at the end (slower due remote image fetch).",
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        if not options["yes"]:
            raise CommandError("Refusing to run without --yes. This command deletes existing data.")

        self.stdout.write(self.style.WARNING("Starting full data reset..."))
        self._reset_all_data()
        self.stdout.write(self.style.SUCCESS("All existing core data deleted."))

        self.stdout.write(self.style.WARNING("Seeding consistent sample dataset..."))
        print_job = self._seed_sample_data()
        self.stdout.write(self.style.SUCCESS("Sample dataset created."))

        if options["build_print_pack"]:
            try:
                pdf_url = pdf.build_print_pack_pdf(str(print_job.id))
                self.stdout.write(self.style.SUCCESS(f"Print pack generated: {pdf_url}"))
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f"Print pack generation skipped due to error: {exc}"))

        self.stdout.write(self.style.SUCCESS("Reset + seed complete."))

    def _reset_all_data(self) -> None:
        """Delete all mutable domain rows in dependency-safe order."""
        if connection.vendor == "postgresql":
            self._truncate_postgres_tables()
            return

        Reconciliation.objects.all().delete()
        InvoiceLineItem.objects.all().delete()
        Invoice.objects.all().delete()
        BankTransaction.objects.all().delete()
        Expense.objects.all().delete()

        ReprintTask.objects.all().delete()
        StockMovement.objects.all().delete()
        WebhookEvent.objects.all().delete()
        DeletedInventoryItem.objects.all().delete()

        PrintJobLine.objects.all().delete()
        PrintJob.objects.all().delete()
        PrintBatch.objects.all().delete()

        OrderLineComponent.objects.all().delete()
        OrderLine.objects.all().delete()
        Order.objects.all().delete()

        PrintedSKU.objects.all().delete()
        DesignAssetFile.objects.all().delete()
        DesignAsset.objects.all().delete()
        Design.objects.all().delete()

        BlankSKU.objects.all().delete()
        Vendor.objects.all().delete()

    def _truncate_postgres_tables(self) -> None:
        """Fast reset for PostgreSQL databases using TRUNCATE CASCADE."""
        table_names = [
            Reconciliation._meta.db_table,
            InvoiceLineItem._meta.db_table,
            Invoice._meta.db_table,
            BankTransaction._meta.db_table,
            Expense._meta.db_table,
            ReprintTask._meta.db_table,
            StockMovement._meta.db_table,
            WebhookEvent._meta.db_table,
            DeletedInventoryItem._meta.db_table,
            PrintJobLine._meta.db_table,
            PrintJob._meta.db_table,
            PrintBatch._meta.db_table,
            OrderLineComponent._meta.db_table,
            OrderLine._meta.db_table,
            Order._meta.db_table,
            PrintedSKU._meta.db_table,
            DesignAssetFile._meta.db_table,
            DesignAsset._meta.db_table,
            Design._meta.db_table,
            BlankSKU._meta.db_table,
            Vendor._meta.db_table,
        ]
        quoted = ", ".join(connection.ops.quote_name(name) for name in table_names)
        with connection.cursor() as cursor:
            cursor.execute(f"TRUNCATE TABLE {quoted} RESTART IDENTITY CASCADE")

    def _seed_sample_data(self) -> PrintJob:
        """Seed a consistent sample dataset reflecting current operational workflow."""
        vendor = Vendor.objects.create(name="Knitwear", contact="ops@knitwear.example", is_active=True)

        sizes = ["S", "M", "L", "XL", "XXL", "XXXL"]
        fabrics = [
            ("180 GSM", "Black", 240),
            ("180 GSM", "White", 140),
        ]
        blank_lookup: dict[tuple[str, str, str], BlankSKU] = {}
        for fabric, colour, qty in fabrics:
            for size in sizes:
                blank = BlankSKU.objects.create(
                    fabric=fabric,
                    colour=colour,
                    size=size,
                    on_hand=qty,
                    reserved=0,
                    reorder_min=30,
                    reorder_target=120,
                )
                blank_lookup[(fabric, colour, size)] = blank

        designs = [
            "Amrutham & Chill",
            "Brathukantha AI-omayam",
            "Current Rent etc",
            "Dulandhar - Konchem Dhula Ekkuva",
            "From 90s to 90ML",
            "Oka Chemchadu Bhava Saagaraalu",
            "Penguin Rahadhaari",
            "Ugadi Telugu Raasi Phalalu",
        ]

        variants_by_design: dict[str, list[str | None]] = {
            "Ugadi Telugu Raasi Phalalu": ["Karkataka", "Vruschika", "Thula"],
        }

        printed_lookup: dict[tuple[str, str | None, str, str], PrintedSKU] = {}
        mockup_url = "https://picsum.photos/seed/bolderp-mockup/1200/1200"
        artwork_url = "https://picsum.photos/seed/bolderp-art/1600/1600"

        for design_name in designs:
            design = Design.objects.create(
                name=design_name,
                product_type=Design.ProductType.TSHIRT,
                sub_category=Design.SubCategory.REGULAR,
                material="Cotton",
                fit=Design.Fit.REGULAR,
                has_variants=design_name in variants_by_design,
                variants=[v for v in variants_by_design.get(design_name, []) if v],
                notes="Sample seeded design",
            )

            for colour, colour_hex in [("Black", "#1b1b1b"), ("White", "#ffffff")]:
                asset = DesignAsset.objects.create(
                    design=design,
                    colour=colour,
                    colour_hex=colour_hex,
                    artwork_url=artwork_url,
                    mockup_url=mockup_url,
                    blank_fabric="180 GSM",
                    print_areas="Front",
                    placement_note="Center chest print",
                    blank_sku=blank_lookup[("180 GSM", colour, "M")],
                )
                DesignAssetFile.objects.create(
                    design_asset=asset,
                    file_type=DesignAssetFile.FileType.MOCKUP,
                    placement=DesignAssetFile.Placement.FRONT,
                    file_url=mockup_url,
                )

                variants = variants_by_design.get(design_name, [None])
                for variant in variants:
                    for size in sizes:
                        sku = PrintedSKU.objects.create(
                            design=design,
                            design_asset=asset,
                            variant=variant,
                            colour=colour,
                            size=size,
                            blank_sku=blank_lookup[("180 GSM", colour, size)],
                            on_hand=0,
                            reserved=0,
                            is_active=True,
                            buffer_min=3,
                            buffer_target=12,
                            buffer_max=30,
                            is_test_data=True,
                        )
                        printed_lookup[(design_name, variant, colour, size)] = sku

        seed_lines = [
            SeedLine("Amrutham & Chill", None, "Black", "M", 2),
            SeedLine("Brathukantha AI-omayam", None, "Black", "L", 1),
            SeedLine("Current Rent etc", None, "White", "XL", 1),
            SeedLine("Dulandhar - Konchem Dhula Ekkuva", None, "Black", "S", 2),
            SeedLine("From 90s to 90ML", None, "White", "M", 1),
            SeedLine("Oka Chemchadu Bhava Saagaraalu", None, "Black", "XXL", 1),
            SeedLine("Penguin Rahadhaari", None, "Black", "L", 1),
            SeedLine("Ugadi Telugu Raasi Phalalu", "Karkataka", "White", "M", 1),
            SeedLine("Ugadi Telugu Raasi Phalalu", "Vruschika", "White", "L", 1),
            SeedLine("Ugadi Telugu Raasi Phalalu", "Thula", "White", "XL", 1),
        ]

        order = Order.objects.create(
            shopify_order_id=f"sample-reset-{int(timezone.now().timestamp())}",
            order_no="#SAMPLE-0001",
            customer_name="Sample Customer",
            email="sample.customer@example.com",
            tags=["sample", "consistent"],
            status=Order.STATUS_NEEDS_PRINTING,
            shopify_fulfillment_status="unfulfilled",
            shopify_delivery_status="pending",
            raw_payload={"source": "reset_and_seed_domain_data"},
            is_test_data=True,
        )

        for index, line in enumerate(seed_lines, start=1):
            sku = printed_lookup[(line.design_name, line.variant, line.colour, line.size)]
            OrderLine.objects.create(
                order=order,
                shopify_line_id=f"sample-reset-line-{index}",
                product_name=line.design_name,
                variant=line.variant or "",
                size=line.size,
                quantity=line.quantity,
                printed_sku=sku,
                is_bundle=False,
                bundle_components=[],
                status=OrderLine.STATUS_TO_BE_PRINTED,
            )

        batch = PrintBatch.objects.create(status=PrintBatch.STATUS_CONFIRMED, notes="Sample seeded batch")
        job = PrintJob.objects.create(
            batch=batch,
            vendor=vendor,
            status=PrintJob.STATUS_SENT,
            sent_at=timezone.now(),
            notes="Sample seeded print job",
            pdf_url="",
        )

        for line in seed_lines:
            sku = printed_lookup[(line.design_name, line.variant, line.colour, line.size)]
            PrintJobLine.objects.create(
                print_job=job,
                printed_sku=sku,
                blank_sku=blank_lookup[("180 GSM", line.colour, line.size)],
                qty_sent=line.quantity,
                qty_received_good=0,
                qty_received_defective=0,
                shortfall_flagged=False,
            )

        return job
