from __future__ import annotations

from typing import Any

from django.core.management.base import BaseCommand

from core.models import (
    BlankSKU,
    OrderLine,
    OrderLineComponent,
    PrintedSKU,
    PrintJobLine,
    ReprintTask,
    StockMovement,
)

SIZE_TOKENS = {"XS", "S", "M", "L", "XL", "XXL", "2XL", "3XL", "4XL"}
POLICY_VALUES = {"continue", "deny"}


def _has_refs(sku: PrintedSKU) -> bool:
    return (
        sku.order_lines.exists()
        or sku.bundle_components.exists()
        or sku.print_job_lines.exists()
        or sku.movements.exists()
        or sku.reprint_tasks.exists()
    )


def _merge_into(src: PrintedSKU, target: PrintedSKU, stdout: Any) -> None:
    """Move all references from src to target, then delete src."""
    OrderLine.objects.filter(printed_sku=src).update(printed_sku=target)
    StockMovement.objects.filter(printed_sku=src).update(printed_sku=target)
    ReprintTask.objects.filter(printed_sku=src).update(printed_sku=target)

    for comp in list(OrderLineComponent.objects.filter(printed_sku=src)):
        existing = OrderLineComponent.objects.filter(
            order_line=comp.order_line, printed_sku=target
        ).first()
        if existing:
            existing.quantity_each = int(existing.quantity_each) + int(comp.quantity_each)
            existing.save(update_fields=["quantity_each", "updated_at"])
            comp.delete()
        else:
            comp.printed_sku = target
            comp.save(update_fields=["printed_sku", "updated_at"])

    for pl in list(PrintJobLine.objects.filter(printed_sku=src)):
        existing = PrintJobLine.objects.filter(
            print_job=pl.print_job, printed_sku=target
        ).first()
        if existing:
            existing.qty_sent = int(existing.qty_sent) + int(pl.qty_sent)
            existing.qty_received_good = int(existing.qty_received_good) + int(pl.qty_received_good)
            existing.qty_received_defective = int(existing.qty_received_defective) + int(pl.qty_received_defective)
            existing.shortfall_flagged = bool(existing.shortfall_flagged or pl.shortfall_flagged)
            existing.save(update_fields=["qty_sent", "qty_received_good", "qty_received_defective", "shortfall_flagged", "updated_at"])
            pl.delete()
        else:
            pl.printed_sku = target
            pl.save(update_fields=["printed_sku", "updated_at"])

    target.on_hand = int(target.on_hand) + int(src.on_hand)
    target.reserved = int(target.reserved) + int(src.reserved)
    target.is_active = bool(target.is_active or src.is_active)
    target.save(update_fields=["on_hand", "reserved", "is_active", "updated_at"])
    src.delete()
    stdout.write(f"  Merged {src} → {target}")


class Command(BaseCommand):
    help = (
        "Clean up malformed PrintedSKU rows: remove size tokens from variant field, "
        "fix policy-string colours (continue/deny → Unknown), and remove duplicates."
    )

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be changed without writing to the database.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Run all cleanup phases in sequence."""
        dry_run: bool = options["dry_run"]
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN — no changes will be written."))

        phase1_fixed = phase1_merged = phase1_skipped = 0
        phase2_fixed = phase2_merged = phase2_skipped = 0
        phase3_deleted = 0

        # ── Phase 1: Remove size tokens from variant field ──────────────────
        self.stdout.write("\nPhase 1: Removing size tokens from variant field…")
        bad_variant_qs = list(
            PrintedSKU.objects.filter(variant__isnull=False)
            .select_related("design")
            .order_by("design__name", "variant", "colour")
        )
        for sku in bad_variant_qs:
            raw_variant = (sku.variant or "").strip().upper()
            if raw_variant not in SIZE_TOKENS:
                continue

            # variant field IS a size token – correct size field should be the same
            # or null (from earlier bad rows).
            correct_size = raw_variant
            if raw_variant == "XXL":
                correct_size = "2XL"

            if dry_run:
                self.stdout.write(
                    f"  WOULD fix: {sku.design.name!r} variant={sku.variant!r} size={sku.size!r} colour={sku.colour!r}"
                )
                phase1_fixed += 1
                continue

            # Check if a canonical row (variant=None, correct_size) already exists.
            target = (
                PrintedSKU.objects.filter(
                    design=sku.design,
                    variant__isnull=True,
                    colour=sku.colour,
                    size=correct_size,
                )
                .exclude(id=sku.id)
                .first()
            )
            if target:
                _merge_into(sku, target, self.stdout)
                phase1_merged += 1
            else:
                sku.variant = None
                sku.size = correct_size
                sku.save(update_fields=["variant", "size", "updated_at"])
                phase1_fixed += 1

        # ── Phase 2: Fix policy-string colours (continue / deny → Unknown) ──
        # For each policy-colour row: if an Unknown row exists with same
        # design/variant/size, merge into it; otherwise just update colour.
        self.stdout.write("\nPhase 2: Fixing policy-string colour values…")
        policy_qs = list(
            PrintedSKU.objects.filter(colour__in=list(POLICY_VALUES))
            .select_related("design")
            .order_by("design__name", "size")
        )
        for sku in policy_qs:
            if dry_run:
                self.stdout.write(
                    f"  WOULD fix colour: {sku.design.name!r} colour={sku.colour!r} variant={sku.variant!r} size={sku.size!r}"
                )
                phase2_fixed += 1
                continue

            # Look for a matching Unknown row
            target = (
                PrintedSKU.objects.filter(
                    design=sku.design,
                    variant=sku.variant,
                    colour="Unknown",
                    size=sku.size,
                )
                .exclude(id=sku.id)
                .first()
            )
            if target:
                # Merge into existing Unknown row
                _merge_into(sku, target, self.stdout)
                phase2_merged += 1
            else:
                # Just update colour to Unknown (no conflict)
                sku.colour = "Unknown"
                sku.save(update_fields=["colour", "updated_at"])
                phase2_fixed += 1

        # ── Phase 3: Delete zero-stock, zero-ref "Unknown" colour rows ──────
        self.stdout.write("\nPhase 3: Removing zero-stock Unknown-colour rows with no references…")
        unknown_qs = list(
            PrintedSKU.objects.filter(colour="Unknown", on_hand=0, reserved=0)
            .select_related("design")
        )
        deleted_count = 0
        for sku in unknown_qs:
            if _has_refs(sku):
                continue
            if dry_run:
                self.stdout.write(f"  WOULD delete: {sku}")
                deleted_count += 1
                continue
            sku.delete()
            deleted_count += 1
        
        phase3_deleted = deleted_count

        verb = "Would change" if dry_run else "Changed"
        self.stdout.write(
            self.style.SUCCESS(
                f"\nCleanup complete.\n"
                f"  Phase 1 (size-in-variant): fixed={phase1_fixed}, merged={phase1_merged}, skipped={phase1_skipped}\n"
                f"  Phase 2 (policy colour):   fixed={phase2_fixed}, merged={phase2_merged}, skipped={phase2_skipped}\n"
                f"  Phase 3 (delete Unknown):  {verb} {phase3_deleted} rows\n"
            )
        )
