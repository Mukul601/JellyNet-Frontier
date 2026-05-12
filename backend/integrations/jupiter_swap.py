# Jupiter Swap API integration — stablecoin conversions for settlement and deposits
from __future__ import annotations

import os
from typing import Any

import httpx

from .usdt_spl import StablecoinManager

SOL_MINT = "So11111111111111111111111111111111111111112"


class JupiterSwap:
    def __init__(self) -> None:
        self._api_url = os.environ.get("JUPITER_API_URL", "https://quote-api.jup.ag/v6")
        self._client = httpx.AsyncClient(
            base_url=self._api_url,
            headers={"Content-Type": "application/json"},
            timeout=30.0,
        )

    async def get_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int = 50,
    ) -> dict[str, Any]:
        """Gets a swap quote from Jupiter. Default slippage is 0.5% (50 bps)."""
        params = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount),
            "slippageBps": str(slippage_bps),
        }
        resp = await self._client.get("/quote", params=params)
        resp.raise_for_status()
        return resp.json()

    async def execute_swap(
        self,
        quote_response: dict[str, Any],
        user_public_key: str,
    ) -> dict[str, Any]:
        """
        Executes a swap transaction using an existing quote.
        Returns a serialized transaction ready for client-side signing.
        """
        payload = {
            "quoteResponse": quote_response,
            "userPublicKey": user_public_key,
            "wrapAndUnwrapSol": True,
        }
        resp = await self._client.post("/swap", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return {
            "swap_transaction": data.get("swapTransaction"),
            "last_valid_block_height": data.get("lastValidBlockHeight"),
        }

    async def convert_stablecoin(
        self,
        from_token: str,
        to_token: str,
        amount: float,
    ) -> dict[str, Any]:
        """
        Convenience method: gets quote + prepares swap between USDC and USDT.
        `amount` is human-readable (e.g. 10.5 for $10.50).
        """
        input_mint = StablecoinManager.get_mint_address(from_token)
        output_mint = StablecoinManager.get_mint_address(to_token)
        raw_amount = StablecoinManager.to_raw_amount(amount, from_token)

        quote = await self.get_quote(input_mint, output_mint, raw_amount)
        out_amount = int(quote.get("outAmount", 0))

        return {
            "from_token": from_token.upper(),
            "to_token": to_token.upper(),
            "input_amount": amount,
            "output_amount": StablecoinManager.format_amount(out_amount, to_token),
            "quote": quote,
        }

    async def convert_sol_to_usdc(
        self,
        sol_amount: float,
        user_public_key: str,
    ) -> dict[str, Any]:
        """
        Converts SOL deposits to USDC for buyers who deposit native SOL.
        sol_amount is in SOL (e.g. 0.1 for 0.1 SOL).
        """
        usdc_mint = StablecoinManager.get_mint_address("USDC")
        raw_lamports = int(sol_amount * 1_000_000_000)

        quote = await self.get_quote(SOL_MINT, usdc_mint, raw_lamports)
        swap = await self.execute_swap(quote, user_public_key)

        out_amount = int(quote.get("outAmount", 0))
        return {
            "sol_input": sol_amount,
            "usdc_output": StablecoinManager.format_amount(out_amount, "USDC"),
            "swap_transaction": swap.get("swap_transaction"),
            "last_valid_block_height": swap.get("last_valid_block_height"),
        }

    async def close(self) -> None:
        await self._client.aclose()
