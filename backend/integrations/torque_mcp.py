# Torque MCP integration — exposes JellyNet marketplace as discoverable MCP tools
from __future__ import annotations

import os
from typing import Any

TORQUE_MCP_ENDPOINT = os.environ.get("TORQUE_MCP_ENDPOINT", "https://mcp.torque.so")

# MCP tool manifest: each entry follows the MCP tool spec (name, description, inputSchema, outputSchema)
JELLYNET_MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "list_models",
        "description": (
            "List all AI model providers available through JellyNet's marketplace. "
            "Returns protocol slugs, display names, supported endpoints, and pricing tiers."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "enum": ["llm", "image", "embedding", "all"],
                    "description": "Filter by model category. Defaults to 'all'.",
                },
                "active_only": {
                    "type": "boolean",
                    "description": "Return only protocols with live supplier keys. Defaults to true.",
                },
            },
            "required": [],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "protocols": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "slug": {"type": "string"},
                            "name": {"type": "string"},
                            "category": {"type": "string"},
                            "base_url": {"type": "string"},
                            "price_per_1k_tokens_usd": {"type": "number"},
                        },
                    },
                }
            },
        },
    },
    {
        "name": "get_pricing",
        "description": (
            "Return current per-call pricing for a specific JellyNet protocol. "
            "Price is denominated in USDC and reflects the live pool rate."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "protocol_slug": {
                    "type": "string",
                    "description": "Protocol identifier, e.g. 'openai-gpt4o' or 'anthropic-claude-sonnet'.",
                }
            },
            "required": ["protocol_slug"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "protocol_slug": {"type": "string"},
                "price_per_1k_input_tokens_usd": {"type": "number"},
                "price_per_1k_output_tokens_usd": {"type": "number"},
                "x402_payment_required": {"type": "boolean"},
                "solana_usdc_address": {"type": "string"},
            },
        },
    },
    {
        "name": "call_llm",
        "description": (
            "Route an LLM completion request through JellyNet's universal proxy. "
            "Automatically selects the cheapest available supplier key for the given protocol. "
            "Payment is deducted via x402 from the agent's prepaid balance."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "protocol_slug": {
                    "type": "string",
                    "description": "Target protocol, e.g. 'openai-gpt4o'.",
                },
                "messages": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "role": {"type": "string", "enum": ["system", "user", "assistant"]},
                            "content": {"type": "string"},
                        },
                    },
                    "description": "OpenAI-compatible messages array.",
                },
                "max_tokens": {"type": "integer", "description": "Max tokens to generate."},
                "jellynet_api_key": {
                    "type": "string",
                    "description": "Buyer's JellyNet API key for routing and billing.",
                },
            },
            "required": ["protocol_slug", "messages", "jellynet_api_key"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "choices": {"type": "array"},
                "usage": {"type": "object"},
                "jellynet_charge_usd": {"type": "number"},
                "supplier_wallet": {"type": "string"},
            },
        },
    },
    {
        "name": "pay_x402",
        "description": (
            "Initiate an x402 micropayment on Solana to fund a JellyNet API call. "
            "Returns a payment payload the agent signs with its wallet before the proxy processes the request."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "amount_usd": {
                    "type": "number",
                    "description": "Amount to pay in USD (converted to USDC-SPL on-chain).",
                },
                "recipient_wallet": {
                    "type": "string",
                    "description": "JellyNet escrow wallet address on Solana.",
                },
                "agent_wallet": {
                    "type": "string",
                    "description": "Payer's Solana wallet address.",
                },
                "call_reference": {
                    "type": "string",
                    "description": "Unique reference ID tying the payment to a pending API call.",
                },
            },
            "required": ["amount_usd", "recipient_wallet", "agent_wallet", "call_reference"],
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "payment_payload_b64": {"type": "string"},
                "expires_at": {"type": "string", "format": "date-time"},
                "instructions": {"type": "string"},
            },
        },
    },
]


def get_tool_manifest() -> dict[str, Any]:
    """Return the full MCP tool manifest for JellyNet's Torque registration."""
    return {
        "server": TORQUE_MCP_ENDPOINT,
        "tools": JELLYNET_MCP_TOOLS,
    }


def get_tool(name: str) -> dict[str, Any] | None:
    """Look up a single tool definition by name."""
    return next((t for t in JELLYNET_MCP_TOOLS if t["name"] == name), None)
