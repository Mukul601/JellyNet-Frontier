# QuickNode RPC integration — high-performance Solana RPC for x402 payment verification and epoch settlement

import os
import httpx
from typing import Optional, Dict, Any

QUICKNODE_ENDPOINT = os.environ.get("QUICKNODE_SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")


class QuickNodeRPC:
    """
    Wraps Solana JSON-RPC calls through a QuickNode endpoint.

    JellyNet uses this for:
    - x402 payment verification: confirming USDC-SPL transfers before proxying API calls
    - Epoch settlement: batching USDC-SPL payouts to suppliers
    - Wallet balance checks: verifying agent/buyer USDC balances during wallet connect

    QuickNode's higher rate limits and lower latency (~500ms vs ~2s on public RPC)
    directly improve x402 payment verification speed.
    """

    def __init__(self, endpoint: Optional[str] = None):
        self.endpoint = endpoint or QUICKNODE_ENDPOINT
        self.client = httpx.AsyncClient(timeout=10.0)

    async def _rpc_call(self, method: str, params: list = None) -> Dict[str, Any]:
        """Execute a JSON-RPC call against the QuickNode Solana endpoint."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or [],
        }
        response = await self.client.post(self.endpoint, json=payload)
        response.raise_for_status()
        result = response.json()
        if "error" in result:
            raise Exception(f"RPC error: {result['error']}")
        return result.get("result")

    async def verify_x402_payment(self, tx_signature: str) -> Dict[str, Any]:
        """
        Verify an x402 USDC-SPL payment transaction on Solana.
        Called before proxying an API call for agent payments.
        Returns transaction details including confirmation status and token transfer amounts.
        """
        result = await self._rpc_call(
            "getTransaction",
            [tx_signature, {"encoding": "jsonParsed", "commitment": "confirmed"}],
        )
        if not result:
            return {"verified": False, "reason": "transaction_not_found"}

        meta = result.get("meta", {})
        if meta.get("err"):
            return {"verified": False, "reason": "transaction_failed", "error": meta["err"]}

        return {
            "verified": True,
            "slot": result.get("slot"),
            "block_time": result.get("blockTime"),
            "fee": meta.get("fee", 0),
            "pre_balances": meta.get("preTokenBalances", []),
            "post_balances": meta.get("postTokenBalances", []),
        }

    async def get_usdc_balance(
        self,
        wallet_address: str,
        usdc_mint: str = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    ) -> float:
        """
        Get USDC-SPL balance for a wallet address.
        Used during wallet connect and before epoch settlement.
        Default mint is USDC on Solana mainnet.
        """
        result = await self._rpc_call(
            "getTokenAccountsByOwner",
            [wallet_address, {"mint": usdc_mint}, {"encoding": "jsonParsed"}],
        )

        if not result or not result.get("value"):
            return 0.0

        total = 0.0
        for account in result["value"]:
            token_amount = (
                account.get("account", {})
                .get("data", {})
                .get("parsed", {})
                .get("info", {})
                .get("tokenAmount", {})
            )
            total += float(token_amount.get("uiAmount", 0))
        return total

    async def get_recent_blockhash(self) -> str:
        """Get recent blockhash for constructing settlement transactions."""
        result = await self._rpc_call("getLatestBlockhash", [{"commitment": "finalized"}])
        return result.get("value", {}).get("blockhash", "")

    async def send_settlement_transaction(self, signed_tx: str) -> str:
        """
        Submit a signed USDC-SPL settlement transaction.
        Used by the epoch worker to batch supplier payouts.
        Returns transaction signature.
        """
        result = await self._rpc_call(
            "sendTransaction",
            [signed_tx, {"encoding": "base64", "skipPreflight": False, "preflightCommitment": "confirmed"}],
        )
        return result

    async def get_transaction_status(self, tx_signature: str) -> Dict[str, Any]:
        """Check confirmation status of a settlement transaction."""
        result = await self._rpc_call("getSignatureStatuses", [[tx_signature]])
        if result and result.get("value") and result["value"][0]:
            status = result["value"][0]
            return {
                "confirmed": status.get("confirmationStatus") in ("confirmed", "finalized"),
                "status": status.get("confirmationStatus"),
                "slot": status.get("slot"),
                "error": status.get("err"),
            }
        return {"confirmed": False, "status": "unknown"}

    async def close(self):
        """Clean up HTTP client."""
        await self.client.aclose()
