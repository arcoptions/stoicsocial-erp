from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction

from core.models import BlankSKU, Order, OrderLine, PrintedSKU, PrintJobLine, StockMovement

User = get_user_model()

ORDER_STATUS_RANK: dict[str, int] = {
    Order.STATUS_NEW: 0,
    Order.STATUS_NEEDS_PRINTING: 1,
    Order.STATUS_IN_PRINTING: 2,
    Order.STATUS_READY_TO_SHIP: 3,
    Order.STATUS_SHIPPED: 4,
    Order.STATUS_CANCELLED: 5,
}

LINE_TO_ORDER_STATUS: dict[str, str] = {
    OrderLine.STATUS_NEW: Order.STATUS_NEW,
    OrderLine.STATUS_TO_BE_PRINTED: Order.STATUS_NEEDS_PRINTING,
    OrderLine.STATUS_IN_PRINTING: Order.STATUS_IN_PRINTING,
    OrderLine.STATUS_READY_SHIP: Order.STATUS_READY_TO_SHIP,
    OrderLine.STATUS_SHIPPED: Order.STATUS_SHIPPED,
    OrderLine.STATUS_CANCELLED: Order.STATUS_CANCELLED,
}


def _recompute_order_status(order: Order) -> str:
    """Recompute order status from its line statuses using worst-case semantics."""
    line_statuses = [LINE_TO_ORDER_STATUS.get(status, Order.STATUS_NEW) for status in order.lines.values_list("status", flat=True)]
    if not line_statuses:
        order.status = Order.STATUS_ISSUE
    else:
        non_terminal = [status for status in line_statuses if status not in {Order.STATUS_SHIPPED, Order.STATUS_CANCELLED}]
        candidates = non_terminal or line_statuses
        order.status = min(candidates, key=lambda status: ORDER_STATUS_RANK.get(status, 999))
    order.save(update_fields=["status", "updated_at"])
    return order.status


def _create_movement(
    *,
    pool: str,
    blank_sku: BlankSKU | None = None,
    printed_sku: PrintedSKU | None = None,
    delta_on_hand: int = 0,
    delta_reserved: int = 0,
    reason: str,
    ref_table: str = "",
    ref_id: Any = None,
    note: str = "",
    actor: User | None = None,
) -> StockMovement:
    """Create a stock movement row for auditability."""
    return StockMovement.objects.create(
        pool=pool,
        blank_sku=blank_sku,
        printed_sku=printed_sku,
        delta_on_hand=delta_on_hand,
        delta_reserved=delta_reserved,
        reason=reason,
        ref_table=ref_table,
        ref_id=ref_id,
        note=note,
        actor=actor,
    )


def deduct_plain(blank_sku_id: str, qty: int, actor: User | None = None) -> BlankSKU:
    """Deduct plain stock from a blank SKU after locking the row.

    Raises:
        ValueError: If quantity is invalid or on-hand stock is insufficient.
    """
    if qty <= 0:
        raise ValueError("Quantity to deduct must be a positive integer.")

    with transaction.atomic():
        blank_sku = BlankSKU.objects.select_for_update().get(id=blank_sku_id)
        if blank_sku.on_hand < qty:
            raise ValueError(
                f"Insufficient plain stock for {blank_sku}. Requested {qty}, available {blank_sku.on_hand}."
            )
        blank_sku.on_hand -= qty
        if blank_sku.on_hand < 0:
            raise ValueError(f"Deduction would result in negative plain stock for {blank_sku}.")
        blank_sku.save(update_fields=["on_hand", "updated_at"])
        _create_movement(
            pool=StockMovement.TYPE_PLAIN,
            blank_sku=blank_sku,
            delta_on_hand=-qty,
            reason=StockMovement.Reason.PRINT_BATCH_CONFIRM,
            ref_table="blank_sku",
            ref_id=blank_sku.id,
            actor=actor,
        )
        return blank_sku


def commit_printed(order_line: OrderLine, actor: User | None = None) -> OrderLine:
    """Hard-commit printed stock for a shipped order line and refresh the parent order status.

    Raises:
        ValueError: If the order line has no printed SKU or stock is insufficient.
    """
    with transaction.atomic():
        locked_line = OrderLine.objects.select_for_update().select_related("order", "printed_sku").get(id=order_line.id)
        if locked_line.status == OrderLine.STATUS_SHIPPED:
            return locked_line
        if locked_line.printed_sku_id is None:
            raise ValueError("Cannot commit printed stock for an order line without a PrintedSKU.")
        printed_sku = PrintedSKU.objects.select_for_update().get(id=locked_line.printed_sku_id)
        if printed_sku.on_hand < locked_line.quantity:
            raise ValueError(
                f"Insufficient printed stock for {printed_sku}. Requested {locked_line.quantity}, available {printed_sku.on_hand}."
            )
        reserved_to_release = min(printed_sku.reserved, locked_line.quantity)
        printed_sku.on_hand -= locked_line.quantity
        printed_sku.reserved -= reserved_to_release
        if printed_sku.on_hand < 0 or printed_sku.reserved < 0:
            raise ValueError(f"Committing shipment would result in negative stock for {printed_sku}.")
        printed_sku.save(update_fields=["on_hand", "reserved", "updated_at"])
        locked_line.status = OrderLine.STATUS_SHIPPED
        locked_line.save(update_fields=["status", "updated_at"])
        _create_movement(
            pool=StockMovement.TYPE_PRINTED,
            printed_sku=printed_sku,
            delta_on_hand=-locked_line.quantity,
            delta_reserved=-reserved_to_release,
            reason=StockMovement.Reason.SHIP,
            ref_table="order_line",
            ref_id=locked_line.id,
            note="Hard commit on fulfillment" if reserved_to_release == locked_line.quantity else "Hard commit without full prior reservation",
            actor=actor,
        )
        _recompute_order_status(locked_line.order)
        return locked_line


def reserve_printed(order_line: OrderLine, actor: User | None = None) -> OrderLine:
    """Soft-reserve printed stock for an order line on order creation.

    Raises:
        ValueError: If the order line has no printed SKU or reservable stock is insufficient.
    """
    with transaction.atomic():
        locked_line = OrderLine.objects.select_for_update().select_related("order", "printed_sku").get(id=order_line.id)
        if locked_line.printed_sku_id is None:
            raise ValueError("Cannot reserve printed stock for an order line without a PrintedSKU.")
        if locked_line.status in {OrderLine.STATUS_CANCELLED, OrderLine.STATUS_SHIPPED}:
            return locked_line
        printed_sku = PrintedSKU.objects.select_for_update().get(id=locked_line.printed_sku_id)
        if locked_line.status == OrderLine.STATUS_READY_SHIP and printed_sku.reserved >= locked_line.quantity:
            return locked_line
        available = printed_sku.on_hand - printed_sku.reserved
        if available < locked_line.quantity:
            raise ValueError(
                f"Insufficient printed stock to reserve for {printed_sku}. Requested {locked_line.quantity}, available {available}."
            )
        printed_sku.reserved += locked_line.quantity
        if printed_sku.reserved > printed_sku.on_hand:
            raise ValueError(f"Reservation would oversell printed stock for {printed_sku}.")
        printed_sku.save(update_fields=["reserved", "updated_at"])
        locked_line.status = OrderLine.STATUS_READY_SHIP
        locked_line.save(update_fields=["status", "updated_at"])
        _create_movement(
            pool=StockMovement.TYPE_PRINTED,
            printed_sku=printed_sku,
            delta_reserved=locked_line.quantity,
            reason=StockMovement.Reason.SOFT_RESERVE,
            ref_table="order_line",
            ref_id=locked_line.id,
            actor=actor,
        )
        _recompute_order_status(locked_line.order)
        return locked_line


def release_printed(order_line: OrderLine, actor: User | None = None) -> OrderLine:
    """Release a soft reservation for an order line on cancellation.

    Raises:
        ValueError: If the order line has no printed SKU or the release would underflow reserved stock.
    """
    with transaction.atomic():
        locked_line = OrderLine.objects.select_for_update().select_related("order", "printed_sku").get(id=order_line.id)
        if locked_line.printed_sku_id is None:
            raise ValueError("Cannot release printed stock for an order line without a PrintedSKU.")
        printed_sku = PrintedSKU.objects.select_for_update().get(id=locked_line.printed_sku_id)
        if printed_sku.reserved <= 0:
            locked_line.status = OrderLine.STATUS_CANCELLED if locked_line.order.status == Order.STATUS_CANCELLED else OrderLine.STATUS_TO_BE_PRINTED
            locked_line.save(update_fields=["status", "updated_at"])
            _recompute_order_status(locked_line.order)
            return locked_line
        if printed_sku.reserved < locked_line.quantity:
            raise ValueError(
                f"Cannot release {locked_line.quantity} reserved units from {printed_sku}; only {printed_sku.reserved} reserved."
            )
        printed_sku.reserved -= locked_line.quantity
        if printed_sku.reserved < 0:
            raise ValueError(f"Release would result in negative reserved stock for {printed_sku}.")
        printed_sku.save(update_fields=["reserved", "updated_at"])
        locked_line.status = OrderLine.STATUS_CANCELLED if locked_line.order.status == Order.STATUS_CANCELLED else OrderLine.STATUS_TO_BE_PRINTED
        locked_line.save(update_fields=["status", "updated_at"])
        _create_movement(
            pool=StockMovement.TYPE_PRINTED,
            printed_sku=printed_sku,
            delta_reserved=-locked_line.quantity,
            reason=StockMovement.Reason.RELEASE_RESERVATION,
            ref_table="order_line",
            ref_id=locked_line.id,
            actor=actor,
        )
        _recompute_order_status(locked_line.order)
        return locked_line


def manual_adjust(
    pool: str,
    sku_id: str,
    delta: int,
    reason: str,
    note: str,
    actor: User | None,
) -> StockMovement:
    """Apply a manual stock correction and write a StockMovement audit row.

    Raises:
        ValueError: If the pool is invalid or the adjustment would result in negative stock.
    """
    if pool not in {StockMovement.TYPE_PLAIN, StockMovement.TYPE_PRINTED}:
        raise ValueError("Pool must be either 'plain' or 'printed'.")

    with transaction.atomic():
        if pool == StockMovement.TYPE_PLAIN:
            blank_sku = BlankSKU.objects.select_for_update().get(id=sku_id)
            new_on_hand = blank_sku.on_hand + delta
            if new_on_hand < 0:
                raise ValueError(
                    f"Manual adjustment would result in negative plain stock for {blank_sku}."
                )
            blank_sku.on_hand = new_on_hand
            blank_sku.save(update_fields=["on_hand", "updated_at"])
            return _create_movement(
                pool=pool,
                blank_sku=blank_sku,
                delta_on_hand=delta,
                reason=reason,
                ref_table="blank_sku",
                ref_id=blank_sku.id,
                note=note,
                actor=actor,
            )

        printed_sku = PrintedSKU.objects.select_for_update().get(id=sku_id)
        new_on_hand = printed_sku.on_hand + delta
        if new_on_hand < printed_sku.reserved:
            raise ValueError(
                f"Manual adjustment would reduce printed stock below reserved units for {printed_sku}."
            )
        if new_on_hand < 0:
            raise ValueError(
                f"Manual adjustment would result in negative printed stock for {printed_sku}."
            )
        printed_sku.on_hand = new_on_hand
        printed_sku.save(update_fields=["on_hand", "updated_at"])
        return _create_movement(
            pool=pool,
            printed_sku=printed_sku,
            delta_on_hand=delta,
            reason=reason,
            ref_table="printed_sku",
            ref_id=printed_sku.id,
            note=note,
            actor=actor,
        )


def reserve_stock_for_order_line(order_line_id: str) -> None:
    """Compatibility wrapper for existing callers."""
    order_line = OrderLine.objects.get(id=order_line_id)
    reserve_printed(order_line)


def release_reservation_for_order_line(order_line_id: str) -> None:
    """Compatibility wrapper for existing callers."""
    order_line = OrderLine.objects.get(id=order_line_id)
    release_printed(order_line)


def commit_stock_for_shipped_order_line(order_line_id: str) -> None:
    """Compatibility wrapper for existing callers."""
    order_line = OrderLine.objects.get(id=order_line_id)
    commit_printed(order_line)


def receive_print_job_line(print_job_line_id: str, qty_good: int = 0, qty_defective: int = 0, actor: User | None = None) -> PrintJobLine:
    """Mark a print job line as received with good and defective quantities.
    
    Args:
        print_job_line_id: UUID of the PrintJobLine to receive
        qty_good: Quantity received in good condition
        qty_defective: Quantity received defective/damaged
        actor: User performing the action for audit trail
        
    Returns:
        Updated PrintJobLine instance
        
    Raises:
        ValueError: If quantities are negative or exceed qty_sent
    """
    if qty_good < 0 or qty_defective < 0:
        raise ValueError("Received quantities must be non-negative.")
    
    with transaction.atomic():
        line = PrintJobLine.objects.select_for_update().get(id=print_job_line_id)
        
        if qty_good + qty_defective > line.qty_sent:
            raise ValueError(
                f"Total received ({qty_good + qty_defective}) exceeds quantity sent ({line.qty_sent}) "
                f"for {line.printed_sku}."
            )
        
        line.qty_received_good = qty_good
        line.qty_received_defective = qty_defective
        line.save(update_fields=["qty_received_good", "qty_received_defective", "updated_at"])
        
        # Add to audit trail
        received_total = qty_good + qty_defective
        if received_total > 0:
            _create_movement(
                pool=StockMovement.TYPE_PRINTED,
                printed_sku=line.printed_sku,
                delta_on_hand=qty_good,  # Good units go to inventory
                reason=StockMovement.Reason.PRINT_RECEIVE,
                ref_table="print_job_line",
                ref_id=line.id,
                note=f"Received {qty_good} good, {qty_defective} defective",
                actor=actor,
            )
        
        return line
