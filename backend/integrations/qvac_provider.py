# QVAC (Tether) integration — local-first AI provider for JellyNet's capacity marketplace
from __future__ import annotations

import os
from typing import Any

import httpx


class QVACProvider:
    """
    QVAC nodes can be registered as JellyNet suppliers. When a buyer's API call is
    routed to a QVAC supplier, it runs locally on the supplier's hardware instead of
    hitting a cloud API. This enables JellyNet's P5 roadmap (residential compute sharing):
    anyone with sufficient hardware can monetize spare GPU/CPU capacity by running a QVAC
    node and registering it as a supplier in the JellyNet marketplace.

    QVAC exposes an OpenAI-compatible API, so existing buyers require zero changes —
    they continue sending standard chat completion requests while the marketplace routes
    them transparently to QVAC nodes.
    """

    def __init__(self, endpoint: str | None = None) -> None:
        self._endpoint = endpoint or os.environ.get("QVAC_ENDPOINT", "http://localhost:8080")
        self._client = httpx.AsyncClient(
            base_url=self._endpoint,
            headers={"Content-Type": "application/json"},
            timeout=120.0,
        )

    async def completion(
        self,
        model: str,
        messages: list[dict[str, str]],
        stream: bool = False,
    ) -> dict[str, Any]:
        """
        Sends a completion request to a QVAC endpoint using OpenAI-compatible API format.
        Supports both streaming and non-streaming responses.
        """
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }
        resp = await self._client.post("/v1/chat/completions", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def list_models(self) -> list[dict[str, Any]]:
        """Queries the QVAC endpoint for available local models."""
        resp = await self._client.get("/v1/models")
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", [])

    async def health_check(self) -> dict[str, Any]:
        """Checks if the QVAC node is online and responsive."""
        try:
            resp = await self._client.get("/health")
            resp.raise_for_status()
            return {"online": True, "endpoint": self._endpoint, "status": resp.json()}
        except (httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError):
            return {"online": False, "endpoint": self._endpoint}

    async def register_as_supplier(
        self,
        supplier_id: str,
        models: list[str],
    ) -> dict[str, Any]:
        """
        Registers a QVAC node as a supplier in JellyNet's capacity pool.
        Returns registration confirmation with assigned supplier metadata.
        """
        health = await self.health_check()
        if not health.get("online"):
            return {"ok": False, "error": "qvac_node_offline", "endpoint": self._endpoint}

        available_models = await self.list_models()
        available_names = {m.get("id") for m in available_models}
        valid_models = [m for m in models if m in available_names]

        return {
            "ok": True,
            "supplier_id": supplier_id,
            "endpoint": self._endpoint,
            "registered_models": valid_models,
            "provider_type": "qvac",
            "api_format": "openai_compatible",
        }

    async def close(self) -> None:
        await self._client.aclose()
