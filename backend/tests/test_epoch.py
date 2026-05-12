"""
tests/test_epoch.py
Tests for the epoch worker: payout aggregation, exclusions, idempotency.

All tests use an in-memory SQLite database seeded with fixture data.
"""
from __future__ import annotations

import sys
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy import select

from database import Base


# ── In-memory DB fixture ──────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    import models.epoch  # noqa
    import models.ledger_entry  # noqa
    import models.call_log  # noqa
    import models.supplier  # noqa
    import models.buyer  # noqa
    import models.protocol  # noqa
    import models.supplier_key  # noqa
    import models.pricing_rule  # noqa

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session

    await engine.dispose()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_epoch(status="open", ends_at_offset_hours=-1) -> "models.epoch.Epoch":
    from models.epoch import Epoch
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    started = now - timedelta(hours=8)
    ends = now + timedelta(hours=ends_at_offset_hours)
    return Epoch(
        id=str(uuid.uuid4()),
        started_at=started,
        ends_at=ends,
        status=status,
    )


def _make_call_log(epoch_id, supplier_id, protocol_id, supplier_share_micros,
                   was_self_served=False, was_refunded=False) -> "models.call_log.CallLog":
    from models.call_log import CallLog
    return CallLog(
        id=str(uuid.uuid4()),
        buyer_id=str(uuid.uuid4()),
        supplier_id=supplier_id,
        protocol_id=protocol_id,
        key_id=str(uuid.uuid4()),
        epoch_id=epoch_id,
        response_status=200,
        request_ms=100,
        was_self_served=was_self_served,
        was_refunded=was_refunded,
        gross_charge_micros=supplier_share_micros + 500,
        supplier_share_micros=supplier_share_micros,
        jellynet_share_micros=500,
        buyer_discount_micros=0,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_multi_supplier_multi_protocol_payout(db: AsyncSession) -> None:
    """
    3 suppliers across 2 protocols should each get a credit equal to
    the sum of their supplier_share_micros within the epoch.
    """
    from models.ledger_entry import LedgerEntry
    from workers.epoch_worker import _close_expired_epochs, _ensure_open_epoch

    epoch = _make_epoch(status="open", ends_at_offset_hours=-1)
    db.add(epoch)

    s1, s2, s3 = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    p1, p2 = str(uuid.uuid4()), str(uuid.uuid4())

    logs = [
        _make_call_log(epoch.id, s1, p1, 1000),
        _make_call_log(epoch.id, s1, p1, 2000),
        _make_call_log(epoch.id, s2, p1, 3000),
        _make_call_log(epoch.id, s2, p2, 1500),
        _make_call_log(epoch.id, s3, p2, 5000),
    ]
    for log in logs:
        db.add(log)
    await db.commit()

    async with db.begin():
        await _close_expired_epochs(db)

    result = await db.execute(
        select(LedgerEntry).where(LedgerEntry.reason == "epoch_payout")
    )
    entries = result.scalars().all()

    totals = {}
    for e in entries:
        totals[(e.account_id, e.protocol_id)] = e.amount_micros

    assert totals[(s1, p1)] == 3000   # 1000 + 2000
    assert totals[(s2, p1)] == 3000
    assert totals[(s2, p2)] == 1500
    assert totals[(s3, p2)] == 5000


@pytest.mark.asyncio
async def test_self_served_calls_excluded(db: AsyncSession) -> None:
    """Self-served calls must not accrue to supplier ledger."""
    from models.ledger_entry import LedgerEntry
    from workers.epoch_worker import _close_expired_epochs

    epoch = _make_epoch(status="open", ends_at_offset_hours=-1)
    db.add(epoch)

    supplier_id = str(uuid.uuid4())
    protocol_id = str(uuid.uuid4())

    db.add(_make_call_log(epoch.id, supplier_id, protocol_id, 5000, was_self_served=True))
    await db.commit()

    async with db.begin():
        await _close_expired_epochs(db)

    result = await db.execute(
        select(LedgerEntry).where(
            LedgerEntry.account_id == supplier_id,
            LedgerEntry.reason == "epoch_payout",
        )
    )
    assert result.scalars().first() is None


@pytest.mark.asyncio
async def test_refunded_calls_excluded(db: AsyncSession) -> None:
    """Refunded calls (upstream 5xx) must not accrue to supplier ledger."""
    from models.ledger_entry import LedgerEntry
    from workers.epoch_worker import _close_expired_epochs

    epoch = _make_epoch(status="open", ends_at_offset_hours=-1)
    db.add(epoch)

    supplier_id = str(uuid.uuid4())
    protocol_id = str(uuid.uuid4())

    db.add(_make_call_log(epoch.id, supplier_id, protocol_id, 4000, was_refunded=True))
    await db.commit()

    async with db.begin():
        await _close_expired_epochs(db)

    result = await db.execute(
        select(LedgerEntry).where(
            LedgerEntry.account_id == supplier_id,
            LedgerEntry.reason == "epoch_payout",
        )
    )
    assert result.scalars().first() is None


@pytest.mark.asyncio
async def test_rerun_on_closed_epoch_is_noop(db: AsyncSession) -> None:
    """Re-running _close_expired_epochs on an already-closed epoch produces no duplicates."""
    from models.ledger_entry import LedgerEntry
    from models.epoch import Epoch
    from workers.epoch_worker import _close_expired_epochs

    epoch = _make_epoch(status="open", ends_at_offset_hours=-1)
    db.add(epoch)

    supplier_id = str(uuid.uuid4())
    protocol_id = str(uuid.uuid4())
    db.add(_make_call_log(epoch.id, supplier_id, protocol_id, 2000))
    await db.commit()

    async with db.begin():
        await _close_expired_epochs(db)

    async with db.begin():
        await _close_expired_epochs(db)

    result = await db.execute(
        select(LedgerEntry).where(
            LedgerEntry.account_id == supplier_id,
            LedgerEntry.reason == "epoch_payout",
        )
    )
    entries = result.scalars().all()
    assert len(entries) == 1
    assert entries[0].amount_micros == 2000


@pytest.mark.asyncio
async def test_bootstrap_creates_epoch_if_none_exists(db: AsyncSession) -> None:
    """_ensure_open_epoch creates a new epoch anchored to UTC boundary when none exists."""
    from models.epoch import Epoch
    from workers.epoch_worker import _ensure_open_epoch

    async with db.begin():
        epoch = await _ensure_open_epoch(db)

    assert epoch.status == "open"
    assert epoch.ends_at > epoch.started_at
    delta = epoch.ends_at - epoch.started_at
    assert delta.total_seconds() == 8 * 3600


@pytest.mark.asyncio
async def test_next_epoch_opened_after_close(db: AsyncSession) -> None:
    """After closing an epoch, a new open epoch is immediately created."""
    from models.epoch import Epoch
    from workers.epoch_worker import _close_expired_epochs

    epoch = _make_epoch(status="open", ends_at_offset_hours=-1)
    db.add(epoch)
    await db.commit()

    async with db.begin():
        await _close_expired_epochs(db)

    result = await db.execute(
        select(Epoch).where(Epoch.status == "open")
    )
    next_epoch = result.scalar_one_or_none()
    assert next_epoch is not None
    assert next_epoch.started_at == epoch.ends_at
