"""Domain models for BoldERP, aligned to docs/REQUIREMENTS.md."""

from __future__ import annotations

import uuid

from auditlog.registry import auditlog
from django.conf import settings
from django.db import models
from django.db.models import F, Q, Value
from django.db.models.functions import Coalesce


class UUIDTimestampedModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Vendor(UUIDTimestampedModel):
    name = models.CharField(max_length=160, unique=True)
    contact = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Design(UUIDTimestampedModel):
    class ProductType(models.TextChoices):
        TSHIRT = "Tshirt", "Tshirt"

    class SubCategory(models.TextChoices):
        REGULAR = "Regular", "Regular"

    class Fit(models.TextChoices):
        REGULAR = "Regular", "Regular"
        OVERSIZED = "Oversized", "Oversized"

    name = models.CharField(max_length=180, unique=True)
    product_type = models.CharField(
        max_length=60,
        choices=ProductType.choices,
        default=ProductType.TSHIRT,
    )
    sub_category = models.CharField(
        max_length=60,
        choices=SubCategory.choices,
        default=SubCategory.REGULAR,
    )
    material = models.CharField(max_length=60, default="Cotton")
    fit = models.CharField(
        max_length=30,
        choices=Fit.choices,
        default=Fit.REGULAR,
    )
    has_variants = models.BooleanField(default=False)
    variants = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class DesignAsset(UUIDTimestampedModel):
    design = models.ForeignKey(Design, on_delete=models.CASCADE, related_name="assets")
    colour = models.CharField(max_length=60)
    colour_hex = models.CharField(
        max_length=7,
        blank=True,
        help_text="Hex colour for the swatch on the print pack, e.g. #1b1b1b.",
    )
    artwork_url = models.URLField(max_length=600)
    mockup_url = models.URLField(max_length=600)
    blank_fabric = models.CharField(max_length=120)
    print_areas = models.CharField(
        max_length=120,
        blank=True,
        help_text="Print location shown on the pack, e.g. 'Front' or 'Front (Chest)'.",
    )
    placement_note = models.TextField(
        blank=True,
        help_text="Placement instructions for the printer, e.g. 'Artwork must be placed at the chest'.",
    )
    blank_sku = models.ForeignKey(
        "BlankSKU",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="design_assets",
        help_text="Linked plain blank SKU for this design+colour. All sizes of this design will use this blank SKU.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["design", "colour"], name="uniq_designasset_design_colour"),
        ]
        ordering = ["design__name", "colour"]

    def __str__(self) -> str:
        return f"{self.design.name} / {self.colour}"


class DesignAssetFile(UUIDTimestampedModel):
    """Tracks mockup and print files for a design+colour combination."""

    class FileType(models.TextChoices):
        MOCKUP = "mockup", "Mockup Image (Preview)"
        PRINT_FILE = "print_file", "Print File (Production)"
        ARTWORK = "artwork", "Artwork Source"

    class Placement(models.TextChoices):
        FRONT = "front", "Front"
        BACK = "back", "Back"
        SLEEVE = "sleeve", "Sleeve"
        FULL = "full", "Full Print"

    design_asset = models.ForeignKey(
        DesignAsset,
        on_delete=models.CASCADE,
        related_name="files",
    )
    file_type = models.CharField(
        max_length=30,
        choices=FileType.choices,
        help_text="Type of file: mockup for preview, print_file for actual printing",
    )
    placement = models.CharField(
        max_length=30,
        choices=Placement.choices,
        blank=True,
        help_text="Where this file applies (front, back, sleeve, etc.)",
    )
    file_url = models.URLField(
        max_length=600,
        help_text="URL or path to the file",
    )

    class Meta:
        ordering = ["design_asset__design__name", "design_asset__colour", "file_type", "placement"]

    def __str__(self) -> str:
        placement_label = f" ({self.placement})" if self.placement else ""
        return f"{self.design_asset.design.name} / {self.design_asset.colour} - {self.get_file_type_display()}{placement_label}"


class BlankSKU(UUIDTimestampedModel):
    fabric = models.CharField(max_length=120)
    colour = models.CharField(max_length=60)
    size = models.CharField(max_length=30)
    on_hand = models.IntegerField(default=0)
    reserved = models.IntegerField(default=0)
    reorder_min = models.IntegerField(default=0)
    reorder_target = models.IntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["fabric", "colour", "size"], name="uniq_blanksku_fabric_colour_size"),
        ]
        ordering = ["fabric", "colour", "size"]

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved

    @property
    def fabric_gsm(self) -> str:
        return self.fabric

    @property
    def on_hand_qty(self) -> int:
        return self.on_hand

    @property
    def reserved_qty(self) -> int:
        return self.reserved

    def __str__(self) -> str:
        return f"{self.fabric} / {self.colour} / {self.size}"


class PrintedSKU(UUIDTimestampedModel):
    design = models.ForeignKey(Design, on_delete=models.PROTECT, related_name="printed_skus")
    design_asset = models.ForeignKey(
        DesignAsset,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="printed_skus",
        help_text="Reference to the design+colour asset. Preferred over design+colour fields.",
    )
    variant = models.CharField(max_length=120, null=True, blank=True)
    colour = models.CharField(max_length=60)
    size = models.CharField(max_length=30, null=True, blank=True)
    blank_sku = models.ForeignKey(
        "BlankSKU",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="printed_skus",
        help_text="Explicitly linked plain blank SKU. When design_asset is set, blank_sku is auto-populated from design_asset.",
    )
    on_hand = models.IntegerField(default=0)
    reserved = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    buffer_min = models.IntegerField(default=0)
    buffer_target = models.IntegerField(default=0)
    buffer_max = models.IntegerField(default=0)
    is_test_data = models.BooleanField(
        default=False,
        help_text="Mark as test data to enable cleanup/filtering of test orders and inventory",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                F("design"),
                Coalesce("variant", Value("")),
                F("colour"),
                Coalesce("size", Value("")),
                name="uniq_printedsku_design_variant_colour_size",
            ),
        ]
        ordering = ["design__name", "variant", "colour", "size"]

    @property
    def available(self) -> int:
        return self.on_hand - self.reserved

    @property
    def on_hand_qty(self) -> int:
        return self.on_hand

    @property
    def reserved_qty(self) -> int:
        return self.reserved

    @property
    def min_buffer_qty(self) -> int:
        return self.buffer_min

    @property
    def target_buffer_qty(self) -> int:
        return self.buffer_target

    @property
    def max_buffer_qty(self) -> int:
        return self.buffer_max

    def save(self, *args: any, **kwargs: any) -> None:
        """Auto-populate blank_sku from design_asset if not explicitly set."""
        if self.design_asset and not self.blank_sku:
            self.blank_sku = self.design_asset.blank_sku
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        variant_label = self.variant or "BASE"
        size_label = self.size or "NA"
        return f"{self.design.name} / {variant_label} / {self.colour} / {size_label}"


class DeletedInventoryItem(UUIDTimestampedModel):
    class RecordType(models.TextChoices):
        BLANK_SKU = "blank_sku", "Plain SKU"
        PRINTED_SKU = "printed_sku", "Printed SKU"

    record_type = models.CharField(max_length=30, choices=RecordType.choices)
    source_model_id = models.CharField(max_length=64)
    label = models.CharField(max_length=255)
    payload = models.JSONField(default=dict)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="deleted_inventory_items",
    )
    restored_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.get_record_type_display()} / {self.label}"


class Order(UUIDTimestampedModel):
    class Status(models.TextChoices):
        NEW = "new", "New"
        NEEDS_PRINTING = "needs_printing", "Needs Printing"
        IN_PRINTING = "in_printing", "In Printing"
        READY_TO_SHIP = "ready_to_ship", "Ready To Ship"
        SHIPPED = "shipped", "Shipped"
        CANCELLED = "cancelled", "Cancelled"
        ISSUE = "issue", "Issue"

    STATUS_NEW = Status.NEW
    STATUS_NEEDS_PRINTING = Status.NEEDS_PRINTING
    STATUS_IN_PRINTING = Status.IN_PRINTING
    STATUS_READY_TO_SHIP = Status.READY_TO_SHIP
    STATUS_SHIPPED = Status.SHIPPED
    STATUS_CANCELLED = Status.CANCELLED
    STATUS_ISSUE = Status.ISSUE

    shopify_order_id = models.CharField(max_length=80, unique=True)
    order_no = models.CharField(max_length=80, blank=True)
    customer_name = models.CharField(max_length=180, blank=True)
    email = models.EmailField(blank=True)
    tags = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.NEW)
    shopify_fulfillment_status = models.CharField(max_length=80, blank=True)
    shopify_delivery_status = models.CharField(max_length=80, blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    is_test_data = models.BooleanField(
        default=False,
        help_text="Mark as test data to enable cleanup/filtering of test orders",
    )

    class Meta:
        indexes = [
            models.Index(fields=["status"], name="order_status_idx"),
            models.Index(fields=["created_at"], name="order_created_idx"),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        display_order_no = self.order_no or self.shopify_order_id
        return f"Order {display_order_no} ({self.status})"


class OrderLine(UUIDTimestampedModel):
    class Status(models.TextChoices):
        NEW = "new", "New"
        TO_BE_PRINTED = "to_be_printed", "To Be Printed"
        IN_PRINTING = "in_printing", "In Printing"
        READY_SHIP = "ready_ship", "Ready to Ship"
        SHIPPED = "shipped", "Shipped"
        CANCELLED = "cancelled", "Cancelled"

    STATUS_NEW = Status.NEW
    STATUS_TO_BE_PRINTED = Status.TO_BE_PRINTED
    STATUS_IN_PRINTING = Status.IN_PRINTING
    STATUS_READY_SHIP = Status.READY_SHIP
    STATUS_READY_TO_SHIP = Status.READY_SHIP
    STATUS_SHIPPED = Status.SHIPPED
    STATUS_CANCELLED = Status.CANCELLED

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    shopify_line_id = models.CharField(max_length=80, unique=True)
    product_name = models.CharField(max_length=220)
    variant = models.CharField(max_length=120, blank=True)
    size = models.CharField(max_length=30, blank=True)
    quantity = models.IntegerField(default=0)
    printed_sku = models.ForeignKey(
        PrintedSKU,
        on_delete=models.PROTECT,
        related_name="order_lines",
        null=True,
        blank=True,
    )
    is_bundle = models.BooleanField(default=False)
    bundle_components = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.NEW)

    class Meta:
        indexes = [models.Index(fields=["status"], name="orderline_status_idx")]
        ordering = ["created_at", "product_name"]

    @property
    def title(self) -> str:
        return self.product_name

    @property
    def reserved_qty(self) -> int:
        return 0

    def __str__(self) -> str:
        return f"{self.order.shopify_order_id} / {self.product_name} x {self.quantity}"


class OrderLineComponent(UUIDTimestampedModel):
    order_line = models.ForeignKey(OrderLine, on_delete=models.CASCADE, related_name="components")
    printed_sku = models.ForeignKey(PrintedSKU, on_delete=models.PROTECT, related_name="bundle_components")
    quantity_each = models.IntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["order_line", "printed_sku"], name="uniq_orderlinecomponent_line_sku"),
        ]

    def __str__(self) -> str:
        return f"{self.order_line_id} / {self.printed_sku_id} x {self.quantity_each}"


class PrintBatch(UUIDTimestampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        CONFIRMED = "confirmed", "Confirmed"
        RECEIVED = "received", "Received"

    STATUS_DRAFT = Status.DRAFT
    STATUS_CONFIRMED = Status.CONFIRMED
    STATUS_RECEIVED = Status.RECEIVED

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    print_pack_path = models.CharField(max_length=300, blank=True)
    notes = models.TextField(blank=True)

    def __str__(self) -> str:
        return f"Batch {self.id} ({self.status})"


class PrintJob(UUIDTimestampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SENT = "sent", "Sent"
        PARTIALLY_RECEIVED = "partially_received", "Partially Received"
        RECEIVED = "received", "Received"
        CLOSED = "closed", "Closed"

    STATUS_DRAFT = Status.DRAFT
    STATUS_SENT = Status.SENT
    STATUS_PARTIALLY_RECEIVED = Status.PARTIALLY_RECEIVED
    STATUS_RECEIVED = Status.RECEIVED
    STATUS_CLOSED = Status.CLOSED

    batch = models.OneToOneField(
        PrintBatch,
        on_delete=models.CASCADE,
        related_name="job",
        null=True,
        blank=True,
    )
    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="print_jobs")
    status = models.CharField(max_length=30, choices=Status.choices, default=Status.DRAFT)
    sent_at = models.DateTimeField(null=True, blank=True)
    expected_at = models.DateTimeField(null=True, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    pdf_url = models.URLField(max_length=600, blank=True)

    @property
    def vendor_name(self) -> str:
        return self.vendor.name

    def __str__(self) -> str:
        return f"Print Job {self.id} / {self.vendor.name}"


class PrintJobLine(UUIDTimestampedModel):
    print_job = models.ForeignKey(PrintJob, on_delete=models.CASCADE, related_name="lines")
    printed_sku = models.ForeignKey(PrintedSKU, on_delete=models.PROTECT, related_name="print_job_lines")
    blank_sku = models.ForeignKey(
        BlankSKU,
        on_delete=models.PROTECT,
        related_name="print_job_lines",
        null=True,
        blank=True,
    )
    qty_sent = models.IntegerField(default=0)
    qty_received_good = models.IntegerField(default=0)
    qty_received_defective = models.IntegerField(default=0)
    shortfall_flagged = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["print_job", "printed_sku"], name="uniq_printjobline_job_sku"),
        ]

    @property
    def job(self) -> PrintJob:
        return self.print_job

    @property
    def qty_good_received(self) -> int:
        return self.qty_received_good

    @property
    def qty_defective_received(self) -> int:
        return self.qty_received_defective

    def __str__(self) -> str:
        return f"{self.print_job_id} / {self.printed_sku} / sent {self.qty_sent}"


class StockMovement(UUIDTimestampedModel):
    class Pool(models.TextChoices):
        PLAIN = "plain", "Plain"
        PRINTED = "printed", "Printed"

    class Reason(models.TextChoices):
        ADJUSTMENT = "adjustment", "Adjustment"
        SOFT_RESERVE = "soft_reserve", "Soft Reserve"
        RELEASE_RESERVATION = "release_reservation", "Release Reservation"
        SHIP = "ship", "Ship"
        PRINT_BATCH_CONFIRM = "print_batch_confirm", "Print Batch Confirm"
        PRINT_RECEIVE = "print_receive", "Print Receive"
        CANCEL = "cancel", "Cancel"
        REPRINT = "reprint", "Reprint"
        IMPORT = "import", "Import"

    TYPE_PLAIN = Pool.PLAIN
    TYPE_PRINTED = Pool.PRINTED

    pool = models.CharField(max_length=20, choices=Pool.choices)
    blank_sku = models.ForeignKey(BlankSKU, on_delete=models.PROTECT, null=True, blank=True, related_name="movements")
    printed_sku = models.ForeignKey(
        PrintedSKU,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="movements",
    )
    delta_on_hand = models.IntegerField(default=0)
    delta_reserved = models.IntegerField(default=0)
    reason = models.CharField(max_length=40, choices=Reason.choices)
    ref_table = models.CharField(max_length=80, blank=True)
    ref_id = models.UUIDField(null=True, blank=True)
    note = models.TextField(blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements",
    )

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(Q(blank_sku__isnull=False) | Q(printed_sku__isnull=False)),
                name="stockmovement_has_target_sku",
            ),
        ]
        ordering = ["-created_at"]

    @property
    def movement_type(self) -> str:
        return self.pool

    @property
    def quantity_delta(self) -> int:
        return self.delta_on_hand

    @property
    def reference(self) -> str:
        if self.ref_table and self.ref_id:
            return f"{self.ref_table}:{self.ref_id}"
        return self.ref_table

    def __str__(self) -> str:
        target = self.blank_sku or self.printed_sku
        return f"{self.pool} / {self.reason} / {target}"


class ReprintTask(UUIDTimestampedModel):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        CLOSED = "closed", "Closed"

    STATUS_OPEN = Status.OPEN
    STATUS_CLOSED = Status.CLOSED

    printed_sku = models.ForeignKey(PrintedSKU, on_delete=models.PROTECT, related_name="reprint_tasks")
    qty = models.IntegerField(default=0)
    source = models.ForeignKey(PrintJobLine, on_delete=models.CASCADE, related_name="reprint_tasks")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.OPEN)

    @property
    def print_job_line(self) -> PrintJobLine:
        return self.source

    @property
    def qty_needed(self) -> int:
        return self.qty

    def __str__(self) -> str:
        return f"Reprint {self.printed_sku} x {self.qty} ({self.status})"


class WebhookEvent(UUIDTimestampedModel):
    source = models.CharField(max_length=40, default="shopify")
    topic = models.CharField(max_length=120)
    idempotency_key = models.CharField(max_length=255, unique=True)
    payload = models.JSONField(default=dict)
    processed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self) -> str:
        return f"{self.topic} / {self.idempotency_key}"


def _register_with_auditlog(model_class: type[models.Model]) -> None:
    try:
        auditlog.register(model_class)
    except Exception:
        return


# ══════════════════════════════════════════════════════════════════════════════
# FINANCIAL MANAGEMENT MODELS (adapted from bold-finance Streamlit app)
# ══════════════════════════════════════════════════════════════════════════════


class Expense(UUIDTimestampedModel):
    """Employee expense reimbursement tracker."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SETTLED = "settled", "Settled"
        REJECTED = "rejected", "Rejected"

    expense_date = models.DateField()
    paid_by = models.CharField(max_length=120)
    entity = models.CharField(max_length=120)
    person = models.CharField(max_length=120, blank=True)
    amount = models.IntegerField()
    description = models.TextField(blank=True)
    remarks = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    bank_reference = models.CharField(max_length=255, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status"], name="expense_status_idx"),
            models.Index(fields=["expense_date"], name="expense_date_idx"),
        ]
        ordering = ["-expense_date"]

    def __str__(self) -> str:
        return f"Expense {str(self.id)[:8]} / {self.paid_by} / ₹{self.amount/100:.2f}"


class BankTransaction(UUIDTimestampedModel):
    """Bank statement transaction record."""

    transaction_date = models.DateField()
    description = models.TextField()
    withdrawals = models.IntegerField(default=0)
    deposits = models.IntegerField(default=0)
    cheque_no = models.CharField(max_length=20, blank=True)
    reference_no = models.CharField(max_length=255, blank=True)
    entity = models.CharField(max_length=120, blank=True)
    person = models.CharField(max_length=120, blank=True)
    remarks = models.TextField(blank=True)
    match_confidence = models.CharField(
        max_length=50,
        default="needs_review",
        choices=[
            ("auto_reconciled", "Auto-Reconciled"),
            ("needs_review", "Needs Review"),
            ("manual_matched", "Manual Match"),
        ],
    )
    running_balance = models.IntegerField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["transaction_date"], name="txn_date_idx"),
            models.Index(fields=["reference_no"], name="txn_reference_idx"),
        ]
        ordering = ["-transaction_date"]

    def __str__(self) -> str:
        amount = self.withdrawals or self.deposits
        return f"{self.transaction_date} / ₹{amount/100:.2f} / {self.description[:40]}"


class Reconciliation(UUIDTimestampedModel):
    """Links an Expense to a BankTransaction."""

    expense = models.OneToOneField(
        Expense, on_delete=models.CASCADE, related_name="reconciliation"
    )
    bank_transaction = models.OneToOneField(
        BankTransaction, on_delete=models.CASCADE, related_name="reconciliation"
    )
    matched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Recon {str(self.id)[:8]}"


class Invoice(UUIDTimestampedModel):
    """Invoice/Proforma Invoice generation record."""

    class InvoiceType(models.TextChoices):
        TAX_INVOICE = "tax_invoice", "Tax Invoice"
        PROFORMA = "proforma", "Proforma Invoice"

    class PlaceOfSupply(models.TextChoices):
        TELANGANA = "telangana", "Telangana"
        MAHARASHTRA = "maharashtra", "Maharashtra"
        KARNATAKA = "karnataka", "Karnataka"
        DELHI = "delhi", "Delhi"
        OTHERS = "others", "Others (IGST)"

    invoice_type = models.CharField(max_length=20, choices=InvoiceType.choices, default=InvoiceType.TAX_INVOICE)
    invoice_number = models.CharField(max_length=50, unique=True)
    invoice_date = models.DateField()
    order_date = models.DateField()
    client_name = models.CharField(max_length=200)
    client_address = models.TextField()
    client_gstin = models.CharField(max_length=20, blank=True)
    place_of_supply = models.CharField(max_length=30, choices=PlaceOfSupply.choices, default=PlaceOfSupply.TELANGANA)
    discount_amount = models.IntegerField(default=0)
    deductions_amount = models.IntegerField(default=0)
    subtotal_amount = models.IntegerField(default=0)
    net_taxable_amount = models.IntegerField(default=0)
    tax_amount = models.IntegerField(default=0)
    grand_total_amount = models.IntegerField(default=0)
    pdf_path = models.CharField(max_length=500, blank=True)
    pdf_generated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["invoice_number"], name="inv_number_idx")]
        ordering = ["-invoice_date"]

    def __str__(self) -> str:
        return f"{self.invoice_number} / {self.client_name}"


class InvoiceLineItem(UUIDTimestampedModel):
    """Line items in an Invoice."""

    invoice = models.ForeignKey(Invoice, on_delete=models.CASCADE, related_name="line_items")
    sequence = models.IntegerField(default=0)
    description = models.CharField(max_length=500)
    hsn_sac = models.CharField(max_length=20, blank=True)
    quantity = models.IntegerField(default=1)
    rate = models.IntegerField()
    amount = models.IntegerField()

    class Meta:
        ordering = ["invoice", "sequence"]

    def __str__(self) -> str:
        return f"{self.invoice.invoice_number} / {self.description}"


for model in (
    Vendor,
    Design,
    DesignAsset,
    BlankSKU,
    PrintedSKU,
    Order,
    OrderLine,
    OrderLineComponent,
    PrintBatch,
    PrintJob,
    PrintJobLine,
    StockMovement,
    ReprintTask,
    WebhookEvent,
    DeletedInventoryItem,
    Expense,
    BankTransaction,
    Reconciliation,
    Invoice,
    InvoiceLineItem,
):
    _register_with_auditlog(model)
