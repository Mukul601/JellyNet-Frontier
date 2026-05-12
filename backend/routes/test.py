"""
JellyNet — routes/test.py
Direct LLM proxy test endpoint for authenticated users.

POST /api/test/call — pick a supplier key for the requested protocol, forward a
                       test call, log it, debit the user's balance.

Auth logic is DB-driven via Protocol.base_url, auth_header, auth_prefix, auth_query_param.
"""
from __future__ import annotations

import json
import time
import uuid
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from middleware.auth_middleware import get_current_user
from models.call_log import CallLog
from models.epoch import Epoch
from models.protocol import Protocol
from models.supplier_key import SupplierKey
from models.user import User
from payments.models import UserBalance
from services.pool import NoCapacityAvailable, pick_key
from services.pricing import estimate_unit_price, resolve_unit_price

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/test", tags=["test"])

_ANTHROPIC_EXTRA_HEADERS = {"anthropic-version": "2023-06-01"}


class TestCallRequest(BaseModel):
    protocol: str = "openai-gpt4o"  # exact DB slug
    model: str = ""
    prompt: str = "Hello, this is a test call from JellyNet"
    network: str = "testnet"


async def _get_open_epoch_id(db: AsyncSession) -> Optional[str]:
    result = await db.execute(select(Epoch).where(Epoch.status == "open").limit(1))
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
    gross_charge_micros: int,
    supplier_share_micros: int,
    jellynet_share_micros: int,
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
        was_self_served=False,
        was_refunded=False,
        gross_charge_micros=gross_charge_micros,
        supplier_share_micros=supplier_share_micros,
        jellynet_share_micros=jellynet_share_micros,
        buyer_discount_micros=0,
    )
    db.add(log)
    await db.flush()


def _build_upstream_url(protocol: Protocol, raw_key: str) -> str:
    base = (protocol.base_url or "").rstrip("/")
    endpoint = (protocol.test_endpoint or "").lstrip("/")
    url = f"{base}/{endpoint}" if endpoint else base

    if protocol.auth_query_param:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}{protocol.auth_query_param}={raw_key}"
    return url


def _build_auth_headers(protocol: Protocol, raw_key: str) -> dict[str, str]:
    headers: dict[str, str] = {"Content-Type": "application/json"}

    if protocol.auth_header:
        if protocol.auth_prefix:
            headers[protocol.auth_header] = f"{protocol.auth_prefix} {raw_key}"
        else:
            headers[protocol.auth_header] = raw_key

    if protocol.slug == "anthropic-claude":
        headers.update(_ANTHROPIC_EXTRA_HEADERS)

    return headers


def _inject_prompt(test_payload_str: Optional[str], prompt: str, model: str) -> dict:
    if not test_payload_str:
        return {"prompt": prompt}

    payload: dict = json.loads(test_payload_str)

    if model and "model" in payload:
        payload["model"] = model

    # OpenAI / Groq / Mistral / Together / Anthropic style
    if "messages" in payload and isinstance(payload["messages"], list):
        for msg in payload["messages"]:
            if msg.get("role") == "user":
                msg["content"] = prompt
        return payload

    # Gemini style
    if "contents" in payload:
        for content in payload["contents"]:
            for part in content.get("parts", []):
                if "text" in part:
                    part["text"] = prompt
        return payload

    # Cohere style
    if "message" in payload:
        payload["message"] = prompt
        return payload

    payload["prompt"] = prompt
    return payload


def _extract_response_text(resp_json: dict) -> str:
    # OpenAI-compatible (openai, groq, mistral, together)
    choices = resp_json.get("choices")
    if choices and isinstance(choices, list):
        return choices[0].get("message", {}).get("content", "") or choices[0].get("text", "")

    # Anthropic
    content = resp_json.get("content")
    if content and isinstance(content, list):
        return content[0].get("text", "")

    # Gemini
    candidates = resp_json.get("candidates")
    if candidates and isinstance(candidates, list):
        parts = candidates[0].get("content", {}).get("parts", [])
        if parts:
            return parts[0].get("text", "")

    # Cohere
    if "text" in resp_json:
        return resp_json["text"]

    return json.dumps(resp_json, indent=2)[:2000]


@router.post("/call")
async def test_call(
    body: TestCallRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> JSONResponse:
    # 1. Resolve protocol from DB by exact slug
    proto_result = await db.execute(
        select(Protocol).where(Protocol.slug == body.protocol, Protocol.is_active == True)  # noqa: E712
    )
    protocol = proto_result.scalar_one_or_none()
    if not protocol:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown or inactive protocol '{body.protocol}'.",
        )

    if not protocol.base_url:
        raise HTTPException(
            status_code=503,
            detail=f"Protocol '{body.protocol}' is not yet fully configured. Missing base_url.",
        )

    # 2. Determine model to use
    popular: list[str] = json.loads(protocol.popular_models) if protocol.popular_models else []
    model = body.model or (popular[0] if popular else "")

    # 3. Estimate cost and pick a key from the pool
    # Production routing uses weighted-random selection based on remaining quota
    est_cost = await estimate_unit_price(db, protocol.id)
    try:
        pool_result = await pick_key(db, None, protocol.id, est_cost)
    except NoCapacityAvailable:
        return JSONResponse(
            status_code=404,
            content={"detail": f"No supplier keys available for protocol '{body.protocol}'. Add one from your dashboard."},
        )

    pricing = await resolve_unit_price(db, protocol.id, pool_result.key.id)
    charge = pricing.unit_price_micros

    # 4. Check user balance (skip if self-serve)
    if not pool_result.was_self_served:
        balance_row = (await db.execute(
            select(UserBalance).where(UserBalance.user_id == current_user.id)
        )).scalar_one_or_none()
        available = balance_row.balance_usdca if balance_row else 0
        if available < charge:
            return JSONResponse(
                status_code=402,
                content={"detail": "Insufficient credits"},
            )

    # 5. Decrypt key
    raw_secret = settings.key_enc_fernet.decrypt(
        pool_result.key.secret_encrypted.encode()
    ).decode()

    # 6. Build upstream request from protocol metadata
    upstream_url = _build_upstream_url(protocol, raw_secret)
    headers = _build_auth_headers(protocol, raw_secret)
    method = (protocol.test_method or "POST").upper()

    upstream_body: Optional[dict] = None
    if method == "POST":
        upstream_body = _inject_prompt(protocol.test_payload, body.prompt, model)
        if model and "model" in (upstream_body or {}):
            upstream_body["model"] = model

    epoch_id = await _get_open_epoch_id(db)
    t0 = time.monotonic()

    # 7. Make upstream call
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if method == "GET":
                upstream_resp = await client.get(upstream_url, headers=headers)
            else:
                upstream_resp = await client.post(upstream_url, headers=headers, json=upstream_body)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Upstream connection error: {exc}")

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    # 8. Extract response text
    response_text: str = ""
    try:
        resp_json = upstream_resp.json()
        response_text = _extract_response_text(resp_json)
    except Exception:
        response_text = upstream_resp.text[:2000]

    # 9. Write call log and debit balance
    await _write_call_log(
        db,
        buyer_id=None,
        protocol_id=protocol.id,
        key_id=pool_result.key.id,
        supplier_id=pool_result.key.supplier_id,
        epoch_id=epoch_id,
        response_status=upstream_resp.status_code,
        request_ms=elapsed_ms,
        gross_charge_micros=charge if not pool_result.was_self_served else 0,
        supplier_share_micros=pricing.supplier_share_micros if not pool_result.was_self_served else 0,
        jellynet_share_micros=pricing.jellynet_share_micros if not pool_result.was_self_served else 0,
    )

    if not pool_result.was_self_served and charge > 0:
        await db.execute(
            update(UserBalance)
            .where(UserBalance.user_id == current_user.id)
            .values(balance_usdca=func.coalesce(UserBalance.balance_usdca, 0) - charge)
        )
        await db.execute(
            update(SupplierKey)
            .where(SupplierKey.id == pool_result.key.id)
            .values(remaining_quota_micros=func.coalesce(SupplierKey.remaining_quota_micros, 0) - charge)
        )
    await db.commit()

    if upstream_resp.status_code >= 400:
        return JSONResponse(
            status_code=upstream_resp.status_code,
            content={"detail": f"Upstream error {upstream_resp.status_code}: {response_text}"},
        )

    return JSONResponse(
        status_code=200,
        content={
            "response": response_text,
            "latency_ms": elapsed_ms,
            "protocol": body.protocol,
            "model": model,
            "key_id_truncated": pool_result.key.id[:8],
            "cost_micros": charge if not pool_result.was_self_served else 0,
        },
    )


@router.post("/run")
async def run_test() -> JSONResponse:
    return JSONResponse(
        status_code=410,
        content={"detail": "This endpoint is deprecated. Use POST /api/test/call instead."},
    )
