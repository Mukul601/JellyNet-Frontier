"""
JellyNet — routes/proxy.py
Universal API endpoint: POST/GET /v1/{path}

Flow:
  1. Check for X-Payment header → x402 agent path (no buyer account needed)
  2. Check for Authorization header → jn_xxx buyer path
  3. Neither → return 402 Payment Required with PaymentRequirements
  4. Whitelist gate (buyer path only)
  5. Router: resolve Protocol
  6. Estimate cost
  7. Pool: pick key from supplier capacity pool
     # Production routing uses weighted-random selection based on remaining quota
  8. Forward upstream call
  9. Log call and settle credits
"""
from __future__ import annotations

import json
import logging
import time
import uuid
from typing import AsyncIterator, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from auth.whitelist import is_whitelisted
from config import settings
from database import get_db
from middleware.api_key_auth import get_buyer_from_api_key
from models.buyer import Buyer
from models.call_log import CallLog
from models.epoch import Epoch
from models.ledger_entry import LedgerEntry
from models.supplier_key import SupplierKey
from services.chains.base_chain import SettlePayload, VerifyPayload
from services.chains.factory import get_chain
from services.pool import NoCapacityAvailable, pick_key
from services.pricing import estimate_unit_price, resolve_unit_price
from services.router import resolve_protocol
from services.x402_service import X402Service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["v1-proxy"])

UPSTREAM_BASES: dict[str, str] = {
    "openai-gpt4o":      "https://api.openai.com",
    "anthropic-claude":  "https://api.anthropic.com",
    "gemini-pro":        "https://generativelanguage.googleapis.com",
    "groq-llama3":       "https://api.groq.com/openai",
    "mistral-medium":    "https://api.mistral.ai",
    "together-mixtral":  "https://api.together.xyz",
    "cohere-command":    "https://api.cohere.ai",
}

_STRIP_HEADERS = {
    "host", "content-length", "transfer-encoding",
    "connection", "x-jellynet-protocol", "x-jellynet-retries",
    "x-payment", "authorization",
}


def _forward_headers(request: Request, api_key: str) -> dict:
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _STRIP_HEADERS
    }
    headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _anthropic_headers(api_key: str, original: dict) -> dict:
    headers = {k: v for k, v in original.items() if k.lower() != "authorization"}
    headers["x-api-key"] = api_key
    headers.setdefault("anthropic-version", "2023-06-01")
    return headers


def _build_upstream_url(slug: str, path: str, query: str) -> str:
    base = UPSTREAM_BASES.get(slug, "")
    url = f"{base}/{path.lstrip('/')}"
    if query:
        url = f"{url}?{query}"
    return url


async def _get_open_epoch_id(db: AsyncSession) -> Optional[str]:
    result = await db.execute(
        select(Epoch).where(Epoch.status == "open").limit(1)
    )
    epoch = result.scalar_one_or_none()
    return epoch.id if epoch else None


async def _write_call_log(
    db: AsyncSession,
    *,
    buyer_id: Optional[str],
    protocol_id: str,
    key_id: str,
    supplier_id: Optional[str],
    epoch_id: Optional[str],
    response_status: int,
    request_ms: int,
    was_self_served: bool,
    was_refunded: bool,
    gross_charge_micros: int,
    supplier_share_micros: int,
    jellynet_share_micros: int,
    buyer_discount_micros: int,
) -> None:
    log = CallLog(
        id=str(uuid.uuid4()),
        buyer_id=buyer_id,
        supplier_id=supplier_id,
        protocol_id=protocol_id,
        key_id=key_id,
        epoch_id=epoch_id,
        response_status=response_status,
        request_ms=request_ms,
        was_self_served=was_self_served,
        was_refunded=was_refunded,
        gross_charge_micros=gross_charge_micros,
        supplier_share_micros=supplier_share_micros,
        jellynet_share_micros=jellynet_share_micros,
        buyer_discount_micros=buyer_discount_micros,
    )
    db.add(log)
    await db.flush()


async def _write_x402_jellynet_credit(
    db: AsyncSession,
    *,
    tx_id: str,
    protocol_id: str,
    amount_micros: int,
) -> None:
    entry = LedgerEntry(
        id=str(uuid.uuid4()),
        account_type="jellynet",
        account_id="platform",
        kind="credit",
        amount_micros=amount_micros,
        reason="deposit_x402",
        reference_id=tx_id,
        protocol_id=protocol_id,
    )
    db.add(entry)
    await db.flush()


@router.api_route(
    "/v1/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
    response_model=None,
)
async def universal_proxy(
    path: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse | JSONResponse:

    x_payment_header = request.headers.get("X-Payment") or request.headers.get("x-payment")
    has_auth = bool(request.headers.get("Authorization") or request.headers.get("authorization"))

    body_bytes = await request.body()
    try:
        body_json: dict = json.loads(body_bytes) if body_bytes else {}
    except json.JSONDecodeError:
        body_json = {}

    is_streaming = (
        body_json.get("stream", False)
        or "text/event-stream" in request.headers.get("accept", "")
    )

    protocol = await resolve_protocol(
        db,
        method=request.method,
        path=f"/{path}",
        body=body_json,
        header_override=request.headers.get("X-Jellynet-Protocol"),
    )

    if x_payment_header:
        return await _handle_x402_payment(
            path=path,
            request=request,
            body_bytes=body_bytes,
            protocol=protocol,
            x_payment_header=x_payment_header,
            is_streaming=is_streaming,
            db=db,
        )

    if not has_auth:
        x402_svc = X402Service(settings)
        payment_requirements = x402_svc.build_402_response(protocol, f"/v1/{path}")
        return JSONResponse(status_code=402, content=payment_requirements)

    buyer = await _get_buyer_from_request(request, db)
    return await _handle_buyer_path(
        path=path,
        request=request,
        body_bytes=body_bytes,
        body_json=body_json,
        protocol=protocol,
        buyer=buyer,
        is_streaming=is_streaming,
        db=db,
    )


async def _get_buyer_from_request(request: Request, db: AsyncSession) -> Buyer:
    from middleware.api_key_auth import get_buyer_from_api_key
    try:
        buyer = await get_buyer_from_api_key(request, db)
    except HTTPException:
        raise
    if buyer is None:
        raise HTTPException(status_code=401, detail={"code": "Unauthorized", "message": "Valid jn_xxx API key required."})
    return buyer


async def _handle_x402_payment(
    *,
    path: str,
    request: Request,
    body_bytes: bytes,
    protocol,
    x_payment_header: str,
    is_streaming: bool,
    db: AsyncSession,
) -> JSONResponse | StreamingResponse:
    """Verify + settle an x402 payment, then forward the request."""
    x402_svc = X402Service(settings)

    try:
        payment_data = x402_svc.decode_payment_header(x_payment_header)
    except ValueError as exc:
        return JSONResponse(
            status_code=402,
            content={"error": f"Invalid X-Payment header: {exc}", "x402Version": settings.x402_version},
        )

    details = x402_svc.extract_payment_details(payment_data)
    network = details["network"]

    if x402_svc.is_payment_expired(details["valid_before"]):
        return JSONResponse(
            status_code=402,
            content={"error": "Payment window expired", "x402Version": settings.x402_version},
        )

    try:
        chain = get_chain(network, settings)
    except ValueError as exc:
        return JSONResponse(
            status_code=402,
            content={"error": str(exc), "x402Version": settings.x402_version},
        )

    verify_result = await chain.verify(
        VerifyPayload(
            tx_hash=details["tx_hash"],
            from_address=details["from_address"],
            to_address=details["to_address"],
            amount=details["value"],
            network=network,
        )
    )
    if not verify_result.is_valid:
        return JSONResponse(
            status_code=402,
            content={
                "error": verify_result.error or "Payment verification failed",
                "x402Version": settings.x402_version,
            },
        )

    settle_result = await chain.settle(
        SettlePayload(
            tx_hash=details["tx_hash"],
            network=network,
            raw_payload=payment_data,
        )
    )
    if not settle_result.success:
        return JSONResponse(
            status_code=402,
            content={
                "error": settle_result.error or "Payment settlement failed",
                "x402Version": settings.x402_version,
            },
        )

    tx_id = settle_result.transaction_id or details["tx_hash"]

    est_cost = await estimate_unit_price(db, protocol.id)
    try:
        pool_result = await pick_key(db, None, protocol.id, est_cost)
    except NoCapacityAvailable:
        raise HTTPException(
            status_code=503,
            detail={"code": "NoCapacityAvailable", "message": "No supplier capacity available."},
        )

    pricing = await resolve_unit_price(db, protocol.id, pool_result.key.id)
    raw_secret = settings.key_enc_fernet.decrypt(
        pool_result.key.secret_encrypted.encode()
    ).decode()

    base_headers = _forward_headers(request, raw_secret)
    if protocol.slug == "anthropic-claude":
        base_headers = _anthropic_headers(raw_secret, base_headers)

    epoch_id = await _get_open_epoch_id(db)

    t0 = time.monotonic()
    try:
        upstream_resp = await request.app.state.proxy_service.forward(
            target_url=UPSTREAM_BASES.get(protocol.slug, ""),
            api_key=raw_secret,
            method=request.method,
            path=path,
            headers=dict(request.headers),
            body=body_bytes or None,
            query_string=request.url.query,
        )
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream connection error: {exc}")
    elapsed_ms = int((time.monotonic() - t0) * 1000)

    async with db.begin():
        await _write_call_log(
            db,
            buyer_id=None,
            protocol_id=protocol.id,
            key_id=pool_result.key.id,
            supplier_id=pool_result.key.supplier_id,
            epoch_id=epoch_id,
            response_status=upstream_resp.status_code,
            request_ms=elapsed_ms,
            was_self_served=False,
            was_refunded=False,
            gross_charge_micros=pricing.unit_price_micros,
            supplier_share_micros=pricing.supplier_share_micros,
            jellynet_share_micros=pricing.jellynet_share_micros,
            buyer_discount_micros=0,
        )
        await _write_x402_jellynet_credit(
            db,
            tx_id=tx_id,
            protocol_id=protocol.id,
            amount_micros=pricing.jellynet_share_micros,
        )

    try:
        content = upstream_resp.json()
    except Exception:
        content = upstream_resp.text

    return JSONResponse(status_code=upstream_resp.status_code, content=content)


async def _handle_buyer_path(
    *,
    path: str,
    request: Request,
    body_bytes: bytes,
    body_json: dict,
    protocol,
    buyer: Buyer,
    is_streaming: bool,
    db: AsyncSession,
) -> StreamingResponse | JSONResponse:
    """Standard jn_xxx buyer path with balance check and retries."""

    if not is_whitelisted(buyer.email) and settings.launch_gate.lower() != "open":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "WaitlistOnly",
                "message": "Beta access required. Join the waitlist to get access.",
                "waitlist_url": "/waitlist",
            },
        )

    est_cost = await estimate_unit_price(db, protocol.id)

    try:
        pool_result = await pick_key(db, buyer.id, protocol.id, est_cost)
    except NoCapacityAvailable:
        raise HTTPException(
            status_code=503,
            detail={"code": "NoCapacityAvailable", "message": "No supplier capacity available for this protocol."},
        )

    pricing = await resolve_unit_price(db, protocol.id, pool_result.key.id)
    charge = pricing.unit_price_micros

    raw_secret = settings.key_enc_fernet.decrypt(
        pool_result.key.secret_encrypted.encode()
    ).decode()

    base_headers = _forward_headers(request, raw_secret)
    if protocol.slug == "anthropic-claude":
        base_headers = _anthropic_headers(raw_secret, base_headers)

    epoch_id = await _get_open_epoch_id(db)

    if pool_result.was_self_served:
        t0 = time.monotonic()
        try:
            if is_streaming:
                return await _stream_response(
                    request, _build_upstream_url(protocol.slug, path, request.url.query),
                    base_headers, body_bytes,
                    db, buyer, pool_result.key, protocol, pricing,
                    was_self_served=True, epoch_id=epoch_id,
                )
            upstream_resp = await request.app.state.proxy_service.forward(
                target_url=UPSTREAM_BASES.get(protocol.slug, ""),
                api_key=raw_secret,
                method=request.method,
                path=path,
                headers=dict(request.headers),
                body=body_bytes or None,
                query_string=request.url.query,
            )
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=f"Upstream connection error: {exc}")
        elapsed_ms = int((time.monotonic() - t0) * 1000)

        await _write_call_log(
            db,
            buyer_id=buyer.id,
            protocol_id=protocol.id,
            key_id=pool_result.key.id,
            supplier_id=pool_result.key.supplier_id,
            epoch_id=epoch_id,
            response_status=upstream_resp.status_code,
            request_ms=elapsed_ms,
            was_self_served=True,
            was_refunded=False,
            gross_charge_micros=0,
            supplier_share_micros=0,
            jellynet_share_micros=0,
            buyer_discount_micros=0,
        )
        await db.commit()

        return JSONResponse(
            status_code=upstream_resp.status_code,
            content=upstream_resp.json() if upstream_resp.content else None,
            headers=dict(upstream_resp.headers),
        )

    max_retries = min(int(request.headers.get("X-Jellynet-Retries", "3")), 5)
    tried_key_ids: list[str] = []

    for attempt in range(max_retries):
        current_key = pool_result.key
        current_raw_secret = raw_secret
        current_pricing = pricing

        if attempt > 0:
            tried_key_ids.append(current_key.id)
            try:
                pool_result = await pick_key(db, buyer.id, protocol.id, est_cost, exclude_key_ids=tried_key_ids)
            except NoCapacityAvailable:
                break
            current_key = pool_result.key
            current_raw_secret = settings.key_enc_fernet.decrypt(
                current_key.secret_encrypted.encode()
            ).decode()
            current_pricing = await resolve_unit_price(db, protocol.id, current_key.id)
            charge = current_pricing.unit_price_micros

        async with db.begin():
            locked = await db.execute(
                select(Buyer).where(Buyer.id == buyer.id).with_for_update()
            )
            locked_buyer = locked.scalar_one()

            if locked_buyer.credit_balance_micros < charge:
                raise HTTPException(
                    status_code=402,
                    detail={
                        "code": "InsufficientCredit",
                        "message": (
                            f"Your balance ({locked_buyer.credit_balance_micros} µUSDC) "
                            f"is below the call cost ({charge} µUSDC). "
                            "Top up at /dashboard."
                        ),
                    },
                )

            t0 = time.monotonic()
            try:
                upstream_resp = await request.app.state.proxy_service.forward(
                    target_url=UPSTREAM_BASES.get(protocol.slug, ""),
                    api_key=current_raw_secret,
                    method=request.method,
                    path=path,
                    headers=dict(request.headers),
                    body=body_bytes or None,
                    query_string=request.url.query,
                )
            except httpx.RequestError as exc:
                raise HTTPException(status_code=502, detail=f"Upstream connection error: {exc}")

            elapsed_ms = int((time.monotonic() - t0) * 1000)

            if upstream_resp.status_code in (429,) or upstream_resp.status_code >= 500:
                await _write_call_log(
                    db,
                    buyer_id=buyer.id,
                    protocol_id=protocol.id,
                    key_id=current_key.id,
                    supplier_id=current_key.supplier_id,
                    epoch_id=epoch_id,
                    response_status=upstream_resp.status_code,
                    request_ms=elapsed_ms,
                    was_self_served=False,
                    was_refunded=True,
                    gross_charge_micros=0,
                    supplier_share_micros=0,
                    jellynet_share_micros=0,
                    buyer_discount_micros=0,
                )
                raise _RetryNeeded()

            await db.execute(
                update(Buyer)
                .where(Buyer.id == buyer.id)
                .values(credit_balance_micros=func.coalesce(Buyer.credit_balance_micros, 0) - charge)
            )
            await db.execute(
                update(SupplierKey)
                .where(SupplierKey.id == current_key.id)
                .values(remaining_quota_micros=func.coalesce(SupplierKey.remaining_quota_micros, 0) - charge)
            )
            await _write_call_log(
                db,
                buyer_id=buyer.id,
                protocol_id=protocol.id,
                key_id=current_key.id,
                supplier_id=current_key.supplier_id,
                epoch_id=epoch_id,
                response_status=upstream_resp.status_code,
                request_ms=elapsed_ms,
                was_self_served=False,
                was_refunded=False,
                gross_charge_micros=charge,
                supplier_share_micros=current_pricing.supplier_share_micros,
                jellynet_share_micros=current_pricing.jellynet_share_micros,
                buyer_discount_micros=current_pricing.buyer_discount_micros,
            )

        try:
            content = upstream_resp.json()
        except Exception:
            content = upstream_resp.text

        return JSONResponse(status_code=upstream_resp.status_code, content=content)

    raise HTTPException(
        status_code=503,
        detail={"code": "NoCapacityAvailable", "message": "All upstream attempts failed. You were not charged."},
    )


class _RetryNeeded(Exception):
    pass


async def _stream_response(
    request: Request,
    upstream_url: str,
    headers: dict,
    body_bytes: bytes,
    db: AsyncSession,
    buyer: Buyer,
    key: SupplierKey,
    protocol,
    pricing,
    was_self_served: bool,
    epoch_id: Optional[str],
) -> StreamingResponse:
    charge = 0 if was_self_served else pricing.unit_price_micros

    if not was_self_served:
        async with db.begin():
            locked = await db.execute(
                select(Buyer).where(Buyer.id == buyer.id).with_for_update()
            )
            locked_buyer = locked.scalar_one()
            if locked_buyer.credit_balance_micros < charge:
                raise HTTPException(
                    status_code=402,
                    detail={
                        "code": "InsufficientCredit",
                        "message": f"Balance ({locked_buyer.credit_balance_micros} µUSDC) < call cost ({charge} µUSDC).",
                    },
                )
            await db.execute(
                update(Buyer)
                .where(Buyer.id == buyer.id)
                .values(credit_balance_micros=func.coalesce(Buyer.credit_balance_micros, 0) - charge)
            )
            await db.execute(
                update(SupplierKey)
                .where(SupplierKey.id == key.id)
                .values(remaining_quota_micros=func.coalesce(SupplierKey.remaining_quota_micros, 0) - charge)
            )

    async def _generate() -> AsyncIterator[bytes]:
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream(
                    request.method,
                    upstream_url,
                    headers=headers,
                    content=body_bytes,
                ) as resp:
                    async for chunk in resp.aiter_bytes():
                        yield chunk
        except Exception as exc:
            logger.error("Stream error mid-flight: %s", exc)
            async with db.begin():
                await _write_call_log(
                    db,
                    buyer_id=buyer.id,
                    protocol_id=protocol.id,
                    key_id=key.id,
                    supplier_id=key.supplier_id,
                    epoch_id=epoch_id,
                    response_status=599,
                    request_ms=0,
                    was_self_served=was_self_served,
                    was_refunded=False,
                    gross_charge_micros=charge,
                    supplier_share_micros=pricing.supplier_share_micros if not was_self_served else 0,
                    jellynet_share_micros=pricing.jellynet_share_micros if not was_self_served else 0,
                    buyer_discount_micros=pricing.buyer_discount_micros if not was_self_served else 0,
                )
            return

        async with db.begin():
            await _write_call_log(
                db,
                buyer_id=buyer.id,
                protocol_id=protocol.id,
                key_id=key.id,
                supplier_id=key.supplier_id,
                epoch_id=epoch_id,
                response_status=200,
                request_ms=0,
                was_self_served=was_self_served,
                was_refunded=False,
                gross_charge_micros=charge,
                supplier_share_micros=pricing.supplier_share_micros if not was_self_served else 0,
                jellynet_share_micros=pricing.jellynet_share_micros if not was_self_served else 0,
                buyer_discount_micros=pricing.buyer_discount_micros if not was_self_served else 0,
            )

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
