# Shopify Webhook Setup for Railway

## Step 1: Get Shopify API Credentials

1. Go to Shopify Admin: https://admin.shopify.com
2. Navigate to **Settings → Apps and Integrations**
3. Click **Develop apps** (top right)
4. Click **Create an app** and set:
   - **App name**: BoldERP Production
   - **App type**: Public or Custom (choose Custom for internal use)
5. After creation, open the app and go to the **Configuration** tab
6. Under **Admin API access scopes**, enable:
   - `read_orders`
   - `write_orders`
7. Go to the **API credentials** tab and copy the **API Access Token**

## Step 2: Set up Webhooks in Shopify

1. In the app's **Configuration** tab, scroll to **Webhooks**
2. Click **Create webhook** for each topic:
   - Topic: **Orders → Created**
   - Topic: **Orders → Updated**
   - Topic: **Orders → Cancelled**
   - Topic: **Orders → Fulfilled** (optional, for fulfillment tracking)

3. For each webhook, enter:
   - **URL**: `https://stoicsocial-web-production.up.railway.app/webhooks/shopify/`
   - **Format**: JSON

4. Copy the **Webhook endpoint signing secret** from the webhook details (used for HMAC verification)

## Step 3: Configure Railway Environment Variables

Get the webhook signing secret from Shopify and set it on Railway:

```bash
railway variable set SHOPIFY_API_SECRET="<YOUR_SHOPIFY_WEBHOOK_SECRET>" --service stoicsocial-web
```

Replace `<YOUR_SHOPIFY_WEBHOOK_SECRET>` with the signing secret from Shopify.

## Step 4: Verify Webhook Delivery

### From Shopify Admin:
1. In your Shopify app's Webhooks section, click on a webhook
2. Scroll to **Recent deliveries**
3. Should show green ✓ status codes (202 Accepted)

### From Railway App:
```bash
railway logs --deployment <ID> | grep webhook
```

### Manual Test (Optional):
```bash
python manage.py send_shopify_webhook --topic orders/created --json '{"id":"1234","name":"#1001",...}'
```

## Webhook Event Payload

BoldERP expects Shopify order webhooks with:

```json
{
  "id": "1234567890",
  "name": "#1001",
  "email": "customer@example.com",
  "fulfillment_status": "unfulfilledquantity",
  "line_items": [
    {
      "id": "111111111",
      "title": "Classic Tee",
      "quantity": 2,
      "size": "M",
      "color": "Black"
    }
  ]
}
```

## Database Verification

After receiving webhooks:

```bash
railway run python manage.py shell
>>> from core.models import Order, WebhookEvent
>>> Order.objects.count()  # Should increase
>>> WebhookEvent.objects.filter(source='shopify').count()  # Should show events
```

## Troubleshooting

### 403 Forbidden on webhook endpoint:
- Check SHOPIFY_API_SECRET is set on Railway
- Verify HMAC signature verification: `railway logs | grep "Invalid signature"`

### Orders not created:
- Check webhook topic is `orders/create` or `orders/updated`
- Verify order JSON has required fields (id, line_items)
- Check logs: `railway logs --deployment <ID>`

### Async processing delay:
- If using Django-Q2, webhook is queued asynchronously
- Check worker logs: `railway logs --service <worker-service-name>`
- For now, web service processes webhooks immediately (synchronous fallback)
