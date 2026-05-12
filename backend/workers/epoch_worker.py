"""
JellyNet — workers/epoch_worker.py
Closes 8-hour epochs and distributes supplier payouts to the ledger.

Cron: 0 */8 * * * UTC  (scheduled via APScheduler in main.py)

Flow:
  1. Bootstrap: ensure an open epoch exists (create if missing).
  2. Find the open epoch whose ends_at has passed → mark closing.
  3. Aggregate call_logs for that epoch (non-self-served, non-refunded).
  4. Write one ledger credit per (supplier_id, protocol_id) group.
  5. Mark epoch closed; open the next one immediately.

Idempotency: the unique constraint on ledger_entries
(reason, reference_id, account_id, protocol_id) means re-running
a closed epoch produces no duplicate rows (ON CONFLICT DO NOTHING).
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from models.call_log import CallLog
from models.epoch import Epoch
from models.ledger_entry import LedgerEntry

logger = logging.getLogger(__name__)

_EPOCH_HOURS = 8
_EPOCH_BOUNDARIES = (0, 8, 16)  # UTC hours at which epochs start/end


def _last_boundary(now: datetime) -> datetime:
    """Return the most recent 00:00/08:00/16:00 UTC before or equal to now."""
    hour = now.hour
    last_h = max(h for h in _EPOCH_BOUNDARIES if h <= hour)
    return now.replace(hour=last_h, minute=0, second=0, microsecond=0)


async def _ensure_open_epoch(db: AsyncSession) -> Epoch:
    """Return the current open epoch, creating one if none exists."""
    result = await db.execute(
        select(Epoch).where(Epoch.status == "open").limit(1)
    )
    epoch = result.scalar_one_or_none()
    if epoch:
        return epoch

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    started_at = _last_boundary(now)
    ends_at = started_at + timedelta(hours=_EPOCH_HOURS)
    epoch = Epoch(
        id=str(uuid.uuid4()),
        started_at=started_at,
        ends_at=ends_at,
        status="open",
    )
    db.add(epoch)
    await db.flush()
    logger.info("Bootstrapped new epoch %s (%s → %s)", epoch.id, started_at, ends_at)
    return epoch


async def _open_next_epoch(db: AsyncSession, closed_epoch: Epoch) -> Epoch:
    """Open the next epoch immediately after the one that just closed."""
    started_at = closed_epoch.ends_at
    ends_at = started_at + timedelta(hours=_EPOCH_HOURS)
    next_epoch = Epoch(
        id=str(uuid.uuid4()),
        started_at=started_at,
        ends_at=ends_at,
        status="open",
    )
    db.add(next_epoch)
    await db.flush()
    logger.info("Opened next epoch %s (%s → %s)", next_epoch.id, started_at, ends_at)
    return next_epoch


async def run_epoch_worker() -> None:
    """Entry point called by APScheduler (and directly in tests)."""
    async with AsyncSessionLocal() as db:
        async with db.begin():
            await _ensure_open_epoch(db)

        async with db.begin():
            await _close_expired_epochs(db)


async def _close_expired_epochs(db: AsyncSession) -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    result = await db.execute(
        select(Epoch)
        .where(Epoch.status == "open", Epoch.ends_at <= now)
        .limit(1)
    )
    epoch = result.scalar_one_or_none()

    if not epoch:
        logger.debug("No expired open epoch to close.")
        return

    logger.info("Closing epoch %s (ended %s)", epoch.id, epoch.ends_at)

    await db.execute(
        update(Epoch).where(Epoch.id == epoch.id).values(status="closing")
    )

    # Aggregate supplier shares from call_logs
    agg_result = await db.execute(
        select(
            CallLog.supplier_id,
            CallLog.protocol_id,
            func.sum(CallLog.supplier_share_micros).label("total_micros"),
        )
        .where(
            CallLog.epoch_id == epoch.id,
            CallLog.was_self_served == False,  # noqa: E712
            CallLog.was_refunded == False,     # noqa: E712
            CallLog.supplier_id.isnot(None),
        )
        .group_by(CallLog.supplier_id, CallLog.protocol_id)
    )
    rows = agg_result.fetchall()

    payout_total = 0
    for supplier_id, protocol_id, total_micros in rows:
        if not total_micros or total_micros <= 0:
            continue
        payout_total += total_micros
        entry = LedgerEntry(
            id=str(uuid.uuid4()),
            account_type="supplier",
            account_id=supplier_id,
            kind="credit",
            amount_micros=total_micros,
            reason="epoch_payout",
            reference_id=epoch.id,
            protocol_id=protocol_id,
        )
        try:
            db.add(entry)
            await db.flush()
        except IntegrityError:
            await db.rollback()
            logger.warning(
                "Duplicate epoch_payout skipped: epoch=%s supplier=%s protocol=%s",
                epoch.id, supplier_id, protocol_id,
            )
            await db.begin()
            continue

    closed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.execute(
        update(Epoch)
        .where(Epoch.id == epoch.id)
        .values(status="closed", payout_total_micros=payout_total, closed_at=closed_at)
    )
    logger.info("Epoch %s closed. Payout total: %d µUSDC", epoch.id, payout_total)

    await _open_next_epoch(db, epoch)
