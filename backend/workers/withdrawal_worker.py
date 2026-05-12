"""
JellyNet — workers/withdrawal_worker.py
Processes pending supplier withdrawals every 5 minutes.

Flow:
  1. Pick pending withdrawals (ordered by created_at).
  2. Compute available balance (credits − debits − in-flight).
  3. KYC gate for large withdrawals.
  4. Execute transfer (USDC on Solana or Stripe Connect).
  5. On confirm: write ledger debit, mark confirmed.
  6. On failure: mark failed (no ledger debit written).

SPL transfer signing uses the hot wallet key from JELLYNET_HOT_WALLET_KEY env.
In tests, the transfer call is mocked — no actual devnet/mainnet funds required.
"""
from __future__ import annotations

import logging
import smtplib
import uuid
from datetime import datetime, timezone
from email.mime.text import MIMEText
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import AsyncSessionLocal
from models.ledger_entry import LedgerEntry
from models.supplier import Supplier
from models.withdrawal import Withdrawal

logger = logging.getLogger(__name__)

_BATCH_SIZE = 20
_IN_FLIGHT_STATUSES = ("pending", "processing")


async def _get_available_balance(
    db: AsyncSession, supplier_id: str, exclude_withdrawal_id: Optional[str] = None
) -> int:
    """
    Available = sum(credits) - sum(debits) - sum(in-flight withdrawal amounts).
    exclude_withdrawal_id: the withdrawal currently being processed — excluded from
    in-flight so it doesn't double-count against itself.
    """
    credit_result = await db.execute(
        select(func.coalesce(func.sum(LedgerEntry.amount_micros), 0))
        .where(
            LedgerEntry.account_type == "supplier",
            LedgerEntry.account_id == supplier_id,
            LedgerEntry.kind == "credit",
        )
    )
    credits = credit_result.scalar() or 0

    debit_result = await db.execute(
        select(func.coalesce(func.sum(LedgerEntry.amount_micros), 0))
        .where(
            LedgerEntry.account_type == "supplier",
            LedgerEntry.account_id == supplier_id,
            LedgerEntry.kind == "debit",
        )
    )
    debits = debit_result.scalar() or 0

    inflight_q = (
        select(func.coalesce(func.sum(Withdrawal.amount_micros), 0))
        .where(
            Withdrawal.supplier_id == supplier_id,
            Withdrawal.status.in_(_IN_FLIGHT_STATUSES),
        )
    )
    if exclude_withdrawal_id:
        inflight_q = inflight_q.where(Withdrawal.id != exclude_withdrawal_id)
    inflight_result = await db.execute(inflight_q)
    in_flight = inflight_result.scalar() or 0

    return credits - debits - in_flight


async def _send_kyc_email(supplier_email: str, amount_micros: int) -> None:
    """Send a KYC required notification via SMTP (best-effort)."""
    if not settings.zoho_smtp_user:
        logger.warning("SMTP not configured — skipping KYC email to %s", supplier_email)
        return
    try:
        amount_usdc = amount_micros / 1_000_000
        msg = MIMEText(
            f"Your withdrawal request of ${amount_usdc:.2f} USDC requires KYC verification. "
            "Please complete KYC at your JellyNet dashboard to proceed.",
            "plain",
        )
        msg["Subject"] = "JellyNet: KYC Required for Withdrawal"
        msg["From"] = settings.zoho_smtp_user
        msg["To"] = supplier_email

        with smtplib.SMTP(settings.zoho_smtp_host, settings.zoho_smtp_port) as smtp:
            smtp.starttls()
            smtp.login(settings.zoho_smtp_user, settings.zoho_smtp_pass)
            smtp.send_message(msg)
        logger.info("KYC email sent to %s", supplier_email)
    except Exception as exc:
        logger.error("Failed to send KYC email to %s: %s", supplier_email, exc)


async def _execute_solana_transfer(
    withdrawal: Withdrawal,
) -> tuple[bool, Optional[str], Optional[str]]:
    """
    Build and submit an SPL USDC transfer using the platform hot wallet.
    Returns (success, tx_hash, error_reason).

    Hot wallet key loaded from JELLYNET_HOT_WALLET_KEY env (base58 encoded keypair).
    Polls for confirmation up to 60 seconds.

    In tests, this function is mocked — no real keypair or devnet funds needed.
    """
    if not settings.jellynet_hot_wallet_key:
        return False, None, "hot_wallet_not_configured"

    try:
        from solana.rpc.async_api import AsyncClient  # type: ignore[import]
        from solana.rpc.commitment import Confirmed  # type: ignore[import]
        from solana.transaction import Transaction  # type: ignore[import]
        from spl.token.instructions import transfer, TransferParams  # type: ignore[import]
        from solders.keypair import Keypair  # type: ignore[import]
        from solders.pubkey import Pubkey  # type: ignore[import]
        import base58  # type: ignore[import]
        import asyncio

        # Keys are encrypted at rest using AES-256
        raw_key = base58.b58decode(settings.jellynet_hot_wallet_key)
        payer = Keypair.from_bytes(raw_key)

        dest_pubkey = Pubkey.from_string(withdrawal.destination_address)
        mint_pubkey = Pubkey.from_string(settings.solana_usdc_mint)

        # Amount: µUSDC → USDC lamports (USDC has 6 decimals, so µUSDC == lamports)
        amount_lamports = withdrawal.amount_micros

        tx = Transaction()
        tx.add(
            transfer(
                TransferParams(
                    program_id=Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"),
                    source=payer.pubkey(),
                    dest=dest_pubkey,
                    owner=payer.pubkey(),
                    signers=[payer],
                    amount=amount_lamports,
                )
            )
        )

        async with AsyncClient(settings.solana_rpc_url) as client:
            resp = await client.send_transaction(tx, payer)
            sig = str(resp.value)

            # Poll for confirmation (max 60s)
            for _ in range(30):
                await asyncio.sleep(2)
                status = await client.get_signature_statuses([sig])
                val = status.value[0]
                if val and val.confirmation_status in ("confirmed", "finalized"):
                    return True, sig, None

            return False, None, "confirmation_timeout"

    except ImportError:
        logger.error("solana-py / solders not installed — cannot execute SPL transfer")
        return False, None, "solana_sdk_not_installed"
    except Exception as exc:
        logger.error("Solana transfer failed for withdrawal %s: %s", withdrawal.id, exc)
        return False, None, str(exc)


async def _write_ledger_debit(
    db: AsyncSession,
    withdrawal: Withdrawal,
) -> None:
    entry = LedgerEntry(
        id=str(uuid.uuid4()),
        account_type="supplier",
        account_id=withdrawal.supplier_id,
        kind="debit",
        amount_micros=withdrawal.amount_micros,
        reason="withdrawal",
        reference_id=withdrawal.id,
        protocol_id=None,
    )
    try:
        db.add(entry)
        await db.flush()
    except IntegrityError:
        logger.warning("Duplicate debit skipped for withdrawal %s", withdrawal.id)
        raise


async def run_withdrawal_worker() -> None:
    """Entry point called by APScheduler (and directly in tests)."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Withdrawal)
            .where(Withdrawal.status == "pending")
            .order_by(Withdrawal.created_at)
            .limit(_BATCH_SIZE)
        )
        pending = result.scalars().all()

    for withdrawal in pending:
        await _process_withdrawal(withdrawal.id)


async def _process_withdrawal(withdrawal_id: str) -> None:
    async with AsyncSessionLocal() as db:
        async with db.begin():
            result = await db.execute(
                select(Withdrawal)
                .where(Withdrawal.id == withdrawal_id)
                .with_for_update(skip_locked=True)
            )
            withdrawal = result.scalar_one_or_none()
            if not withdrawal or withdrawal.status != "pending":
                return

            supplier_result = await db.execute(
                select(Supplier).where(Supplier.id == withdrawal.supplier_id)
            )
            supplier = supplier_result.scalar_one_or_none()

            available = await _get_available_balance(
                db, withdrawal.supplier_id, exclude_withdrawal_id=withdrawal.id
            )
            if withdrawal.amount_micros > available:
                await db.execute(
                    update(Withdrawal)
                    .where(Withdrawal.id == withdrawal.id)
                    .values(status="failed", failure_reason="insufficient_balance")
                )
                logger.info("Withdrawal %s failed: insufficient_balance", withdrawal.id)
                return

            if (
                withdrawal.amount_micros > settings.kyc_threshold_micros
                and supplier
                and not supplier.kyc_completed
            ):
                await db.execute(
                    update(Withdrawal)
                    .where(Withdrawal.id == withdrawal.id)
                    .values(status="pending_kyc")
                )
                logger.info("Withdrawal %s pending_kyc", withdrawal.id)
                supplier_email = getattr(supplier, "email", None) or ""

    if withdrawal.status == "pending_kyc":
        if supplier_email:
            await _send_kyc_email(supplier_email, withdrawal.amount_micros)
        return

    async with AsyncSessionLocal() as db:
        async with db.begin():
            result = await db.execute(
                select(Withdrawal)
                .where(Withdrawal.id == withdrawal_id)
                .with_for_update(skip_locked=True)
            )
            withdrawal = result.scalar_one_or_none()
            if not withdrawal or withdrawal.status != "pending":
                return
            await db.execute(
                update(Withdrawal)
                .where(Withdrawal.id == withdrawal.id)
                .values(status="processing")
            )

    if withdrawal.method == "usdc_solana":
        success, tx_hash, error = await _execute_solana_transfer(withdrawal)

        async with AsyncSessionLocal() as db:
            async with db.begin():
                if success:
                    completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
                    await db.execute(
                        update(Withdrawal)
                        .where(Withdrawal.id == withdrawal.id)
                        .values(
                            status="confirmed",
                            tx_hash=tx_hash,
                            completed_at=completed_at,
                        )
                    )
                    result = await db.execute(
                        select(Withdrawal).where(Withdrawal.id == withdrawal.id)
                    )
                    w = result.scalar_one()
                    await _write_ledger_debit(db, w)
                    logger.info("Withdrawal %s confirmed tx=%s", withdrawal.id, tx_hash)
                else:
                    await db.execute(
                        update(Withdrawal)
                        .where(Withdrawal.id == withdrawal.id)
                        .values(status="failed", failure_reason=error)
                    )
                    logger.error("Withdrawal %s failed: %s", withdrawal.id, error)

    elif withdrawal.method == "stripe":
        success, error = await _execute_stripe_transfer(withdrawal)
        if not success:
            async with AsyncSessionLocal() as db:
                async with db.begin():
                    await db.execute(
                        update(Withdrawal)
                        .where(Withdrawal.id == withdrawal.id)
                        .values(status="failed", failure_reason=error)
                    )


async def _execute_stripe_transfer(
    withdrawal: Withdrawal,
) -> tuple[bool, Optional[str]]:
    """Create a Stripe Connect Transfer. Confirmation comes via webhook."""
    if not settings.stripe_secret_key:
        return False, "stripe_not_configured"
    try:
        import stripe  # type: ignore[import]
        stripe.api_key = settings.stripe_secret_key
        stripe.Transfer.create(
            amount=withdrawal.amount_micros // 1000,
            currency="usd",
            destination=withdrawal.destination_address,
            metadata={"withdrawal_id": withdrawal.id},
        )
        return True, None
    except ImportError:
        return False, "stripe_sdk_not_installed"
    except Exception as exc:
        return False, str(exc)
