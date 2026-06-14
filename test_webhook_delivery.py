#!/usr/bin/env python
"""
Test Shopify webhook delivery to the BoldERP webhook endpoint.

Usage:
    # Test locally (Django dev server must be running)
    python test_webhook_delivery.py --url http://localhost:8000/webhooks/shopify/ --secret <local-secret>
    
    # Test Railway deployment
    python test_webhook_delivery.py --url https://stoicsocial-web-production.up.railway.app/webhooks/shopify/ --secret <shopify-secret>
"""

import json
import hmac
import hashlib
import base64
import requests
import argparse
from datetime import datetime


def generate_hmac(payload_body: bytes, secret: str) -> str:
    """Generate Shopify HMAC signature for webhook verification."""
    digest = hmac.new(
        secret.encode('utf-8'),
        payload_body,
        hashlib.sha256
    ).digest()
    return base64.b64encode(digest).decode('utf-8')


def send_webhook_test(
    url: str,
    secret: str,
    topic: str = "orders/create",
    order_id: str = "4712999999999",
    skip_verify: bool = False
) -> tuple[int, dict]:
    """Send a test webhook payload to the specified endpoint."""
    
    # Sample order payload from Shopify
    payload = {
        "id": order_id,
        "email": "john@example.com",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
        "number": 1001,
        "note": None,
        "token": "test-token",
        "gateway": "shopify_payments",
        "test": False,
        "total_price": "99.99",
        "subtotal_price": "99.99",
        "total_weight": 0,
        "currency": "USD",
        "financial_status": "authorized",
        "confirmed": True,
        "total_discounts": "0.00",
        "total_line_items_price": "99.99",
        "cart_token": None,
        "buyer_accepts_marketing": False,
        "name": "#1001",
        "referring_site": None,
        "landing_site": None,
        "cancelled_at": None,
        "cancel_reason": None,
        "total_price_usd": "99.99",
        "checkout_token": None,
        "reference": None,
        "user_id": None,
        "location_id": None,
        "source_identifier": None,
        "source_url": None,
        "processed_at": datetime.now().isoformat(),
        "device_id": None,
        "phone": None,
        "customer_locale": None,
        "app_id": 755357713,
        "browser_ip": "192.0.2.1",
        "landing_site_ref": None,
        "number_of_attributes": 0,
        "note_attributes": [],
        "payment_gateway_names": ["shopify_payments"],
        "processing_method": "direct",
        "checkout_id": None,
        "source_name": "api",
        "fulfillment_status": None,
        "tags": "test",
        "contact_email": "john@example.com",
        "order_status_url": "https://stoic-social.myshopify.com/orders/4712999999999",
        "presentment_currency": "USD",
        "shipping_lines": [
            {
                "id": 1234567890,
                "title": "Standard",
                "price": "9.99",
                "price_set": {
                    "shop_money": {
                        "amount": "9.99",
                        "currency_code": "USD"
                    },
                    "presentment_money": {
                        "amount": "9.99",
                        "currency_code": "USD"
                    }
                },
                "custom": False,
                "handle": "standard",
                "delivery_category": None,
                "carrier_identifier": None,
                "tax_lines": []
            }
        ],
        "billing_address": {
            "first_name": "John",
            "address1": "1234 Main St",
            "phone": "555-1234",
            "city": "Boston",
            "zip": "02101",
            "province": "MA",
            "country": "United States",
            "last_name": "Doe",
            "address2": "",
            "company": "",
            "latitude": None,
            "longitude": None,
            "country_code": "US",
            "province_code": "MA"
        },
        "shipping_address": {
            "first_name": "John",
            "address1": "1234 Main St",
            "phone": "555-1234",
            "city": "Boston",
            "zip": "02101",
            "province": "MA",
            "country": "United States",
            "last_name": "Doe",
            "address2": "",
            "company": "",
            "latitude": None,
            "longitude": None,
            "country_code": "US",
            "province_code": "MA"
        },
        "customer": {
            "id": 1234567890,
            "email": "john@example.com",
            "accepts_marketing": False,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "first_name": "John",
            "last_name": "Doe",
            "orders_count": 1,
            "state": "enabled",
            "total_spent": "99.99",
            "last_order_id": 4712999999999,
            "note": None,
            "verified_email": True,
            "multipass_identifier": None,
            "tax_exempt": False,
            "phone": "555-1234",
            "tags": "",
            "last_order_name": "#1001",
            "currency": "USD",
            "accepts_marketing_updated_at": datetime.now().isoformat(),
            "marketing_opt_in_level": None,
            "tax_exemptions": [],
            "email_marketing_consent": {
                "state": "not_subscribed",
                "opt_in_level": None,
                "consent_updated_at": None
            },
            "sms_marketing_consent": {
                "state": "not_subscribed",
                "opt_in_level": None,
                "consent_updated_at": None
            },
            "addresses": [
                {
                    "id": 1234567890,
                    "customer_id": 1234567890,
                    "first_name": "John",
                    "last_name": "Doe",
                    "company": "",
                    "address1": "1234 Main St",
                    "address2": "",
                    "city": "Boston",
                    "province": "MA",
                    "country": "United States",
                    "zip": "02101",
                    "phone": "555-1234",
                    "default": True
                }
            ]
        },
        "line_items": [
            {
                "id": 1234567890,
                "variant_id": 1234567890,
                "title": "Classic Tee",
                "quantity": 2,
                "sku": "",  # Will match by design name + colour + size
                "variant_title": None,
                "vendor": "stoic-social",
                "fulfillment_service": "manual",
                "product_id": 1234567890,
                "requires_shipping": True,
                "taxable": True,
                "gift_card": False,
                "name": "Classic Tee",
                "variant_inventory_management": "shopify",
                "properties": [],
                "product_exists": True,
                "fulfillment_status": None,
                "grams": 200,
                "price": "49.99",
                "option1": None,
                "option2": "Black",  # Colour
                "option3": "M",      # Size
                "price_set": {
                    "shop_money": {
                        "amount": "49.99",
                        "currency_code": "USD"
                    },
                    "presentment_money": {
                        "amount": "49.99",
                        "currency_code": "USD"
                    }
                },
                "total_discount": "0.00",
                "total_discount_set": {
                    "shop_money": {
                        "amount": "0.00",
                        "currency_code": "USD"
                    },
                    "presentment_money": {
                        "amount": "0.00",
                        "currency_code": "USD"
                    }
                },
                "discount_allocations": [],
                "duties": [],
                "admin_graphql_api_id": "gid://shopify/LineItem/1234567890",
                "tax_lines": [
                    {
                        "title": "US Sales Tax",
                        "price": "4.50",
                        "rate": 0.09,
                        "price_set": {
                            "shop_money": {
                                "amount": "4.50",
                                "currency_code": "USD"
                            },
                            "presentment_money": {
                                "amount": "4.50",
                                "currency_code": "USD"
                            }
                        }
                    }
                ]
            }
        ],
        "fulfillments": [],
        "refunds": [],
        "payment_terms": None,
        "discount_codes": [],
        "tax_lines": [
            {
                "title": "US Sales Tax",
                "price": "4.50",
                "rate": 0.09,
                "price_set": {
                    "shop_money": {
                        "amount": "4.50",
                        "currency_code": "USD"
                    },
                    "presentment_money": {
                        "amount": "4.50",
                        "currency_code": "USD"
                    }
                }
            }
        ],
        "admin_graphql_api_id": "gid://shopify/Order/4712999999999"
    }
    
    payload_json = json.dumps(payload, separators=(',', ':')).encode('utf-8')
    hmac_sig = generate_hmac(payload_json, secret)
    
    headers = {
        'X-Shopify-Topic': topic,
        'X-Shopify-Hmac-Sha256': hmac_sig,
        'X-Shopify-Webhook-Id': f"{topic}:{order_id}",
        'X-Shopify-Order-Id': order_id,
        'Content-Type': 'application/json',
    }
    
    print(f"\n{'='*70}")
    print(f"Testing Webhook Delivery")
    print(f"{'='*70}")
    print(f"URL:       {url}")
    print(f"Topic:     {topic}")
    print(f"Order ID:  {order_id}")
    print(f"HMAC:      {hmac_sig[:20]}...")
    print(f"Payload:   {len(payload_json)} bytes")
    print(f"{'='*70}\n")
    
    try:
        if skip_verify:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        response = requests.post(
            url,
            data=payload_json,
            headers=headers,
            verify=not skip_verify,
            timeout=10
        )
        
        status_code = response.status_code
        response_data = {}
        try:
            response_data = response.json()
        except:
            response_data = {"text": response.text[:200]}
        
        print(f"Status:    {status_code}")
        print(f"Response:  {json.dumps(response_data, indent=2)}")
        
        if status_code == 202:
            print(f"\n✅ WEBHOOK ACCEPTED (202)")
            print(f"   Order should be queued for processing")
        elif status_code == 200:
            print(f"\n✅ WEBHOOK PROCESSED (200)")
            print(f"   Order processed synchronously")
        elif status_code == 401:
            print(f"\n❌ AUTHENTICATION FAILED (401)")
            print(f"   Check SHOPIFY_API_SECRET on Railway or local .env")
        elif status_code == 400:
            print(f"\n❌ BAD REQUEST (400)")
            print(f"   Check payload format and required fields")
        else:
            print(f"\n⚠️  UNEXPECTED STATUS ({status_code})")
        
        return status_code, response_data
        
    except requests.exceptions.RequestException as e:
        print(f"❌ REQUEST FAILED")
        print(f"   Error: {e}")
        return None, {"error": str(e)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test Shopify webhook delivery")
    parser.add_argument("--url", required=True, help="Webhook endpoint URL")
    parser.add_argument("--secret", required=True, help="Shopify webhook signing secret")
    parser.add_argument("--topic", default="orders/create", help="Webhook topic")
    parser.add_argument("--order-id", default="4712999999999", help="Shopify order ID")
    parser.add_argument("--skip-verify", action="store_true", help="Skip SSL verification (for self-signed certs)")
    
    args = parser.parse_args()
    
    status, response = send_webhook_test(
        url=args.url,
        secret=args.secret,
        topic=args.topic,
        order_id=args.order_id,
        skip_verify=args.skip_verify
    )
