"""
tests/test_x402.py
Tests for the x402 payment gate in the universal proxy:
  - 402 response shape when no payment header is present
  - Verify+settle path forwards request on success
  - Verify failure returns 402 again
  - Base path: flag-off raises error, flag-on works
"""
from __future__ import annotations

import sys
import os
import base64
import json
import time
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Fixtures / helpers ────────────────────────────────────────────────────────

def _make_settings(x402_base: bool = False) -> MagicMock:
    s = MagicMock()
    s.cdp_facilitator_url = "https://fake-cdp.example.com"
    s.cdp_api_key = ""
    s.solana_usdc_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
    s.base_usdc_address = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
    s.x402_base = x402_base
    s.x402_version = 1
    s.x402_timeout_seconds = 60
    s.platform_payment_address = "platform_sol_addr"
    return s


def _make_protocol(slug: str = "openai-gpt4o", default_retail_micros: int = 5000) -> MagicMock:
    p = MagicMock()
    p.slug = slug
    p.id = str(uuid.uuid4())
    p.default_retail_micros = default_retail_micros
    return p


def _build_payment_header(
    tx_hash: str = "fake_tx_hash",
    from_addr: str = "buyer_sol_addr",
    to_addr: str = "platform_sol_addr",
    value: int = 5000,
    network: str = "solana",
    valid_before_offset: int = 60,
) -> str:
    payload = {
        "x402Version": 1,
        "scheme": "exact",
        "network": network,
        "payload": {
            "signature": tx_hash,
            "authorization": {
                "from": from_addr,
                "to": to_addr,
                "value": str(value),
                "validAfter": str(int(time.time()) - 5),
                "validBefore": str(int(time.time()) + valid_before_offset),
            },
        },
    }
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode())
    return encoded.rstrip(b"=").decode()


# ── x402 Service tests ────────────────────────────────────────────────────────

def test_build_402_response_shape_solana_only():
    """402 response without Base flag has x402Version and one solana entry."""
    from services.x402_service import X402Service
    s = _make_settings(x402_base=False)
    svc = X402Service(s)
    protocol = _make_protocol()

    body = svc.build_402_response(protocol, "/v1/chat/completions")

    assert body["x402Version"] == 1
    assert "error" in body
    assert len(body["accepts"]) == 1
    entry = body["accepts"][0]
    assert entry["network"] == "solana"
    assert entry["scheme"] == "exact"
    assert entry["maxAmountRequired"] == str(protocol.default_retail_micros)
    assert entry["payTo"] == s.platform_payment_address
    assert entry["asset"] == "USDC"
    assert entry["resource"] == "/v1/chat/completions"


def test_build_402_response_includes_base_when_flag_on():
    """402 response with Base flag has both solana and base-mainnet entries."""
    from services.x402_service import X402Service
    s = _make_settings(x402_base=True)
    svc = X402Service(s)
    protocol = _make_protocol()

    body = svc.build_402_response(protocol, "/v1/chat/completions")

    networks = {e["network"] for e in body["accepts"]}
    assert "solana" in networks
    assert "base-mainnet" in networks
    assert len(body["accepts"]) == 2


def test_base_path_raises_when_flag_off():
    """get_chain('base') raises ValueError when x402_base=False."""
    from services.chains.factory import get_chain
    s = _make_settings(x402_base=False)
    with pytest.raises(ValueError, match="x402_base"):
        get_chain("base", s)


def test_base_path_works_when_flag_on():
    """get_chain('base') returns a BaseChainAdapter when x402_base=True."""
    from services.chains.factory import get_chain
    from services.chains.base import BaseChainAdapter
    s = _make_settings(x402_base=True)
    adapter = get_chain("base", s)
    assert isinstance(adapter, BaseChainAdapter)


# ── X-Payment header encoding/decoding ───────────────────────────────────────

def test_encode_decode_roundtrip():
    """encode_payment_header → decode_payment_header is a lossless roundtrip."""
    from services.x402_service import X402Service
    s = _make_settings()
    svc = X402Service(s)

    header = svc.encode_payment_header(
        tx_hash="abc123",
        from_address="from_addr",
        to_address="to_addr",
        value=5000,
        network="solana",
    )
    decoded = svc.decode_payment_header(header)
    details = svc.extract_payment_details(decoded)

    assert details["tx_hash"] == "abc123"
    assert details["from_address"] == "from_addr"
    assert details["to_address"] == "to_addr"
    assert details["value"] == 5000
    assert details["network"] == "solana"


def test_is_payment_expired_future():
    from services.x402_service import X402Service
    s = _make_settings()
    svc = X402Service(s)
    future = int(time.time()) + 120
    assert svc.is_payment_expired(future) is False


def test_is_payment_expired_past():
    from services.x402_service import X402Service
    s = _make_settings()
    svc = X402Service(s)
    past = int(time.time()) - 120
    assert svc.is_payment_expired(past) is True


# ── Verify + settle path (mocked chain) ──────────────────────────────────────

@pytest.mark.asyncio
async def test_verify_success_settle_success_returns_verify_result():
    """
    When CDP verify returns isValid=True and settle returns success=True,
    the chain adapter reports both successes.
    """
    from services.chains.base_chain import VerifyPayload, SettlePayload
    from services.chains.solana import SolanaChainAdapter

    s = _make_settings()
    adapter = SolanaChainAdapter(s)

    verify_payload = VerifyPayload(
        tx_hash="good_tx",
        from_address="buyer",
        to_address="platform_sol_addr",
        amount=5000,
        network="solana",
    )
    settle_payload = SettlePayload(
        tx_hash="good_tx",
        network="solana",
        raw_payload={"x402Version": 1, "scheme": "exact"},
    )

    mock_verify_resp = MagicMock()
    mock_verify_resp.json.return_value = {"isValid": True}
    mock_settle_resp = MagicMock()
    mock_settle_resp.json.return_value = {"success": True, "transaction": "settled_tx_id"}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=[mock_verify_resp, mock_settle_resp])
        mock_client_cls.return_value = mock_client

        verify_result = await adapter.verify(verify_payload)
        settle_result = await adapter.settle(settle_payload)

    assert verify_result.is_valid is True
    assert verify_result.error is None
    assert settle_result.success is True
    assert settle_result.transaction_id == "settled_tx_id"


@pytest.mark.asyncio
async def test_verify_failure_returns_invalid_result():
    """CDP verify failure returns is_valid=False with error reason."""
    from services.chains.base_chain import VerifyPayload
    from services.chains.solana import SolanaChainAdapter

    s = _make_settings()
    adapter = SolanaChainAdapter(s)

    payload = VerifyPayload(
        tx_hash="bad_tx",
        from_address="buyer",
        to_address="wrong_address",
        amount=100,
        network="solana",
    )

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"isValid": False, "invalidReason": "receiver_mismatch"}

    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client_cls.return_value = mock_client

        result = await adapter.verify(payload)

    assert result.is_valid is False
    assert result.error == "receiver_mismatch"


@pytest.mark.asyncio
async def test_expired_payment_header_returns_error():
    """Payment header with past validBefore is detected as expired."""
    from services.x402_service import X402Service
    s = _make_settings()
    svc = X402Service(s)

    header = _build_payment_header(valid_before_offset=-120)
    decoded = svc.decode_payment_header(header)
    details = svc.extract_payment_details(decoded)

    assert svc.is_payment_expired(details["valid_before"]) is True


def test_invalid_payment_header_raises_value_error():
    """decode_payment_header raises ValueError on garbage input."""
    from services.x402_service import X402Service
    s = _make_settings()
    svc = X402Service(s)

    with pytest.raises(ValueError, match="Invalid X-Payment header"):
        svc.decode_payment_header("not_valid_base64!!!")
