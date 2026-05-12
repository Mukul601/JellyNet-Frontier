# Dodo Payments integration — fiat billing and usage-based credit metering for human buyers
from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any

import httpx


class DodoPayments:
    def __init__(self) -> None:
        self._api_key = os.environ.get("DODO_API_KEY", "")
        self._base_url = os.environ.get("DODO_BASE_URL", "https://api.dodopayments.com")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def create_credit_purchase(
        self,
        customer_id: str,
        credit_amount: int,
        price_cents: int,
    ) -> dict[str, Any]:
        """Creates a one-time payment for API credits. Returns checkout URL."""
        payload = {
            "customer_id": customer_id,
            "amount": price_cents,
            "currency": "USD",
            "metadata": {
                "credit_amount": credit_amount,
                "product": "jellynet_api_credits",
            },
            "line_items": [
                {
                    "name": f"JellyNet API Credits ({credit_amount})",
                    "quantity": 1,
                    "unit_amount": price_cents,
                }
            ],
        }
        resp = await self._client.post("/v1/payments", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return {
            "payment_id": data.get("id"),
            "checkout_url": data.get("checkout_url"),
            "status": data.get("status"),
        }

    async def record_usage(
        self,
        customer_id: str,
        calls_made: int,
        credits_consumed: int,
    ) -> dict[str, Any]:
        """Reports API usage to Dodo's metering system."""
        payload = {
            "customer_id": customer_id,
            "events": [
                {
                    "event_name": "api_call",
                    "quantity": calls_made,
                    "properties": {"credits_consumed": credits_consumed},
                }
            ],
        }
        resp = await self._client.post("/v1/metering/events", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def get_customer_balance(self, customer_id: str) -> dict[str, Any]:
        """Gets remaining credit balance for a customer."""
        resp = await self._client.get(f"/v1/customers/{customer_id}/balance")
        resp.raise_for_status()
        data = resp.json()
        return {
            "customer_id": customer_id,
            "credits_remaining": data.get("credits_remaining", 0),
            "credits_used": data.get("credits_used", 0),
        }

    async def handle_webhook(
        self,
        payload: dict[str, Any],
        signature: str,
    ) -> dict[str, Any]:
        """
        Processes Dodo webhook events.
        - payment.succeeded → fulfill credits for customer
        - payment.failed → notify customer of failure
        """
        webhook_secret = os.environ.get("DODO_WEBHOOK_SECRET", "")
        if webhook_secret:
            expected = hmac.new(
                webhook_secret.encode(),
                str(payload).encode(),
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(expected, signature):
                return {"ok": False, "error": "invalid_signature"}

        event_type = payload.get("type")

        if event_type == "payment.succeeded":
            payment = payload.get("data", {})
            credit_amount = payment.get("metadata", {}).get("credit_amount", 0)
            return {
                "ok": True,
                "action": "fulfill_credits",
                "customer_id": payment.get("customer_id"),
                "credits_to_grant": credit_amount,
                "payment_id": payment.get("id"),
            }

        if event_type == "payment.failed":
            payment = payload.get("data", {})
            return {
                "ok": True,
                "action": "notify_failure",
                "customer_id": payment.get("customer_id"),
                "payment_id": payment.get("id"),
                "reason": payment.get("failure_reason"),
            }

        return {"ok": True, "action": "ignored", "event_type": event_type}

    async def close(self) -> None:
        await self._client.aclose()
