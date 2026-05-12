# Zerion CLI integration — on-chain wallet analysis for x402 payment verification
from __future__ import annotations

import json
import os
import subprocess
from typing import Any

ZERION_API_KEY = os.environ.get("ZERION_API_KEY")


def _run_zerion(args: list[str]) -> dict[str, Any]:
    """Execute a zerion-cli command and return parsed JSON output."""
    cmd = ["zerion-cli", "--output", "json"]
    if ZERION_API_KEY:
        cmd += ["--api-key", ZERION_API_KEY]
    cmd += args

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    if result.returncode != 0:
        return {"error": result.stderr.strip(), "ok": False}

    return json.loads(result.stdout)


def check_agent_wallet_balance(wallet_address: str) -> dict[str, Any]:
    """Check USDC-SPL balance for an agent wallet before processing an x402 payment.

    Returns balance in USDC units plus token account metadata.
    """
    raw = _run_zerion(["wallet", "tokens", wallet_address, "--chain", "solana"])

    if raw.get("error"):
        return {"ok": False, "error": raw["error"], "wallet": wallet_address}

    tokens: list[dict] = raw.get("data", [])
    usdc = next(
        (t for t in tokens if t.get("symbol", "").upper() in ("USDC", "USDC-SPL")),
        None,
    )

    return {
        "ok": True,
        "wallet": wallet_address,
        "usdc_balance": float(usdc["quantity"]["float"]) if usdc else 0.0,
        "usdc_token_account": usdc.get("address") if usdc else None,
        "raw_tokens": tokens,
    }


def verify_payment_status(tx_signature: str) -> dict[str, Any]:
    """Verify that a Solana transaction (x402 payment) has been confirmed on-chain.

    Returns confirmation status, block time, and transfer amount.
    """
    raw = _run_zerion(["transaction", "get", tx_signature, "--chain", "solana"])

    if raw.get("error"):
        return {"ok": False, "error": raw["error"], "tx_signature": tx_signature}

    tx = raw.get("data", {})
    return {
        "ok": True,
        "tx_signature": tx_signature,
        "confirmed": tx.get("status") == "confirmed",
        "block_time": tx.get("mined_at"),
        "fee_usd": tx.get("fee", {}).get("value"),
        "transfers": tx.get("transfers", []),
    }


def get_supplier_portfolio(wallet_address: str) -> dict[str, Any]:
    """Fetch a supplier's full on-chain portfolio for admin analytics and payout tracking.

    Combines token balances and recent transaction summary from Zerion.
    """
    tokens_raw = _run_zerion(["wallet", "tokens", wallet_address, "--chain", "solana"])
    txns_raw = _run_zerion(
        ["wallet", "transactions", wallet_address, "--chain", "solana", "--limit", "20"]
    )

    tokens = tokens_raw.get("data", []) if not tokens_raw.get("error") else []
    transactions = txns_raw.get("data", []) if not txns_raw.get("error") else []

    total_usd = sum(
        float(t.get("value", {}).get("usd", 0)) for t in tokens
    )

    return {
        "ok": True,
        "wallet": wallet_address,
        "total_portfolio_usd": total_usd,
        "token_count": len(tokens),
        "tokens": tokens,
        "recent_transactions": transactions,
    }
