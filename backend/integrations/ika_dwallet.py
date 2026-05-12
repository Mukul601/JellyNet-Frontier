# Ika dWallet integration — bridgeless cross-chain supplier onboarding and agent spending policies
"""
JellyNet uses Ika dWallets so suppliers on other chains can participate without bridging.
A supplier with USDC on Ethereum receives epoch payouts through a dWallet controlled from
Solana. For AI agents, the dWallet enforces spending policies — an agent can only spend up
to X USDC per epoch on API calls.
"""

# NOTE: Ika is currently on devnet pre-alpha. These interfaces are built against the
# expected mainnet SDK and will activate when Ika launches on mainnet.

import os
from typing import Optional

IKA_PROGRAM_ID = "ikaXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"  # placeholder - replace when mainnet launches
SUPPORTED_CHAINS = ["ethereum", "base", "bitcoin", "polygon"]


class IkaDWallet:
    def __init__(self, program_id: str = IKA_PROGRAM_ID):
        self.program_id = program_id
        self.rpc_url = os.getenv("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")

    async def create_supplier_dwallet(
        self, supplier_pubkey: str, source_chain: str
    ) -> dict:
        """Create a dWallet for a supplier who holds assets on another chain.

        Returns dWallet address and setup instructions. The dWallet is controlled
        from Solana but can hold and move assets on the source_chain.
        """
        if source_chain not in SUPPORTED_CHAINS:
            return {
                "success": False,
                "error": f"Unsupported chain: {source_chain}. Supported: {SUPPORTED_CHAINS}",
            }
        # Stub: returns expected response shape for when Ika mainnet SDK is available
        return {
            "success": True,
            "dwallet_address": f"ika_{supplier_pubkey[:8]}_dwallet_placeholder",
            "source_chain": source_chain,
            "controller_pubkey": supplier_pubkey,
            "program_id": self.program_id,
            "setup_instructions": [
                f"1. Connect your {source_chain} wallet to JellyNet",
                "2. Sign the dWallet creation transaction on Solana",
                f"3. Authorize the dWallet to receive payouts on {source_chain}",
                "4. Your dWallet is now active — JellyNet will route epoch payouts to it",
            ],
            "status": "pending_mainnet",
        }

    async def set_agent_spending_policy(
        self,
        dwallet_address: str,
        max_spend_per_epoch: float,
        allowed_tokens: list,
    ) -> dict:
        """Configure spending limits for an AI agent's dWallet.

        Limits are enforced on Solana even if the agent's funds live on another chain.
        """
        if max_spend_per_epoch <= 0:
            return {"success": False, "error": "max_spend_per_epoch must be positive"}
        return {
            "success": True,
            "dwallet_address": dwallet_address,
            "policy": {
                "max_spend_per_epoch_usd": max_spend_per_epoch,
                "allowed_tokens": allowed_tokens,
                "enforcement": "solana_program",
                "program_id": self.program_id,
            },
            "status": "pending_mainnet",
        }

    async def initiate_cross_chain_payout(
        self,
        dwallet_address: str,
        amount: float,
        destination_chain: str,
        destination_address: str,
    ) -> dict:
        """Initiate a payout from JellyNet's settlement to a supplier on another chain.

        Uses the dWallet to move funds without requiring the supplier to bridge manually.
        """
        if destination_chain not in SUPPORTED_CHAINS:
            return {
                "success": False,
                "error": f"Unsupported destination chain: {destination_chain}",
            }
        if amount <= 0:
            return {"success": False, "error": "Payout amount must be positive"}
        return {
            "success": True,
            "dwallet_address": dwallet_address,
            "payout": {
                "amount_usd": amount,
                "destination_chain": destination_chain,
                "destination_address": destination_address,
                "estimated_arrival": "5-15 minutes after mainnet launch",
            },
            "tx_id": f"ika_payout_{dwallet_address[:8]}_placeholder",
            "status": "pending_mainnet",
        }

    async def get_dwallet_status(self, dwallet_address: str) -> dict:
        """Check dWallet state including linked chains and current policies."""
        return {
            "dwallet_address": dwallet_address,
            "linked_chains": [],
            "active_policies": [],
            "balance_usd": 0.0,
            "status": "pending_mainnet",
            "note": "Ika dWallet state will populate when mainnet SDK is available",
        }
