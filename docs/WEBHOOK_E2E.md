# Shopify Webhook End-to-End Walkthrough

This repo now includes a small webhook test kit that sends signed Shopify-style requests to the local endpoint at `/webhooks/shopify/`.

## What this covers

- `orders/create` for a mixed order with one stocked line and one line that must be printed
- `orders/updated` for the same order while it is still open
- `orders/fulfilled` after the internal print and receive flow finishes
- `orders/cancelled` for a separate unfulfilled order
- idempotency verification using a repeated webhook ID

## Included files

- `docs/webhook-tests/orders-create-mixed.json`
- `docs/webhook-tests/orders-updated-mixed.json`
- `docs/webhook-tests/orders-fulfilled-mixed.json`
- `docs/webhook-tests/orders-create-cancel.json`
- `docs/webhook-tests/orders-cancelled-cancel.json`
- `core/management/commands/send_shopify_webhook.py`

The payloads were chosen to resolve against the seeded workbook data already loaded in this workspace:

- `Amrutham & Chill / White / L` has on-hand printed stock
- `Bro I Don't Care / Red / S` currently has zero printed stock and will route to printing

## One-time setup

1. Activate the virtual environment.

```powershell
.\venv\Scripts\Activate.ps1
```

2. Make sure the database is migrated and seeded.

```powershell
python manage.py migrate
python manage.py seed_from_excel
```

3. Start the web server in one terminal.

```powershell
python manage.py runserver
```

4. Start the Django-Q2 worker in a second terminal.

```powershell
python manage.py qcluster
```

The walkthrough assumes your local `.env` has a valid `SHOPIFY_API_SECRET` or `SHOPIFY_WEBHOOK_SECRET` configured.

## Scenario A: Mixed order from create to fulfillment

### Step 1: Send the `orders/create` webhook

```powershell
python manage.py send_shopify_webhook orders/create docs/webhook-tests/orders-create-mixed.json
```

Expected HTTP result:

- `202` from the HTTP endpoint
- the worker then creates or updates order `#WH-1001`

### Step 2: Verify the post-create state

```powershell
python manage.py shell -c "from core.models import Order, PrintedSKU; order = Order.objects.get(shopify_order_id='9900000001001'); print('order', order.order_no, order.status, order.shopify_fulfillment_status); print('lines', list(order.lines.values_list('shopify_line_id', 'product_name', 'size', 'quantity', 'status'))); stocked = PrintedSKU.objects.select_related('design').get(design__name='Amrutham & Chill', colour='White', size='L'); queued = PrintedSKU.objects.select_related('design').get(design__name='Bro I Don\'t Care', colour='Red', size='S'); print('stocked_sku', stocked.on_hand, stocked.reserved, stocked.available); print('queued_sku', queued.on_hand, queued.reserved, queued.available)"
```

Expected state:

- order status: `needs_printing`
- `Amrutham & Chill / White / L` line: `ready_ship`
- `Bro I Don't Care / Red / S` line: `to_be_printed`
- `Amrutham & Chill / White / L` reserved increases by `2`
- `Bro I Don't Care / Red / S` remains at `0 on_hand / 0 reserved`

### Step 3: Resend the same create webhook with a fixed webhook ID

This verifies that the HTTP path now preserves idempotency through `WebhookEvent`.

```powershell
python manage.py send_shopify_webhook orders/create docs/webhook-tests/orders-create-mixed.json --webhook-id demo-create-1001
python manage.py send_shopify_webhook orders/create docs/webhook-tests/orders-create-mixed.json --webhook-id demo-create-1001
```

Verify only one event row exists for that repeated ID:

```powershell
python manage.py shell -c "from core.models import WebhookEvent; print(WebhookEvent.objects.filter(source='shopify', topic='orders/create', idempotency_key='demo-create-1001').count())"
```

Expected state:

- event count: `1`
- order inventory state does not double-reserve

### Step 4: Send the `orders/updated` webhook

This increases the print-queue line from `1` to `2` while leaving the stocked line unchanged.

```powershell
python manage.py send_shopify_webhook orders/updated docs/webhook-tests/orders-updated-mixed.json
```

Verify the updated quantity:

```powershell
python manage.py shell -c "from core.models import Order; order = Order.objects.get(shopify_order_id='9900000001001'); print(list(order.lines.values_list('shopify_line_id', 'product_name', 'quantity', 'status')))"
```

Expected state:

- `Amrutham & Chill / White / L` stays `ready_ship`
- `Bro I Don't Care / Red / S` quantity becomes `2`
- order stays `needs_printing`

### Step 5: Run the internal print flow for the queued line

1. Open the print batch screen and confirm a batch that includes `Bro I Don't Care / Red / S`.
   - URL: `http://127.0.0.1:8000/ops/print-batches/`
   - Choose any active vendor
   - Confirm at least `2` units for `Bro I Don't Care / Red / S`

2. Open the receive dashboard and receive those units.
   - URL: `http://127.0.0.1:8000/ops/receive/`
   - Receive `2` good units and `0` defective units for that print job line

3. Verify the order is now ready internally.

```powershell
python manage.py shell -c "from core.models import Order, PrintedSKU; order = Order.objects.get(shopify_order_id='9900000001001'); queued = PrintedSKU.objects.select_related('design').get(design__name='Bro I Don\'t Care', colour='Red', size='S'); print('order', order.status); print('lines', list(order.lines.values_list('product_name', 'quantity', 'status'))); print('queued_sku', queued.on_hand, queued.reserved, queued.available)"
```

Expected state after receive:

- order status: `ready_to_ship`
- both lines are `ready_ship`
- `Bro I Don't Care / Red / S` on-hand has increased from the receive step

### Step 6: Send the `orders/fulfilled` webhook

```powershell
python manage.py send_shopify_webhook orders/fulfilled docs/webhook-tests/orders-fulfilled-mixed.json
```

### Step 7: Verify the shipped state and stock commit

```powershell
python manage.py shell -c "from core.models import Order, PrintedSKU, StockMovement; order = Order.objects.get(shopify_order_id='9900000001001'); stocked = PrintedSKU.objects.select_related('design').get(design__name='Amrutham & Chill', colour='White', size='L'); queued = PrintedSKU.objects.select_related('design').get(design__name='Bro I Don\'t Care', colour='Red', size='S'); print('order', order.order_no, order.status, order.shopify_fulfillment_status, order.shopify_delivery_status); print('lines', list(order.lines.values_list('product_name', 'quantity', 'status'))); print('stocked_sku', stocked.on_hand, stocked.reserved, stocked.available); print('queued_sku', queued.on_hand, queued.reserved, queued.available); print('ship_moves', list(StockMovement.objects.filter(reason='ship', ref_table='order_line', ref_id__in=order.lines.values_list('id', flat=True)).values_list('delta_on_hand', 'delta_reserved', 'note')))"
```

Expected state:

- order status: `shipped`
- fulfillment status: `fulfilled`
- delivery status: `delivered`
- both lines: `shipped`
- `Amrutham & Chill / White / L` loses `2 on_hand` and releases its `2 reserved`
- `Bro I Don't Care / Red / S` ships from the stock received through the print workflow

## Scenario B: Cancel an unfulfilled order

### Step 1: Send the cancellable `orders/create` webhook

```powershell
python manage.py send_shopify_webhook orders/create docs/webhook-tests/orders-create-cancel.json
```

### Step 2: Verify it is queued for printing

```powershell
python manage.py shell -c "from core.models import Order; order = Order.objects.get(shopify_order_id='9900000001002'); print('order', order.order_no, order.status); print('lines', list(order.lines.values_list('product_name', 'quantity', 'status')))"
```

Expected state:

- order status: `needs_printing`
- line status: `to_be_printed`

### Step 3: Send the `orders/cancelled` webhook

```powershell
python manage.py send_shopify_webhook orders/cancelled docs/webhook-tests/orders-cancelled-cancel.json
```

### Step 4: Verify cancellation

```powershell
python manage.py shell -c "from core.models import Order; order = Order.objects.get(shopify_order_id='9900000001002'); print('order', order.order_no, order.status); print('lines', list(order.lines.values_list('product_name', 'status')))"
```

Expected state:

- order status: `cancelled`
- line status: `cancelled`
- no printed reservation remains for that order

## Notes and limits

- The local endpoint returns `202` immediately because work is queued into Django-Q2. If you do not run `qcluster`, the payload will be accepted but nothing will process.
- These payloads resolve SKUs by `product_title`, `color`, and `size`, so they remain readable and do not depend on database UUIDs.
- The walkthrough assumes the workbook seed data is present. If you reload the database with different design names, update the payload titles accordingly.
