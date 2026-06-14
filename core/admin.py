from django.contrib import admin
from django.contrib import messages
from django.utils import timezone
import re

from .models import (
    BlankSKU,
    Design,
    DesignAsset,
    DesignAssetFile,
    Order,
    OrderLine,
    OrderLineComponent,
    PrintBatch,
    PrintJob,
    PrintJobLine,
    PrintedSKU,
    ReprintTask,
    StockMovement,
    Vendor,
    WebhookEvent,
    Expense,
    BankTransaction,
    DeletedInventoryItem,
    Reconciliation,
    Invoice,
    InvoiceLineItem,
)


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ("name", "contact", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "contact")
    list_editable = ("is_active",)


@admin.register(BlankSKU)
class BlankSKUAdmin(admin.ModelAdmin):
    list_display = ("fabric", "colour", "size", "on_hand", "reserved", "available")
    search_fields = ("fabric", "colour", "size")


class DesignAssetFileInline(admin.TabularInline):
    model = DesignAssetFile
    extra = 1
    fields = (
        "file_type",
        "placement",
        "file_url",
        "created_at",
    )
    readonly_fields = ("created_at",)


class DesignAssetInline(admin.TabularInline):
    model = DesignAsset
    extra = 0
    fields = (
        "colour",
        "colour_hex",
        "artwork_url",
        "mockup_url",
        "blank_sku",
        "blank_fabric",
        "print_areas",
        "placement_note",
    )
    autocomplete_fields = ["blank_sku"]


@admin.register(Design)
class DesignAdmin(admin.ModelAdmin):
    list_display = ("name", "product_type", "sub_category", "fit", "material", "has_variants")
    list_filter = ("fit", "product_type", "sub_category")
    search_fields = ("name",)
    inlines = [DesignAssetInline]


@admin.register(DesignAsset)
class DesignAssetAdmin(admin.ModelAdmin):
    list_display = ("design", "colour", "blank_sku", "created_at")
    list_filter = ("design", "colour")
    search_fields = ("design__name", "colour")
    autocomplete_fields = ["blank_sku"]
    inlines = [DesignAssetFileInline]


@admin.register(DesignAssetFile)
class DesignAssetFileAdmin(admin.ModelAdmin):
    list_display = ("design_asset", "file_type", "placement", "created_at")
    list_filter = ("file_type", "placement")
    search_fields = ("design_asset__design__name", "design_asset__colour")


@admin.register(PrintedSKU)
class PrintedSKUAdmin(admin.ModelAdmin):
    list_display = ("design", "variant", "size", "colour", "blank_sku", "on_hand", "reserved", "available", "is_test_data")
    list_filter = ("colour", "design", "is_active", "is_test_data")
    search_fields = ("design__name", "variant", "size", "colour")
    autocomplete_fields = ["blank_sku", "design_asset"]
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        ("Core", {
            "fields": ("design", "design_asset", "variant", "colour", "size"),
        }),
        ("Linking", {
            "fields": ("blank_sku",),
            "description": "Set blank_sku at design_asset level for all sizes of this colour",
        }),
        ("Inventory", {
            "fields": ("on_hand", "reserved", "buffer_min", "buffer_target", "buffer_max"),
        }),
        ("Status", {
            "fields": ("is_active", "is_test_data", "created_at", "updated_at"),
        }),
    )
    actions = ["backfill_size_from_variant"]

    @admin.action(description="Backfill missing size from variant suffix")
    def backfill_size_from_variant(self, request, queryset):
        size_pattern = re.compile(r"^(?P<variant>.*?)\s*/\s*(?P<size>XS|S|M|L|XL|XXL|XXXL|2XL|3XL|4XL)$", re.IGNORECASE)
        updated = 0
        skipped = 0
        conflicts = 0

        for sku in queryset.select_related("design"):
            if (sku.size or "").strip():
                skipped += 1
                continue

            variant_value = (sku.variant or "").strip()
            match = size_pattern.match(variant_value)
            if not match:
                skipped += 1
                continue

            derived_variant = (match.group("variant") or "").strip() or None
            derived_size = (match.group("size") or "").strip().upper()
            if derived_size == "2XL":
                derived_size = "XXL"
            if derived_size == "3XL":
                derived_size = "XXXL"

            conflict = (
                PrintedSKU.objects.filter(
                    design=sku.design,
                    variant=derived_variant,
                    colour=sku.colour,
                    size=derived_size,
                )
                .exclude(id=sku.id)
                .exists()
            )
            if conflict:
                conflicts += 1
                continue

            sku.variant = derived_variant
            sku.size = derived_size
            sku.save(update_fields=["variant", "size", "updated_at"])
            updated += 1

        if updated:
            self.message_user(request, f"Updated {updated} PrintedSKU row(s).", level=messages.SUCCESS)
        if skipped:
            self.message_user(request, f"Skipped {skipped} row(s) with no parsable variant suffix.", level=messages.WARNING)
        if conflicts:
            self.message_user(request, f"Skipped {conflicts} row(s) due to uniqueness conflicts.", level=messages.ERROR)


class OrderLineComponentInline(admin.TabularInline):
    model = OrderLineComponent
    extra = 0


class OrderLineInline(admin.TabularInline):
    model = OrderLine
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("shopify_order_id", "status", "is_test_data", "created_at")
    list_filter = ("status", "is_test_data")
    search_fields = ("shopify_order_id",)
    inlines = [OrderLineInline]


@admin.register(OrderLine)
class OrderLineAdmin(admin.ModelAdmin):
    list_display = ("order", "product_name", "quantity", "is_bundle", "status")
    list_filter = ("status",)
    inlines = [OrderLineComponentInline]


class PrintJobLineInline(admin.TabularInline):
    model = PrintJobLine
    extra = 0


@admin.register(PrintBatch)
class PrintBatchAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "created_at")
    list_filter = ("status",)


@admin.register(PrintJob)
class PrintJobAdmin(admin.ModelAdmin):
    list_display = ("vendor", "status", "sent_at", "expected_at", "received_at")
    inlines = [PrintJobLineInline]


@admin.register(ReprintTask)
class ReprintTaskAdmin(admin.ModelAdmin):
    list_display = ("source", "printed_sku", "qty", "status")
    list_filter = ("status",)


@admin.register(StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = ("pool", "blank_sku", "printed_sku", "delta_on_hand", "delta_reserved", "reason", "created_at")
    list_filter = ("pool", "reason")


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    list_display = ("source", "topic", "idempotency_key", "processed_at")
    search_fields = ("topic", "idempotency_key")


@admin.register(DeletedInventoryItem)
class DeletedInventoryItemAdmin(admin.ModelAdmin):
    list_display = ("record_type", "label", "deleted_by", "created_at", "restored_at")
    list_filter = ("record_type", "restored_at")
    search_fields = ("label", "source_model_id")
    actions = ["mark_restored"]

    @admin.action(description="Mark selected items as restored")
    def mark_restored(self, request, queryset):
        queryset.filter(restored_at__isnull=True).update(restored_at=timezone.now())


# ------------------------------------------------------------------------------
# FINANCIAL MANAGEMENT ADMIN
# ------------------------------------------------------------------------------


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ("created_at", "expense_date", "paid_by", "entity", "amount", "status")
    list_filter = ("status", "entity", "paid_by")
    search_fields = ("paid_by", "entity", "description")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(BankTransaction)
class BankTransactionAdmin(admin.ModelAdmin):
    list_display = ("transaction_date", "description", "withdrawals", "deposits", "entity", "match_confidence")
    list_filter = ("match_confidence", "entity", "transaction_date")
    search_fields = ("description", "reference_no", "entity")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Reconciliation)
class ReconciliationAdmin(admin.ModelAdmin):
    list_display = ("created_at", "expense", "bank_transaction", "matched_by")
    list_filter = ("created_at", "matched_by")
    search_fields = ("expense__description", "bank_transaction__description")


class InvoiceLineItemInline(admin.TabularInline):
    model = InvoiceLineItem
    extra = 1
    fields = ("sequence", "description", "hsn_sac", "quantity", "rate", "amount")


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ("invoice_number", "invoice_date", "client_name", "invoice_type", "grand_total_amount")
    list_filter = ("invoice_type", "place_of_supply", "invoice_date")
    search_fields = ("invoice_number", "client_name", "client_gstin")
    inlines = [InvoiceLineItemInline]
