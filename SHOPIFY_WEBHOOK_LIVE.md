# Shopify Webhook Setup - Complete & Live ✅

## Current Status

**App**: https://stoicsocial-web-production.up.railway.app  
**Database**: PostgreSQL online with 4 orders (3 seeded + 1 from test webhook)  
**Webhook Endpoint**: `/webhooks/shopify/` - Live and processing orders  
**Processing**: Synchronous (immediate persistence, no worker required)

---

## Test Credentials

| User | Role | Access | Password |
|------|------|--------|----------|
| **ARC** | Admin | All areas | `ARC@BoldERP2026!` |
| **testim** | Inventory Manager | Inventory only | `Testim@Inv2026!` |
| **testsales** | Sales Manager | Sales only | `TestSales@2026!` |
| **testfin** | Finance Manager | Finance only | `TestFin@2026!` |

---

## Database Contents

```
✓ 3 Designs (Classic Tee, Premium Fit, Oversized Drop Shoulder)
✓ 25 Blank SKUs (inventory stock)
✓ 36 Printed SKUs (print inventory)
✓ 4 Orders (3 seeded + 1 from test webhook)
✓ 5 Order Lines
```

### View Data
- **Designs**: https://stoicsocial-web-production.up.railway.app/admin/core/design/
- **Orders**: https://stoicsocial-web-production.up.railway.app/ops/inventory/orders/
- **Print Batches**: https://stoicsocial-web-production.up.railway.app/ops/inventory/print-batches/

---

## Shopify Integration Setup

### Step 1: Create Shopify App

1. Log in to Shopify Admin: https://admin.shopify.com
2. Go to **Settings → Apps and Integrations → Develop apps**
3. Click **Create an app**:
   - Name: "BoldERP Production"
   - Type: Custom app (for internal use)
4. In **Configuration** tab, enable scopes:
   - `read_orders`
   - `write_orders`
5. Copy the **API Access Token** (you'll need this for Shopify API calls)

### Step 2: Configure Webhooks in Shopify

1. In the Shopify app, go to **Configuration → Webhooks**
2. **Create webhook** for each topic:

| Topic | URL |
|-------|-----|
| Orders → Created | `https://erp.boldanditalic.in/webhooks/shopify/` |
| Orders → Updated | `https://erp.boldanditalic.in/webhooks/shopify/` |
| Orders → Cancelled | `https://erp.boldanditalic.in/webhooks/shopify/` |
| Orders → Fulfilled *(optional)* | `https://erp.boldanditalic.in/webhooks/shopify/` |

3. **Copy the signing secret** from any webhook (all use the same secret)

### Step 3: Configure Railway Environment Variable

Set the Shopify webhook signing secret on Railway:

```bash
railway variable set SHOPIFY_API_SECRET="<YOUR_SHOPIFY_SIGNING_SECRET>" --service stoicsocial-web
```

Replace `<YOUR_SHOPIFY_SIGNING_SECRET>` with the secret from Shopify.

---

## Testing Webhook Delivery

### Test Script

Run the webhook delivery test locally or remotely:

```bash
# Test local environment
python test_webhook_delivery.py \
  --url http://localhost:8000/webhooks/shopify/ \
  --secret "your-local-secret"

# Test Railway deployment
python test_webhook_delivery.py \
   --url https://erp.boldanditalic.in/webhooks/shopify/ \
  --secret "your-shopify-signing-secret" \
  --skip-verify
```

### Expected Response

**Success (200 OK)**:
```json
{
  "processed": true,
  "event_id": "47539e47-a4e0-487b-bfb2-5fce0648b09d"
}
```

**HMAC Failure (401)**:
```json
{
  "detail": "Invalid signature"
}
```

**Order Error (500)**:
```json
{
  "detail": "error message"
}
```

---

## Webhook Behavior

### How Orders Flow

1. **Shopify → BoldERP**
   - Shopify sends POST to `/webhooks/shopify/`
   - BoldERP verifies HMAC signature
   - Order ingested and persisted to database
   - Returns 200 OK immediately

2. **Order Matching**
   - Line items matched by: design name + colour + size
   - If printed stock available → `ready_ship` status
   - If not available → `to_be_printed` status
   - If no design match → `to_be_printed` (creates demand)

3. **Status Propagation**
   - Order status = worst-case line status
   - Statuses: new → needs_printing → in_printing → ready_to_ship → shipped

### Idempotency

- Each webhook has unique `idempotency_key` (Shopify webhook ID)
- Duplicate webhooks are deduplicated at database level
- Safe to retry webhook delivery

### Event Tracking

All webhooks logged in `WebhookEvent` table:
- `source`: "shopify"
- `topic`: "orders/create", "orders/updated", etc.
- `idempotency_key`: Shopify webhook ID
- `payload`: Full Shopify payload
- `processed_at`: Timestamp when processed

View events:
```bash
railway run python manage.py shell
>>> from core.models import WebhookEvent
>>> WebhookEvent.objects.filter(source='shopify').count()
>>> list(WebhookEvent.objects.values('topic', 'processed_at'))
```

---

## Catch-Up Sync (when webhooks miss orders)

Webhooks are the primary path, but they fail silently: if the subscription is deleted in
Shopify or `SHOPIFY_API_SECRET` drifts from the signing secret, every delivery is rejected with
a 401 **before** a `WebhookEvent` row is written. Nothing appears in the events table — the only
symptom is that orders stop arriving.

### Step 1 — Read the sync-health banner

The Orders page (`/ops/inventory/orders/`) shows a banner above the stat cards with the last
webhook received, the count in the last 24 hours, and the newest order in the ERP. If no webhook
has arrived in 24 hours it turns red and names the two things to check. Start there — it tells
you within seconds whether deliveries stopped, and when.

### Step 2 — Confirm the subscription in Shopify

Shopify Admin → App → **Webhooks**. Confirm the four topics from Step 2 above still exist and
point at `https://erp.boldanditalic.in/webhooks/shopify/`, and that recent deliveries show 200,
not 401. A 401 means the secret is wrong; a missing row means the subscription was deleted.
Re-create the webhook, or re-set `SHOPIFY_API_SECRET` on Railway to match the signing secret.

### Step 3 — Pull in whatever was missed

`sync_shopify_orders` defaults to a full history backfill. Add a window to make it incremental —
it sends Shopify's `updated_at_min`, so it fetches only orders created or changed since then:

```bash
# Dry run first: fetch and count, write nothing.
railway run python manage.py sync_shopify_orders --since-minutes 1440 --dry-run

# Then for real, behaving exactly like a live webhook (reserves printed stock).
railway run python manage.py sync_shopify_orders --since-minutes 1440 --apply-inventory

# Or from an exact instant, which overrides --since-minutes.
railway run python manage.py sync_shopify_orders --updated-at-min 2026-08-16T00:00:00Z --apply-inventory
```

| Flag | Effect |
|------|--------|
| `--since-minutes N` | Only orders Shopify updated in the last N minutes |
| `--updated-at-min ISO` | Same, from an exact ISO-8601 timestamp; overrides `--since-minutes` |
| `--apply-inventory` | Reserve printed stock as a webhook would. **Omit for a full historical backfill** |
| `--dry-run` | Fetch and count only; no DB writes |

The command reports `created` and `updated` separately. Re-running it is safe: `ingest_order`
upserts on `shopify_order_id`, so re-processing an order that already arrived is a no-op.

> Historical orders imported before Aug 2026 carry the date BoldERP imported them in
> `created_at`. Migration `0008` recovers the real Shopify dates from each order's stored
> `raw_payload` into `shopify_created_at`, which is what the dashboard sorts and filters on.

### Step 4 — Turn on the automatic poll

A Django-Q2 schedule can run the same catch-up every 10 minutes, so a dropped delivery
self-heals without anyone noticing:

```bash
railway run python manage.py shell
>>> from core.tasks import schedule_shopify_catch_up
>>> schedule_shopify_catch_up()          # every 10 minutes; pass minutes=N to change
```

Each run looks back 3× the interval, so a slow run can't leave a gap.

> **This requires the `worker: python manage.py qcluster` process to actually be deployed on
> Railway.** The `Procfile` declares it, but if that service isn't running the schedule row is
> created and never fires. Confirm with `railway logs --service <worker>`; if there is no worker
> service, run the Step 3 command from a Railway cron instead — it does the same work.

Environment variables the poll needs (the same ones the command reads):
`SHOPIFY_SHOP_DOMAIN`, `SHOPIFY_ADMIN_API_TOKEN`, and optionally `SHOPIFY_API_VERSION`. If any
are missing the task logs a warning and returns zero counts rather than failing.

---

## Troubleshooting

### Webhooks Not Being Processed

0. **Check the sync-health banner** on `/ops/inventory/orders/` — it reports the last webhook
   received and how long ago. See [Catch-Up Sync](#catch-up-sync-when-webhooks-miss-orders) for
   the full recovery procedure.

1. **Check Shopify Webhook Status**:
   - Shopify Admin → App → Webhooks
   - Look for red ❌ or yellow ⚠️ status codes
   - Click webhook to see recent deliveries

2. **Check Railway Logs**:
   ```bash
   railway logs | grep -i webhook
   railway logs | grep -i error
   ```

3. **Verify HMAC Configuration**:
   ```bash
   railway run python manage.py shell
   >>> from django.conf import settings
   >>> print(settings.SHOPIFY_API_SECRET)
   ```
   - Should match Shopify's signing secret

4. **Test Endpoint Directly**:
   ```bash
   python test_webhook_delivery.py --url ... --secret ...
   ```
   - Should return 200 OK with `"processed": true`

### Common Errors

**"Invalid signature" (401)**
- SHOPIFY_API_SECRET doesn't match Shopify's secret
- Fix: Update environment variable on Railway
- Note: rejected deliveries are **not** written to `WebhookEvent` (the endpoint is public, so
  logging unauthenticated POSTs would grow the table without bound). They appear only in the
  Railway logs as a warning, and as silence on the Orders sync banner.

**Orders arriving but showing as unmatched**
- The Shopify product title doesn't match any Design in the ERP
- Fix: Print Batches page → "Unmatched Orders" table → link to an existing Printed SKU or create
  the missing one. Leave **Remember this name** ticked and a `ProductNameAlias` is stored, so
  every future order with that title matches on its own.

**"SKU is not a valid UUID" (500)**
- Test payload has invalid SKU format
- Fix: Webhooks match by design name, not SKU. Leave SKU empty.

**Order not created despite 200 OK**
- Order might already exist (idempotency)
- Check database: `railway run python manage.py shell`

**502 Bad Gateway**
- App crashed or still deploying
- Check status: `railway status`
- View logs: `railway logs`

---

## Next Steps (Optional)

### 1. Set Up Django-Q Worker (For High Volume)

For high-volume Shopify stores (100+ orders/day), offload webhook processing to async worker:

```bash
railway add --service stoicsocial-worker --dockerfile Dockerfile.worker
```

Then update webhook endpoint to use `async_task` instead of sync processing.

### 2. Connect to Real Shopify Store

1. Create app in production Shopify store
2. Update SHOPIFY_API_SECRET on Railway
3. Configure webhooks in Shopify to point to live endpoint
4. Test with real orders

### 3. Add Webhook Retry Logic

Shopify retries failed webhooks on its own. For deliveries it gives up on — or never attempts,
because the subscription is gone — the poll in
[Catch-Up Sync](#catch-up-sync-when-webhooks-miss-orders) is the backstop:

```bash
railway run python manage.py shell
>>> from core.tasks import schedule_shopify_catch_up
>>> schedule_shopify_catch_up()
```

### 4. Monitor Order Flow

The Orders page already shows orders by status, the sync-health banner, and a link to the
webhook event log. Beyond that, consider alerting on the banner's stale condition.

---

## Commands Reference

```bash
# View recent orders (by real Shopify order date, not import date)
railway run python manage.py shell -c "from core.models import Order; print(list(Order.objects.order_by('-shopify_created_at')[:5]))"

# Catch up on anything webhooks missed in the last day
railway run python manage.py sync_shopify_orders --since-minutes 1440 --apply-inventory

# Enable the 10-minute automatic catch-up poll (needs the qcluster worker)
railway run python manage.py shell -c "from core.tasks import schedule_shopify_catch_up; schedule_shopify_catch_up()"

# Seed test data
railway run python manage.py seed_test_data --full

# Check webhook events
railway run python manage.py shell -c "from core.models import WebhookEvent; print(WebhookEvent.objects.filter(source='shopify').count())"

# View app logs
railway logs

# Trigger deployment
railway up --detach
```

---

## Architecture

```
Shopify Admin
    ↓
    ├→ POST /webhooks/shopify/          (primary path, real time)
    │   (HMAC verification — a 401 here writes nothing to the DB)
    │       ↓
    └→ sync_shopify_orders / core.tasks.sync_recent_shopify_orders
        (catch-up path, polls updated_at_min — same ingest, same result)
            ↓
        core/services/shopify.py
            ├→ ingest_order()           (upsert on shopify_order_id)
            ├→ mark_cancelled()
            └→ sync_fulfillment()
            ↓
        Database (Orders, OrderLines, WebhookEvents, ProductNameAlias)
            ↓
        Inventory System
        (reserve_printed, release_printed, commit_printed)
            ↓
        Print Batches, Pick Lists, etc.
```

---

**Status**: ✅ Live and ready for Shopify integration  
**Last Updated**: 2026-08-18  
**Documentation**: See [SHOPIFY_WEBHOOK_SETUP.md](docs/SHOPIFY_WEBHOOK_SETUP.md) for detailed guide
