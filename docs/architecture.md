# JellyNet — Architecture Overview

## System Components

**Universal Proxy** (`backend/routes/proxy.py`)
The single entry point for all API calls. Accepts requests at `/v1/{path}` with either an `Authorization: Bearer jn_xxx` header (buyer path) or an `X-Payment` header (x402 agent path). Routes to the appropriate handling flow, selects a supplier key, forwards to the upstream provider, and returns the response.

**Test Endpoint** (`backend/routes/test.py`)
A simplified proxy path for authenticated users to test live API calls through the JellyNet pool. Resolves protocol metadata from the DB, picks a supplier key, and returns the structured response with latency and cost breakdown.

**Routing Engine / Capacity Pool** (`services/pool.py`)
Given a protocol and estimated cost, selects a supplier key from the active pool. Self-serve detection: if the buyer owns a key for the requested protocol, their own key is preferred (free). Otherwise, a key is selected from the shared pool. Production routing uses weighted-random selection based on remaining quota.

**x402 Service** (`backend/services/x402_service.py`)
Implements the x402 payment protocol. Builds `402 Payment Required` responses advertising Solana (and optionally Base) as accepted payment networks. Encodes and decodes `X-Payment` headers (base64url-encoded payment payloads). Verifies payment expiry.

**Chain Adapters** (`backend/services/chains/`)
Pluggable chain implementations. `SolanaChainAdapter` verifies and settles USDC-SPL transactions via the CDP facilitator API. `BaseChainAdapter` handles EVM/Base. The factory (`factory.py`) returns the correct adapter based on the `network` field in the payment payload.

**Epoch Worker** (`backend/workers/epoch_worker.py`)
Runs every 8 hours (APScheduler). Closes the current epoch, aggregates `call_logs` by `(supplier_id, protocol_id)`, and writes one `LedgerEntry` credit per group. Opens the next epoch immediately. Idempotent — duplicate runs produce no extra ledger rows due to a unique constraint.

**Withdrawal Worker** (`backend/workers/withdrawal_worker.py`)
Runs every 5 minutes. Picks pending supplier withdrawal requests, checks available balance (credits minus debits minus in-flight), applies a KYC gate for large amounts, then executes an SPL USDC transfer using the platform hot wallet. On success, writes a ledger debit and marks the withdrawal confirmed.

---

## Request Flows

### Standard Buyer Call
```
Buyer → POST /v1/{path}  [Authorization: Bearer jn_xxx]
  → Auth middleware validates jn_xxx → resolves Buyer
  → Whitelist gate check
  → resolve_protocol() matches path/body to a Protocol row
  → estimate_unit_price() → pick_key() selects supplier key from pool
  → Balance check (row-locked Buyer read)
  → Forward to upstream provider
  → 2xx: debit buyer balance + supplier quota, write CallLog
  → 429/5xx: rollback, retry with next key (up to 3 attempts)
  → Return upstream response to buyer
```

### x402 Agent Call
```
AI Agent → POST /v1/{path}  [X-Payment: <base64url payload>]
  → x402_service.decode_payment_header() parses payload
  → x402_service.is_payment_expired() checks validBefore
  → chain.verify() — calls CDP to verify USDC tx on-chain
  → chain.settle() — calls CDP to settle the payment
  → pick_key() selects supplier key (no buyer account)
  → Forward to upstream provider
  → Write CallLog + x402 JellyNet credit ledger entry
  → Return upstream response to agent
```

### No Auth → 402 Response
```
Request with no Authorization and no X-Payment header
  → x402_service.build_402_response() constructs payment requirements
  → Returns HTTP 402 with accepts[] listing Solana (+ Base if flag on)
  → Agent reads accepts[], submits USDC payment, retries with X-Payment header
```

### Epoch Settlement
```
APScheduler fires every 8 hours
  → _ensure_open_epoch(): create epoch if none exists
  → _close_expired_epochs(): find open epoch past ends_at
  → Aggregate call_logs: GROUP BY (supplier_id, protocol_id), SUM(supplier_share_micros)
  → Write LedgerEntry credits per supplier/protocol group
  → Mark epoch closed with payout_total_micros
  → _open_next_epoch(): create next 8-hour epoch
```

### Supplier Withdrawal
```
Supplier requests withdrawal → Withdrawal row created (status=pending)
APScheduler fires every 5 minutes
  → _get_available_balance(): credits - debits - in-flight
  → KYC gate: if amount > threshold and kyc_completed=False → status=pending_kyc
  → Mark status=processing (row-locked)
  → _execute_solana_transfer(): build SPL transfer, sign with hot wallet, submit
  → Poll for confirmation (max 60s)
  → On confirm: write LedgerEntry debit, mark status=confirmed
  → On failure: mark status=failed with reason
```

---

## Data Model (key tables)

| Table | Purpose |
|-------|---------|
| `protocols` | API provider catalog — routing rules, pricing, test payloads |
| `keys` (SupplierKey) | Supplier API credentials — encrypted, quota-tracked |
| `call_logs` | Per-call record — charges, shares, epoch linkage |
| `epochs` | 8-hour settlement windows |
| `ledger_entries` | Double-entry credits/debits for suppliers and platform |
| `withdrawals` | Supplier withdrawal requests and state machine |
| `buyers` | Buyer accounts with credit balances |

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python / FastAPI on Fly.io |
| Frontend | Next.js / TypeScript on Vercel |
| Database | PostgreSQL (Neon) via SQLAlchemy async |
| Auth | NextAuth v5 (Google OAuth) |
| Blockchain | Solana — solana-py, solders, Phantom wallet |
| Payments | x402 protocol (CDP facilitator) + USDC-SPL |
| Workers | APScheduler (in-process) |
| Key encryption | AES-256 (Fernet) |
