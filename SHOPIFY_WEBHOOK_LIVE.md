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
| Orders → Created | `https://stoicsocial-web-production.up.railway.app/webhooks/shopify/` |
| Orders → Updated | `https://stoicsocial-web-production.up.railway.app/webhooks/shopify/` |
| Orders → Cancelled | `https://stoicsocial-web-production.up.railway.app/webhooks/shopify/` |
| Orders → Fulfilled *(optional)* | `https://stoicsocial-web-production.up.railway.app/webhooks/shopify/` |

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
  --url https://stoicsocial-web-production.up.railway.app/webhooks/shopify/ \
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

## Troubleshooting

### Webhooks Not Being Processed

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

Shopify retries failed webhooks. Configure Railway alerts:

```bash
railway run python manage.py shell
>>> from django_q.models import Schedule
>>> # Set up periodic reconciliation of stuck orders
```

### 4. Monitor Order Flow

Create a dashboard view showing:
- Orders by status
- Recent webhook events
- Failed webhooks (if any)

---

## Commands Reference

```bash
# View recent orders
railway run python manage.py shell -c "from core.models import Order; print(list(Order.objects.order_by('-created_at')[:5]))"

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
    └→ POST /webhooks/shopify/
        (HMAC verification)
            ↓
        core/services/shopify.py
            ├→ ingest_order()
            ├→ mark_cancelled()
            └→ sync_fulfillment()
            ↓
        Database (Orders, OrderLines, WebhookEvents)
            ↓
        Inventory System
        (reserve_printed, release_printed, commit_printed)
            ↓
        Print Batches, Pick Lists, etc.
```

---

**Status**: ✅ Live and ready for Shopify integration  
**Last Updated**: 2026-06-14  
**Documentation**: See [SHOPIFY_WEBHOOK_SETUP.md](docs/SHOPIFY_WEBHOOK_SETUP.md) for detailed guide
