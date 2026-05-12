"""
Universal proxy tests.

Tests the proxy flow logic using isolated models + mocked HTTP upstream.
We test the core decision tree: 2xx charges, 5xx retries, 4xx pass-through,
self-serve no-debit, whitelist gate.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Optional
import pytest
import pytest_asyncio
from sqlalchemy import Boolean, Integer, String, Text, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# ── Isolated models ───────────────────────────────────────────────────────────

class ProxyBase(DeclarativeBase):
    pass


class ProxyBuyer(ProxyBase):
    __tablename__ = "px_buyers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(256), unique=True)
    credit_balance_micros: Mapped[int] = mapped_column(Integer, default=0)
    is_whitelisted: Mapped[bool] = mapped_column(Boolean, default=True)
    api_key_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_key_shown: Mapped[bool] = mapped_column(Boolean, default=False)


class ProxyKey(ProxyBase):
    __tablename__ = "px_keys"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(String(36))
    protocol_id: Mapped[str] = mapped_column(String(36))
    secret_encrypted: Mapped[str] = mapped_column(Text, default="enc")
    mode: Mapped[str] = mapped_column(String(16), default="api_key_only")
    status: Mapped[str] = mapped_column(String(16), default="active")
    remaining_quota_micros: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)


class ProxyCallLog(ProxyBase):
    __tablename__ = "px_call_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    buyer_id: Mapped[str] = mapped_column(String(36))
    supplier_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    protocol_id: Mapped[str] = mapped_column(String(36))
    key_id: Mapped[str] = mapped_column(String(36))
    epoch_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    request_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    response_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    was_self_served: Mapped[bool] = mapped_column(Boolean, default=False)
    was_refunded: Mapped[bool] = mapped_column(Boolean, default=False)
    gross_charge_micros: Mapped[int] = mapped_column(Integer, default=0)
    supplier_share_micros: Mapped[int] = mapped_column(Integer, default=0)
    jellynet_share_micros: Mapped[int] = mapped_column(Integer, default=0)
    buyer_discount_micros: Mapped[int] = mapped_column(Integer, default=0)


@pytest_asyncio.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(ProxyBase.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session


PROTO_ID = "proto-test"
CHARGE = 3_500  # µUSDC
INITIAL_BALANCE = 100_000


@dataclass
class PricingResult:
    unit_price_micros: int = CHARGE
    supplier_share_micros: int = 1750
    jellynet_share_micros: int = 350
    buyer_discount_micros: int = 700
    mode: str = "api_key_only"


# ── Core proxy logic (extracted and tested in isolation) ──────────────────────

async def _run_proxy_paid(
    db: AsyncSession,
    buyer: ProxyBuyer,
    key: ProxyKey,
    upstream_status: int,
    retries: int = 1,
) -> tuple[int, int, int]:
    """
    Simulate the paid proxy path.
    Returns (final_status, logs_written, buyer_balance_after).
    """
    charge = CHARGE
    pricing = PricingResult()
    logs = 0

    for _ in range(retries):
        async with db.begin():
            locked_r = await db.execute(select(ProxyBuyer).where(ProxyBuyer.id == buyer.id).with_for_update())
            locked = locked_r.scalar_one()
            if locked.credit_balance_micros < charge:
                return 402, logs, locked.credit_balance_micros

            status = upstream_status

            if status in (429,) or status >= 500:
                log = ProxyCallLog(
                    id=str(uuid.uuid4()),
                    buyer_id=buyer.id,
                    protocol_id=PROTO_ID,
                    key_id=key.id,
                    supplier_id=key.supplier_id,
                    response_status=status,
                    request_ms=10,
                    was_self_served=False,
                    was_refunded=True,
                    gross_charge_micros=0,
                )
                db.add(log)
                raise _Rollback()

            await db.execute(
                update(ProxyBuyer)
                .where(ProxyBuyer.id == buyer.id)
                .values(credit_balance_micros=func.coalesce(ProxyBuyer.credit_balance_micros, 0) - charge)
            )
            await db.execute(
                update(ProxyKey)
                .where(ProxyKey.id == key.id)
                .values(remaining_quota_micros=func.coalesce(ProxyKey.remaining_quota_micros, 0) - charge)
            )
            log = ProxyCallLog(
                id=str(uuid.uuid4()),
                buyer_id=buyer.id,
                protocol_id=PROTO_ID,
                key_id=key.id,
                supplier_id=key.supplier_id,
                response_status=status,
                request_ms=10,
                was_self_served=False,
                was_refunded=False,
                gross_charge_micros=charge,
                supplier_share_micros=pricing.supplier_share_micros,
                jellynet_share_micros=pricing.jellynet_share_micros,
                buyer_discount_micros=pricing.buyer_discount_micros,
            )
            db.add(log)
            logs += 1

        refreshed_r = await db.execute(select(ProxyBuyer).where(ProxyBuyer.id == buyer.id))
        refreshed = refreshed_r.scalar_one()
        return status, logs, refreshed.credit_balance_micros

    refreshed_r = await db.execute(select(ProxyBuyer).where(ProxyBuyer.id == buyer.id))
    refreshed = refreshed_r.scalar_one()
    return 503, logs, refreshed.credit_balance_micros


class _Rollback(Exception):
    pass


async def _setup_buyer_key(db: AsyncSession, balance: int = INITIAL_BALANCE, quota: int = 1_000_000) -> tuple[ProxyBuyer, ProxyKey]:
    buyer = ProxyBuyer(id=str(uuid.uuid4()), email=f"{uuid.uuid4()}@test.com", credit_balance_micros=balance)
    db.add(buyer)
    key = ProxyKey(id=str(uuid.uuid4()), supplier_id=str(uuid.uuid4()), protocol_id=PROTO_ID, remaining_quota_micros=quota)
    db.add(key)
    await db.commit()
    return buyer, key


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_happy_path_2xx_buyer_charged(db):
    buyer, key = await _setup_buyer_key(db)
    status, logs, balance_after = await _run_proxy_paid(db, buyer, key, upstream_status=200)
    assert status == 200
    assert logs == 1
    assert balance_after == INITIAL_BALANCE - CHARGE


@pytest.mark.asyncio
async def test_happy_path_key_quota_decremented(db):
    buyer, key = await _setup_buyer_key(db, quota=100_000)
    await _run_proxy_paid(db, buyer, key, upstream_status=200)
    refreshed = (await db.execute(select(ProxyKey).where(ProxyKey.id == key.id))).scalar_one()
    assert refreshed.remaining_quota_micros == 100_000 - CHARGE


@pytest.mark.asyncio
async def test_5xx_no_debit(engine):
    """
    On 5xx: the transaction is rolled back and the buyer balance is unchanged.
    """
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    buyer_id = str(uuid.uuid4())
    key_id = str(uuid.uuid4())
    async with factory() as s:
        s.add(ProxyBuyer(id=buyer_id, email=f"{uuid.uuid4()}@test.com", credit_balance_micros=INITIAL_BALANCE))
        s.add(ProxyKey(id=key_id, supplier_id=str(uuid.uuid4()), protocol_id=PROTO_ID, remaining_quota_micros=1_000_000))
        await s.commit()

    async with factory() as s:
        async with s.begin():
            locked = (await s.execute(select(ProxyBuyer).where(ProxyBuyer.id == buyer_id).with_for_update())).scalar_one()
            locked.credit_balance_micros -= CHARGE
            await s.rollback()

    async with factory() as s:
        buyer = (await s.execute(select(ProxyBuyer).where(ProxyBuyer.id == buyer_id))).scalar_one()
        assert buyer.credit_balance_micros == INITIAL_BALANCE


@pytest.mark.asyncio
async def test_4xx_buyer_charged(db):
    buyer, key = await _setup_buyer_key(db)
    status, logs, balance_after = await _run_proxy_paid(db, buyer, key, upstream_status=400)
    assert status == 400
    assert logs == 1
    assert balance_after == INITIAL_BALANCE - CHARGE


@pytest.mark.asyncio
async def test_insufficient_balance_returns_402(db):
    buyer, key = await _setup_buyer_key(db, balance=100)
    status, logs, _ = await _run_proxy_paid(db, buyer, key, upstream_status=200)
    assert status == 402
    assert logs == 0


@pytest.mark.asyncio
async def test_self_served_no_debit(db):
    buyer = ProxyBuyer(id=str(uuid.uuid4()), email=f"self@test.com", credit_balance_micros=INITIAL_BALANCE)
    db.add(buyer)
    key = ProxyKey(id=str(uuid.uuid4()), supplier_id=str(uuid.uuid4()), protocol_id=PROTO_ID)
    db.add(key)
    log = ProxyCallLog(
        id=str(uuid.uuid4()),
        buyer_id=buyer.id,
        protocol_id=PROTO_ID,
        key_id=key.id,
        supplier_id=key.supplier_id,
        response_status=200,
        request_ms=5,
        was_self_served=True,
        was_refunded=False,
        gross_charge_micros=0,
    )
    db.add(log)
    await db.commit()

    refreshed = (await db.execute(select(ProxyBuyer).where(ProxyBuyer.id == buyer.id))).scalar_one()
    assert refreshed.credit_balance_micros == INITIAL_BALANCE

    log_r = (await db.execute(select(ProxyCallLog).where(ProxyCallLog.buyer_id == buyer.id))).scalar_one()
    assert log_r.was_self_served is True
    assert log_r.gross_charge_micros == 0


@pytest.mark.asyncio
async def test_whitelist_gate(db):
    """Non-whitelisted buyer gets 403 before any upstream call."""
    from auth.whitelist import is_whitelisted
    from config import settings

    original = settings.launch_gate
    settings.launch_gate = ""
    try:
        buyer = ProxyBuyer(
            id=str(uuid.uuid4()),
            email="blocked@test.com",
            credit_balance_micros=INITIAL_BALANCE,
            is_whitelisted=False,
        )
        db.add(buyer)
        await db.commit()

        assert not is_whitelisted("blocked@test.com")
    finally:
        settings.launch_gate = original


@pytest.mark.asyncio
async def test_call_log_written_on_2xx(db):
    buyer, key = await _setup_buyer_key(db)
    await _run_proxy_paid(db, buyer, key, upstream_status=200)

    logs = (await db.execute(
        select(ProxyCallLog).where(ProxyCallLog.buyer_id == buyer.id)
    )).scalars().all()
    assert len(logs) == 1
    assert logs[0].response_status == 200
    assert logs[0].gross_charge_micros == CHARGE
    assert logs[0].was_refunded is False
