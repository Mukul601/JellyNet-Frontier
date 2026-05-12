# LPAgent.io API integration — DeFi analytics context for AI agents
from __future__ import annotations

import os
from typing import Any

import httpx

LPAGENT_API_KEY = os.environ.get("LPAGENT_API_KEY")
LPAGENT_BASE_URL = "https://api.lpagent.io/v1"


def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if LPAGENT_API_KEY:
        headers["Authorization"] = f"Bearer {LPAGENT_API_KEY}"
    return headers


async def get_lp_positions(wallet_address: str) -> dict[str, Any]:
    """Fetch all active LP positions for a wallet across supported DeFi protocols."""
    async with httpx.AsyncClient(base_url=LPAGENT_BASE_URL, timeout=10) as client:
        resp = await client.get(
            "/positions",
            params={"wallet": wallet_address},
            headers=_headers(),
        )
        resp.raise_for_status()
        data = resp.json()

    return {
        "ok": True,
        "wallet": wallet_address,
        "positions": data.get("positions", []),
        "total_value_usd": data.get("total_value_usd", 0.0),
        "position_count": len(data.get("positions", [])),
    }


async def get_yield_analytics(protocol_slug: str) -> dict[str, Any]:
    """Fetch current APY, TVL, and fee data for a given DeFi protocol."""
    async with httpx.AsyncClient(base_url=LPAGENT_BASE_URL, timeout=10) as client:
        resp = await client.get(
            f"/protocols/{protocol_slug}/yield",
            headers=_headers(),
        )
        resp.raise_for_status()
        data = resp.json()

    return {
        "ok": True,
        "protocol": protocol_slug,
        "apy_7d": data.get("apy_7d"),
        "apy_30d": data.get("apy_30d"),
        "tvl_usd": data.get("tvl_usd"),
        "fee_tier": data.get("fee_tier"),
        "chain": data.get("chain"),
    }


async def agent_portfolio_context(wallet_address: str) -> dict[str, Any]:
    """Build a combined financial context object an AI agent can use for decision-making.

    Merges LP position data with per-protocol yield analytics into a single payload.
    Used by JellyNet agents to assess supplier financial health and route payments.
    """
    positions_data = await get_lp_positions(wallet_address)

    protocol_slugs: list[str] = list(
        {p.get("protocol") for p in positions_data.get("positions", []) if p.get("protocol")}
    )

    yield_map: dict[str, Any] = {}
    for slug in protocol_slugs:
        try:
            yield_data = await get_yield_analytics(slug)
            yield_map[slug] = yield_data
        except httpx.HTTPError:
            yield_map[slug] = {"ok": False, "error": "fetch_failed"}

    return {
        "ok": True,
        "wallet": wallet_address,
        "total_lp_value_usd": positions_data.get("total_value_usd", 0.0),
        "active_positions": positions_data.get("positions", []),
        "yield_by_protocol": yield_map,
        "summary": {
            "position_count": positions_data.get("position_count", 0),
            "protocols_active": protocol_slugs,
        },
    }
