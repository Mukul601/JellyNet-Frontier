# USDT-SPL integration — Tether stablecoin support for x402 payments and supplier payouts
from __future__ import annotations

import json
from typing import Any

USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

SUPPORTED_STABLECOINS: dict[str, dict[str, Any]] = {
    "USDC": {
        "mint": USDC_MINT,
        "decimals": 6,
        "name": "USD Coin",
    },
    "USDT": {
        "mint": USDT_MINT,
        "decimals": 6,
        "name": "Tether USD",
    },
}

_MINT_TO_SYMBOL: dict[str, str] = {v["mint"]: k for k, v in SUPPORTED_STABLECOINS.items()}


class StablecoinManager:
    @staticmethod
    def get_mint_address(token: str) -> str:
        """Returns the SPL mint address for USDC or USDT."""
        entry = SUPPORTED_STABLECOINS.get(token.upper())
        if not entry:
            raise ValueError(f"Unsupported stablecoin: {token}. Supported: {list(SUPPORTED_STABLECOINS)}")
        return entry["mint"]

    @staticmethod
    def detect_token_from_mint(mint_address: str) -> str | None:
        """Identifies which stablecoin a mint address belongs to. Returns None if unknown."""
        return _MINT_TO_SYMBOL.get(mint_address)

    @staticmethod
    def validate_x402_payment_token(payment_header: str) -> dict[str, Any]:
        """
        Validates that an x402 payment header uses a supported stablecoin.
        Returns validation result with detected token info.
        """
        try:
            payload = json.loads(payment_header) if isinstance(payment_header, str) else payment_header
        except (json.JSONDecodeError, TypeError):
            return {"valid": False, "error": "invalid_payment_header"}

        mint = payload.get("token") or payload.get("mint") or payload.get("token_mint")
        if not mint:
            return {"valid": False, "error": "missing_token_mint"}

        symbol = StablecoinManager.detect_token_from_mint(mint)
        if not symbol:
            return {"valid": False, "error": "unsupported_token", "mint": mint}

        return {
            "valid": True,
            "token": symbol,
            "mint": mint,
            "decimals": SUPPORTED_STABLECOINS[symbol]["decimals"],
        }

    @staticmethod
    def get_supplier_payout_config(supplier_preference: str) -> dict[str, Any]:
        """Returns payout config for epoch settlement based on supplier's preferred stablecoin."""
        token = supplier_preference.upper()
        if token not in SUPPORTED_STABLECOINS:
            token = "USDC"

        info = SUPPORTED_STABLECOINS[token]
        return {
            "payout_token": token,
            "mint": info["mint"],
            "decimals": info["decimals"],
            "settlement_type": "epoch",
        }

    @staticmethod
    def format_amount(raw_amount: int, token: str) -> float:
        """Converts raw on-chain amount to human-readable amount (e.g. 1_000_000 → 1.0 USDC)."""
        info = SUPPORTED_STABLECOINS.get(token.upper())
        if not info:
            raise ValueError(f"Unsupported stablecoin: {token}")
        return raw_amount / (10 ** info["decimals"])

    @staticmethod
    def to_raw_amount(human_amount: float, token: str) -> int:
        """Converts human-readable amount to raw on-chain amount (e.g. 1.0 USDC → 1_000_000)."""
        info = SUPPORTED_STABLECOINS.get(token.upper())
        if not info:
            raise ValueError(f"Unsupported stablecoin: {token}")
        return int(human_amount * (10 ** info["decimals"]))
