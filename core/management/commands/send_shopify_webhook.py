from __future__ import annotations

import base64
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Send a signed Shopify-style webhook payload to the local BoldERP endpoint."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument("topic", help="Shopify topic, for example orders/create")
        parser.add_argument("payload_path", help="Path to a JSON payload fixture")
        parser.add_argument(
            "--base-url",
            default="http://127.0.0.1:8000",
            help="Base URL where the Django server is running.",
        )
        parser.add_argument(
            "--webhook-id",
            default="",
            help="Optional fixed X-Shopify-Webhook-Id for idempotency testing.",
        )
        parser.add_argument(
            "--timeout",
            type=float,
            default=15.0,
            help="HTTP timeout in seconds.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        payload_path = Path(options["payload_path"]).expanduser().resolve()
        if not payload_path.exists():
            raise CommandError(f"Payload file not found: {payload_path}")

        secret = getattr(settings, "SHOPIFY_API_SECRET", "") or getattr(settings, "SHOPIFY_WEBHOOK_SECRET", "")
        if not secret:
            raise CommandError("SHOPIFY_API_SECRET or SHOPIFY_WEBHOOK_SECRET must be configured.")

        raw_body = payload_path.read_text(encoding="utf-8")
        payload = json.loads(raw_body)
        topic = str(options["topic"]).strip()
        webhook_id = str(options["webhook_id"] or self._default_webhook_id(topic, payload, payload_path)).strip()
        order_id = str(payload.get("id") or payload.get("order_id") or "").strip()
        signature = self._build_hmac(secret, raw_body.encode("utf-8"))
        endpoint = options["base_url"].rstrip("/") + "/webhooks/shopify/"

        headers = {
            "Content-Type": "application/json",
            "X-Shopify-Topic": topic,
            "X-Shopify-Hmac-Sha256": signature,
            "X-Shopify-Webhook-Id": webhook_id,
        }
        if order_id:
            headers["X-Shopify-Order-Id"] = order_id

        with httpx.Client(timeout=float(options["timeout"])) as client:
            response = client.post(endpoint, content=raw_body.encode("utf-8"), headers=headers)

        self.stdout.write(f"POST {endpoint}")
        self.stdout.write(f"Topic: {topic}")
        self.stdout.write(f"Webhook ID: {webhook_id}")
        self.stdout.write(f"Status: {response.status_code}")
        self.stdout.write(response.text)

        if response.is_error:
            raise CommandError(f"Webhook request failed with status {response.status_code}.")

    @staticmethod
    def _build_hmac(secret: str, raw_body: bytes) -> str:
        digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
        return base64.b64encode(digest).decode("utf-8")

    @staticmethod
    def _default_webhook_id(topic: str, payload: dict[str, Any], payload_path: Path) -> str:
        identifier = str(payload.get("id") or payload.get("order_id") or payload.get("name") or payload_path.stem).strip()
        return f"{topic}:{identifier}"
