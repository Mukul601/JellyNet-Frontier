# SNS integration — human-readable .sol identities for suppliers in the marketplace
"""
Suppliers register their .sol name on the JellyNet marketplace. Buyers see `alice.sol`
instead of raw wallet addresses when browsing available providers. The public supplier
leaderboard uses .sol names for top earners.
"""

import re
import os
from typing import Optional
import httpx

SNS_REGISTRY_PROGRAM_ID = "namesLPneVptA9Z5rqUDD9tMTWEJwofgaYwp8cawRkX"
SOL_TLD_CLASS = "58PwtjSDuFHuUkYjH9BYnnQKHfwo9reZhC2zMJv9JPkx"
SNS_RPC_URL = os.getenv("SNS_RPC_URL", "https://api.mainnet-beta.solana.com")

_SOL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9\-]{0,61}[a-z0-9]?\.sol$")


class SNSResolver:
    def __init__(self, rpc_url: str = SNS_RPC_URL):
        self.rpc_url = rpc_url
        self._client: Optional[httpx.AsyncClient] = None

    async def _client_(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def resolve_name(self, sol_name: str) -> Optional[str]:
        """Resolve a .sol domain name to a wallet address via SNS RPC."""
        if not self.validate_sol_name(sol_name):
            return None
        try:
            client = await self._client_()
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getNameRecord",
                "params": [sol_name, SNS_REGISTRY_PROGRAM_ID, SOL_TLD_CLASS],
            }
            resp = await client.post(self.rpc_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", {}).get("owner")
        except Exception:
            return None

    async def reverse_resolve(self, wallet_address: str) -> Optional[str]:
        """Look up the .sol name registered to a wallet address."""
        try:
            client = await self._client_()
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "reverseNameLookup",
                "params": [wallet_address, SNS_REGISTRY_PROGRAM_ID, SOL_TLD_CLASS],
            }
            resp = await client.post(self.rpc_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("result", {}).get("name")
        except Exception:
            return None

    async def get_supplier_display_name(
        self, wallet_address: str, fallback_truncate: bool = True
    ) -> str:
        """Return .sol name for a wallet if available, else a truncated address."""
        sol_name = await self.reverse_resolve(wallet_address)
        if sol_name:
            return sol_name
        if fallback_truncate and len(wallet_address) >= 8:
            return f"{wallet_address[:4]}...{wallet_address[-4:]}"
        return wallet_address

    async def batch_resolve_suppliers(self, wallet_addresses: list) -> dict:
        """Resolve multiple supplier wallet addresses to .sol names in parallel.

        Returns a dict mapping each address to its display name (.sol or truncated).
        """
        import asyncio

        async def _resolve_one(addr: str):
            return addr, await self.get_supplier_display_name(addr)

        results = await asyncio.gather(*[_resolve_one(addr) for addr in wallet_addresses])
        return dict(results)

    @staticmethod
    def validate_sol_name(name: str) -> bool:
        """Validate that a string is a properly formatted .sol domain name."""
        if not isinstance(name, str):
            return False
        return bool(_SOL_NAME_RE.match(name.lower()))
