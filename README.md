# JellyNet — Capacity-Sharing Marketplace for AI APIs

> One universal key. Multiple AI providers. Pay-per-call on Solana.

**Live product:** [jellynet.net](https://jellynet.net)
**Twitter:** [@jellynet_](https://twitter.com/jellynet_)

---

## The Problem

The AI API economy is fragmented. Developers juggle separate keys, billing dashboards, and rate limits across multiple providers. When one provider rate-limits you at 3 AM, your app goes down. And AI agents — autonomous systems that need API access — can't even pay for compute without a human setting up billing first.

Meanwhile, thousands of developers and teams are sitting on unused API credits that expire every month.

## The Solution

JellyNet is a two-sided capacity-sharing marketplace:

**For buyers:** One universal API key (`jn_xxx`) that routes to multiple AI providers. No more juggling. If one provider is down or rate-limited, JellyNet automatically routes to the next available key in the pool.

**For suppliers:** Contribute your idle API keys and earn USDC on Solana for every call your key serves. Your own calls through JellyNet are free — you only pay when consuming other suppliers' capacity.

**For AI agents:** Pay per-call via x402 payment headers. No sign-up, no OAuth, no credit card. Just attach a USDC payment header and make the API call.

## Architecture

```
┌─────────────┐     ┌──────────────────────────────┐     ┌──────────────┐
│  Developer   │────▶│    JellyNet Universal         │────▶│   OpenAI     │
│  (fiat/USDC) │     │         Proxy                 │────▶│   Anthropic  │
└─────────────┘     │                               │────▶│   Gemini     │
                    │  ┌────────────────────────┐   │────▶│   Groq       │
┌─────────────┐     │  │   Routing Engine       │   │────▶│   Mistral    │
│  AI Agent    │────▶│  │   (quota-weighted)     │   │────▶│   + more     │
│  (x402/USDC) │     │  └────────────────────────┘   │     └──────────────┘
└─────────────┘     │                               │
                    │  ┌────────────────────────┐   │     ┌──────────────┐
                    │  │  Capacity Pool         │   │     │   Solana     │
                    │  │  (supplier keys)       │   │────▶│  USDC-SPL    │
                    │  └────────────────────────┘   │     │  settlements  │
                    │                               │     └──────────────┘
                    │  ┌────────────────────────┐   │
                    │  │  Epoch Settlement      │   │
                    │  │  (USDC-SPL payouts)    │   │
                    │  └────────────────────────┘   │
                    └──────────────────────────────┘
```

## Solana Integration

JellyNet uses Solana as the settlement layer:

- **x402 Payments:** AI agents include a `X-Payment` header with a signed USDC-SPL transaction. JellyNet verifies the payment on-chain before proxying the API call. No accounts, no OAuth — just pay and call.

- **Epoch Settlement:** Supplier earnings are calculated per epoch. At epoch close, the system distributes USDC-SPL proportionally based on calls served. Payouts are batched for gas efficiency.

- **Wallet Connect:** Human users connect via Phantom wallet for USDC deposits and withdrawal management.

## Key Economics

| Role | What they do | What they earn/save |
|------|-------------|-------------------|
| Supplier | Contribute idle API keys | 60% of revenue per call served |
| Buyer | Use universal key | 30% discount vs retail pricing |
| JellyNet | Route + settle | 10% platform fee |

**Self-serve rule:** When you contribute your own keys, your own calls are FREE. You only pay when consuming other suppliers' capacity. Bring your keys, use them free, sell the surplus.

## Tech Stack

- **Backend:** Python / Flask on Fly.io
- **Frontend:** Next.js / TypeScript on Vercel
- **Database:** PostgreSQL on Neon
- **Auth:** NextAuth with Google OAuth
- **Blockchain:** Solana (solana-py, Phantom wallet integration)
- **Payments:** x402 protocol for agent payments, USDC-SPL for settlements
- **Workers:** APScheduler for epoch settlement and withdrawal processing

## Repository Structure

```
backend/
├── integrations/
│   ├── torque_mcp.py         # Torque MCP — exposes JellyNet marketplace as MCP tools
│   ├── zerion_agent.py       # Zerion CLI — on-chain wallet analysis for x402 verification
│   └── lpagent.py            # LPAgent.io — DeFi analytics context for AI agents
├── routes/
│   ├── proxy.py              # Universal API proxy — routes calls to best available key
│   └── test.py               # Test endpoint — live API call flow for evaluation
├── services/
│   └── x402_service.py       # x402 payment verification and agent payment flow
├── workers/
│   ├── epoch_worker.py       # Epoch settlement — calculates and distributes supplier earnings
│   └── withdrawal_worker.py  # USDC-SPL withdrawal processing via Solana
├── models/
│   ├── protocol.py           # API provider protocol definitions
│   ├── supplier_key.py       # Supplier key management
│   └── call_log.py           # API call logging and tracking
└── tests/
    ├── test_proxy.py         # Proxy flow tests (charge, retry, self-serve)
    ├── test_x402.py          # x402 payment gate tests
    └── test_epoch.py         # Epoch settlement and payout tests

frontend/
├── app/
│   ├── test/page.tsx         # Test call interface — run live API calls
│   └── marketplace/page.tsx  # Browse available providers and pool capacity
├── components/
│   ├── TestCallPanel.tsx     # Test call UI panel with step timeline
│   ├── SolanaProvider.tsx    # Solana wallet provider (Phantom / wallet adapter)
│   ├── WalletSetupModal.tsx  # Phantom wallet connect flow
│   └── marketplace/
│       └── MarketplaceCard.tsx  # Endpoint card (grid and list view)
└── lib/
    └── chain-utils.ts        # Blockchain utility functions (explorer links, formatting)

docs/
└── architecture.md           # Full architecture overview
```

## Integrations

JellyNet integrates with several Solana ecosystem tools:

- **Torque MCP** — Exposes JellyNet's marketplace as discoverable MCP tools for AI agents. Agents can list models, check pricing, and make API calls through the MCP interface.
- **Zerion CLI** — On-chain wallet analysis for x402 payment verification. Used to check agent wallet balances and verify USDC-SPL transactions.
- **LPAgent.io** — DeFi analytics API providing LP position data and yield analytics, giving AI agents financial context alongside API access.

## Running Locally

```bash
# Backend
cd backend
pip install -r requirements.txt
flask run

# Frontend
cd frontend
npm install
npm run dev
```

Requires environment variables for database, Solana wallet, and upstream API keys. See `.env.example` for the full list.

## Status

- ✅ Universal proxy with multi-provider routing
- ✅ x402 agent payment path (Solana)
- ✅ Epoch settlement with USDC-SPL payouts
- ✅ Protocol catalog (LLMs, image gen, speech, vision, embeddings, crypto)
- ✅ Supplier key management with self-serve economics
- ✅ Marketplace with provider browsing and pool visibility
- ✅ Wallet connect via Phantom
- 🔜 Native-call mode (lower latency)
- 🔜 MCP web-session sharing

## License

© 2026 JellyNet. Shared for Solana Frontier Hackathon evaluation only. See [LICENSE](./LICENSE).

---

**Contact:** admin@jellynet.net | [@jellynet_](https://twitter.com/jellynet_)
