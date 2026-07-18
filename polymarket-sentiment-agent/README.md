# Poly Agent — Sentiment Trading on Polymarket

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Poly Agent is a **modular sentiment-trading system** for [Polymarket](https://polymarket.com):
it ingests crypto news, estimates probabilities with rigorous math (not LLM
guessing), compares them to live market prices, and paper-trades when the edge
is large enough. It also exposes a **pay-per-call API** via the [x402](https://x402.org)
protocol so other apps and AI agents can buy premium trade intelligence with
USDC on Base Sepolia.

Ships in **paper-trading mode** for the agent itself (no real Polymarket bets).
The **x402 paywall** is live on one premium endpoint for workshop demos and
external integrations.

---

## What we built

| Layer | What it is | Status |
| --- | --- | --- |
| **Scout** | RSS + CryptoPanic news ingestion, URL-deduped | Working |
| **Quant** | LLM extracts sentiment; Python computes Bayesian posterior | Live (heuristic fallback; Groq optional) |
| **Oracle** | Polymarket Gamma + CLOB price/order-book snapshots | Watching 5 crypto markets |
| **Overseer** | Edge threshold, max size, drawdown kill switch | Enforced every cycle |
| **Trader** | Idempotent paper executor | Live; LIVE signing stubbed for safety |
| **Command Center** | React dashboard — portfolio, signals, trade log, kill switch | Served from same URL |
| **Public API** | `GET /api/public/ping` — free, for Lovable / curl / webhooks | Live |
| **x402 paywall** | `GET /api/trade/{id}/rationale` — $0.01 USDC/call, Base Sepolia | Live |
| **Workshop skills** | `email-triage`, `x402-pay`, Gmail connector docs in [CLAUDE.md](./CLAUDE.md) | In `.cursor/skills/` |
| **CI + deploy** | GitHub Actions, Docker, Render (blueprint at repo root `render.yaml`) | Auto on push |

**Repository:** https://github.com/priyanshshahh/polymarket-sentiment-agent

---

## Why this is useful

**For trading research**
- Demonstrates how to trade on **information asymmetry** without letting an LLM
  pick prices. The LLM only labels news; the math decides.
- Full **audit trail**: every trade links to the headline, signal, and market
  snapshot at decision time — essential for post-mortems.

**For builders**
- A working template for **decoupled agent architecture** (ingest → analyze →
  price → risk → execute) that survives partial failures.
- **Zero-key demo path**: runs on free RSS + Polymarket public APIs + heuristic NLP.

**For the Headless Vibe workshop**
- **Public endpoint** (`/api/public/ping`) you can hit from Lovable or any HTTP client.
- **x402 micropayments**: machines and apps pay $0.01 USDC per premium API call
  with no accounts or API keys — HTTP 402 is the invoice.
- **Agent skills** so Claude can triage email (`/email`) or pay for your API
  (`.cursor/skills/x402-pay`).

**For monetization experiments**
- Premium data (trade rationale) is gated behind x402. You receive USDC directly
  to your wallet; the facilitator settles on-chain.

---

## x402 wallet (Base Sepolia)

| Field | Value |
| --- | --- |
| **EVM address** | `0x5190715b3aFd1076b1416F20e7E64F53B90e054e` |
| **USDC balance** | **20 USDC** (testnet, as of last on-chain check) |
| **Network** | Base Sepolia (`eip155:84532`) |
| **USDC contract** | `0x036CbD53842c5426634e7929541eC2318f3dCF7e` |
| **Facilitator** | https://x402.org/facilitator |

Check balance anytime:

```bash
# On-chain (USDC ERC-20 balanceOf)
curl -s -X POST https://sepolia.base.org \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"eth_call","params":[{"to":"0x036CbD53842c5426634e7929541eC2318f3dCF7e","data":"0x70a082310000000000000000000000005190715b3afd1076b1416f20e7e64f53b90e054e"},"latest"],"id":1}'
```

Fund more testnet USDC: [Circle faucet](https://faucet.circle.com/) → **Base Sepolia**.

---

## Table of contents

- [What we built](#what-we-built)
- [Why this is useful](#why-this-is-useful)
- [x402 wallet (Base Sepolia)](#x402-wallet-base-sepolia)
- [What it does](#what-it-does)
- [Why this design](#why-this-design)
- [Architecture](#architecture)
- [The math](#the-math-bayesian-update-against-market-price)
- [Data model](#data-model)
- [API reference](#api-reference)
- [x402 monetization (workshop)](#x402-monetization-workshop)
- [Workshop skills & Gmail](#workshop-skills--gmail)
- [Configuration](#configuration)
- [Running locally](#running-locally)
- [Deployment](#deployment)
- [Going live with real money](#going-live-with-real-money-do-not-rush-this)
- [How to read the dashboard](#how-to-read-the-dashboard)
- [Extending the agent](#extending-the-agent)
- [Troubleshooting](#troubleshooting)

---

## What it does

Every 30 seconds, the agent runs one cycle:

1. **Scout** pulls fresh news from RSS feeds and (optionally) CryptoPanic.
2. **Quant** sends each headline to an LLM, which returns a structured
   `{sentiment, confidence, topic, entities}` JSON.
3. **Oracle** fetches the current Polymarket order book for a curated set
   of crypto/macro markets.
4. **Bayesian update** treats the *market price* as the prior probability
   and the news as evidence, producing a posterior.
5. **Overseer** gates the trade: edge must clear a threshold, confidence
   must clear a floor, max position size and daily drawdown limits enforced.
6. **Trader** executes idempotently. In paper mode it simulates fills at
   the best ask. In live mode it would sign EIP-712 orders against the
   Polymarket CLOB (stubbed in MVP).
7. **Mark-to-market** updates unrealized PnL on open positions.

Everything that happens is logged to a SQLite database with full lineage,
so every trade is one SQL query away from a complete post-mortem.

---

## Why this design

Three principles drove every architectural choice:

### 1. Separation of LLM and math
The LLM is used **only as an NLP parser**. It extracts structured fields:
sentiment label, its confidence in that label, the topic. It never produces
a probability, a price target, or a trade decision. All probability math
happens in deterministic Python (`bayesian_update()`), because LLMs
hallucinate confidence and have no calibration for tail events.

### 2. Idempotent execution
Network calls fail; transactions get stuck. Every trade plan derives a
deterministic `idem_key = f"{condition_id}:{outcome}:{signal_id}"`. The
`trades.idem_key` column has a `UNIQUE` constraint. If the orchestrator
retries the same signal, the DB swallows the duplicate insert and the
trade fires exactly once.

### 3. Single source of truth
Every decision the agent makes writes one row that joins to its causes:

```
Trade  →  Signal  →  NewsItem        (why we decided)
       ↘  MarketSnapshot              (what the market looked like)
```

The dashboard's "click any trade → rationale drawer" is a single
`GET /api/trade/{id}/rationale` that reconstructs the full causal chain.

### 4. Decoupled modules
Each system role lives in its own file under `backend/app/modules/`.
If the Scout's RSS provider crashes, the Trader and Overseer keep running
on cached state. The orchestrator wraps every sub-step in `try/except`.

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                          ORCHESTRATOR LOOP                              │
│                       (asyncio task, 30s tick)                          │
└────────────────────────────────────────────────────────────────────────┘
        │
        ├──▶  SCOUT  ─────────────▶  news_items  (URL-deduped)
        │    RSS + CryptoPanic
        │
        ├──▶  QUANT  ─────────────▶  signals   (sentiment, conf, topic)
        │    LLM extract → JSON
        │    (Groq / OpenAI / Anthropic / heuristic fallback)
        │
        ├──▶  ORACLE  ────────────▶  market_snapshots
        │    Polymarket Gamma + CLOB
        │
        ├──▶  Match signal → market
        │    posterior = bayes(market_price, sentiment, conf)
        │    edge = posterior − market_price
        │
        ├──▶  OVERSEER  ──────────▶  log_events
        │    edge ≥ threshold?
        │    confidence ≥ floor?
        │    size ≤ max?
        │    drawdown OK?
        │    kill switch off?
        │
        ├──▶  TRADER  ────────────▶  trades     (idem-keyed)
        │    PAPER: simulated fill at best ask
        │    LIVE:  EIP-712 sign + CLOB submit  (stubbed)
        │
        └──▶  Mark-to-market open positions
```

### Module responsibilities

| File | Role | What it owns |
| --- | --- | --- |
| `app/modules/ingestion.py` | **Scout** | RSS (CoinDesk, Cointelegraph, Decrypt) + optional CryptoPanic. Dedupes by URL via DB UNIQUE constraint. Filters by keyword to keep DB tight. |
| `app/modules/intelligence.py` | **Quant** | LLM extraction (Groq → OpenAI → Anthropic → heuristic chain). Pure-Python Bayesian update in log-odds space. Heuristic uses a curated bullish/bearish word list so the agent works with zero API keys. |
| `app/modules/market.py` | **Oracle** | Polymarket Gamma API for market discovery, CLOB API for `/midpoint`, `/price?side=BUY|SELL`. Snapshots all watched markets every cycle. |
| `app/modules/risk.py` | **Overseer** | Trade plan validation, kill switch with DB-backed state, daily drawdown auto-kill, structured event log. |
| `app/modules/execution.py` | **Trader** | Paper executor with idempotency. Live mode raises `NotImplementedError` — intentional safety. |
| `app/orchestrator.py` | **Conductor** | The asyncio loop. Wires every module together. Each step is independently restartable. |
| `app/api/routes.py` | **REST API** | Dashboard endpoints: portfolio, trades, signals, news, markets, equity curve, kill switch, rationale, run-once. |
| `app/main.py` | **Entry point** | FastAPI app, lifespan hooks (DB init + loop start/stop), static SPA serving. |

---

## The math: Bayesian update against market price

This is the core. Most "AI trading" demos ask GPT for a price prediction.
That's terrible — LLMs are uncalibrated. Instead, we:

1. The LLM emits `{sentiment ∈ {bullish, bearish, neutral}, confidence ∈ [0,1]}`.
2. Map sentiment + confidence to a **likelihood ratio**:

```python
if sentiment == "bullish":
    LR = 1 + 4 * confidence            # 1.0 .. 5.0
elif sentiment == "bearish":
    LR = 1 / (1 + 4 * confidence)      # 1.0 .. 0.2
else:
    LR = 1.0
```

3. Use the **market price as the prior**, do the Bayes update in
   log-odds space (numerically stable):

```python
log_odds_post = log(p_mkt / (1 − p_mkt)) + log(LR)
posterior     = 1 / (1 + exp(−log_odds_post))
edge          = posterior − p_mkt
```

Why market-price-as-prior? Because the market price *is* the consensus
probability. Bullish news shouldn't push us to "BTC has a 22% chance of
hitting $150K" — it should push us from "market thinks 1%" to "now I think
1.3%, which is still a 30% relative mispricing."

The LR is intentionally capped (max ~5×). Even maximum-confidence bullish
news only shifts the posterior modestly. We're sentiment traders, not
oracles.

Worked example: BTC market is priced at 1% YES. A bullish-confidence-0.8
news article hits. `LR = 4.2`. New posterior = ~4.1%. Edge = +3.1%.
If our threshold is 8%, we **don't trade**. If the article is more
explosive (confidence 0.95 → LR 4.8 → posterior ~4.6%, edge 3.6%) — still
no trade. Conservative.

---

## Data model

Five tables (SQLite, single file at `/data/doa.db` in production):

### `news_items`
Raw scraped articles. `url` is `UNIQUE` for dedup.

### `signals`
LLM extractions joined to news. Stores `prior=0.5`-based posterior for
analytics, but the trade-time posterior uses the market price as prior
(see [the math](#the-math-bayesian-update-against-market-price)).

### `market_snapshots`
One row per market outcome per cycle. Yes/No prices, best bid/ask,
liquidity, 24h volume. Lets you reconstruct exactly what the order book
looked like when any trade fired.

### `trades`
The decision + execution record. Each row joins to a `signal` and a
`market_snapshot`. `idem_key` is `UNIQUE`. PAPER mode populates `shares`,
`price`, `pnl_usdc` via mark-to-market. LIVE mode would also populate
`tx_hash`.

### `agent_state`
Single-row key/value store for runtime flags: `kill_switch`,
`last_loop_at`.

### `log_events`
Structured operational events distinct from Python stdlib logger output.
Powers the **Decision log** panel in the dashboard.

Schema definitions are in `backend/app/models.py`.

---

## API reference

The backend exposes JSON endpoints at `/api/*` and serves the React SPA
from `/`.

| Method | Path | Payment | Returns |
| --- | --- | --- | --- |
| `GET` | `/healthz` | Free | `{ok, mode}` |
| `GET` | `/api/public/ping` | Free | Public snapshot for Lovable / external pings |
| `GET` | `/api/status` | Free | Agent runtime config + last loop timestamp |
| `GET` | `/api/portfolio` | Cash, equity, realized + unrealized PnL, open positions |
| `GET` | `/api/trades?limit=N` | Recent trades |
| `GET` | `/api/trade/{id}/rationale` | **x402 $0.01 USDC** | Trade joined to signal, news, snapshot |
| `GET` | `/api/signals?limit=N` | Free | Recent LLM extractions |
| `GET` | `/api/news?limit=N` | Free | Recent ingested headlines |
| `GET` | `/api/markets` | Free | Latest snapshot per (market, outcome) |
| `GET` | `/api/equity-curve` | Free | Cumulative PnL time series |
| `GET` | `/api/logs?limit=N&component=...` | Free | Decision log events |
| `POST` | `/api/kill-switch` | **Admin token** | Body `{enabled: bool}` |
| `POST` | `/api/loop/run-once` | **Admin token** | Force one cycle immediately |
| `POST` | `/api/loop/start` | **Admin token** | Start the background loop |
| `POST` | `/api/loop/stop` | **Admin token** | Stop the background loop |

Auto-generated OpenAPI/Swagger at `/docs` (FastAPI default).

The four control endpoints above require `Authorization: Bearer <ADMIN_TOKEN>`.
CORS headers don't stop a direct `curl`, so these are gated by a shared
secret rather than relying on the browser to behave. If `ADMIN_TOKEN` is
unset, the endpoints are disabled and return `503` — they never run open.

```bash
curl -i -X POST http://localhost:8000/api/kill-switch \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'
```

Try it (against a local or deployed instance):

```bash
curl http://localhost:8000/api/public/ping | jq
curl http://localhost:8000/api/status | jq
curl http://localhost:8000/api/trades | jq '.[0]'
```

---

## x402 monetization (workshop)

Following the [Headless Vibe workshop](https://singleton.ai/w2), premium API access
uses the [x402 protocol](https://x402.org): HTTP 402 → client pays USDC → retry
with `X-PAYMENT` header.

| Setting | Value |
| --- | --- |
| Network | Base Sepolia (`eip155:84532`) |
| Facilitator | https://x402.org/facilitator (free, no API key) |
| Price | $0.01 USDC per call |
| Paywalled route | `GET /api/trade/{trade_id}/rationale` |
| Receive wallet | `0x5190715b3aFd1076b1416F20e7E64F53B90e054e` (see [CLAUDE.md](./CLAUDE.md)) |

**Test without paying:**

```bash
curl -i http://localhost:8000/api/trade/1/rationale
# HTTP/1.1 402 Payment Required
```

Enable locally: set `X402_ENABLED=true` and `X402_PAY_TO=<your Base Sepolia address>` in `backend/.env`.

---

## Workshop skills & Gmail

Project-scoped skills from [zingleton/workshop](https://github.com/zingleton/workshop/tree/main)
are in `.cursor/skills/`:

- **email-triage** — inbox scan + reply drafting (requires Gmail connector in Claude)
- **x402-pay** — OWS wallet setup + pay for x402 APIs
- **workshop** — full agenda reference

**Gmail connector:** In Claude Code / Desktop, enable the Anthropic **Gmail**
integration, then run `/email` or ask "check my email". See [CLAUDE.md](./CLAUDE.md).

---

## Configuration

All knobs live in environment variables. Defaults are sane — the agent
runs with zero config. See `backend/.env.example` for the full list.

| Variable | Default | What it does |
| --- | --- | --- |
| `TRADING_MODE` | `PAPER` | `PAPER` simulates; `LIVE` raises `NotImplementedError` until you wire the signer. |
| `LOOP_INTERVAL_SECONDS` | `30` | How often the orchestrator ticks. |
| `EDGE_THRESHOLD` | `0.08` | Minimum `posterior − price` (absolute, 0–1 scale) to trade. |
| `MIN_SIGNAL_CONFIDENCE` | `0.55` | Skip signals the LLM isn't confident about. |
| `MAX_USDC_PER_TRADE` | `10` | Hard cap on every trade. |
| `MAX_OPEN_POSITIONS` | `5` | Refuse new entries past this. |
| `DAILY_DRAWDOWN_USDC` | `25` | If 24h realized PnL drops below `-25`, auto-engage kill switch. |
| `KILL_SWITCH` | `false` | Initial kill switch state. |
| `ADMIN_TOKEN` | *(empty)* | Bearer token for `/api/kill-switch` and `/api/loop/*`. Unset disables those endpoints (503) instead of leaving them open. |
| `MARKET_KEYWORDS` | `bitcoin,ethereum,crypto,sec,etf,fed` | Filter for market discovery. |
| `WATCH_MARKETS` | *(empty)* | Comma-separated `condition_id`s to pin specific markets. Overrides keyword discovery. |
| `MAX_MARKETS` | `5` | How many markets to track. |
| `RSS_FEEDS` | CoinDesk + Cointelegraph + Decrypt | Comma-separated RSS URLs. |
| `CRYPTOPANIC_API_KEY` | *(empty)* | Optional. Free tier at https://cryptopanic.com/developers/api. |
| `GROQ_API_KEY` | *(empty)* | **Recommended.** Free tier at https://console.groq.com. Llama 3.1 8B. |
| `OPENAI_API_KEY` | *(empty)* | Optional fallback. |
| `ANTHROPIC_API_KEY` | *(empty)* | Optional fallback. |
| `DATABASE_URL` | `sqlite:///./doa.db` | SQLAlchemy URL. |
| `X402_PAY_TO` | *(empty)* | EVM address to receive x402 USDC (enables paywall). |
| `X402_PRICE` | `$0.01` | Price per paywalled call. |
| `X402_FACILITATOR_URL` | `https://x402.org/facilitator` | x402 facilitator. |
| `X402_NETWORK` | `eip155:84532` | Base Sepolia (CAIP-2). |

### LLM provider priority

`Groq → OpenAI → Anthropic → heuristic`. First one with a non-empty key
wins. The heuristic fallback is a curated bullish/bearish keyword list and
always works (used as last resort).

---

## Running locally

Prereqs: Python 3.11+, Node 18+.

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # optional — defaults work without any keys
uvicorn app.main:app --reload --port 8000
```

The agent loop starts automatically. Visit:
- `http://localhost:8000/healthz` — health check
- `http://localhost:8000/docs` — Swagger UI
- `http://localhost:8000/api/status` — agent state

### Frontend (dev)

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api` and `/healthz` to
`localhost:8000` automatically.

### Frontend (production-style local test)

To test the single-deploy mode (FastAPI serves the built React bundle):

```bash
cd frontend && npm run build
cd ../backend && uvicorn app.main:app --port 8000
# open http://localhost:8000
```

---

## Deployment

Production is a **single container** on Render: FastAPI serves both the
API and the built React bundle, the agent loop runs in the same process, and
state lives in Postgres (Neon free tier works well; Render free-tier disks are
ephemeral, so do not rely on SQLite there).

### Render (blueprint)

The repo root contains a [`render.yaml`](../render.yaml) blueprint:

1. Fork the repo and open https://dashboard.render.com/select-repo?type=blueprint.
2. Set `DATABASE_URL` to a Postgres connection string (e.g. from
   [Neon](https://neon.tech) free tier). Without it the container falls back to
   SQLite in `/tmp`, which is wiped on every restart.
3. Set `X402_PAY_TO` to your own Base Sepolia address if you want the paywall
   live, plus `X402_ENABLED=true`.
4. Optional: set `GROQ_API_KEY` (free at https://console.groq.com) for real LLM
   extraction instead of the heuristic fallback.

### Any Docker host

The `Dockerfile` in this directory is self-contained (multi-stage: Node 20
frontend build + Python 3.12 runtime). It works unchanged on a VPS,
DigitalOcean, or any container platform — supply the same env vars.

---

## Going live with real money (do not rush this)

`TRADING_MODE=LIVE` is gated behind an explicit `NotImplementedError` in
`app/modules/execution.py:_execute_live`. This is deliberate — a half-built
signer on a public repo is a footgun. To enable:

1. **Implement the signer.** Use [`py-clob-client`](https://github.com/Polymarket/py-clob-client):
   ```python
   from py_clob_client.client import ClobClient
   client = ClobClient(
       host="https://clob.polymarket.com",
       chain_id=137,
       key=os.environ["WALLET_PRIVATE_KEY"],  # not a config field today; add it when going live
   )
   # build a market order, sign with EIP-712, submit
   ```
2. **Capture the order id / tx hash** on the `Trade.tx_hash` column for
   audit.
3. **Store the wallet key as a host secret** (Render dashboard env var),
   never in `.env` or the repo.
4. **Smoke test with `MAX_USDC_PER_TRADE=1`** for at least a day of live
   trades before scaling up.
5. **Set a tight kill switch:** `DAILY_DRAWDOWN_USDC=5` initially.
6. **Run the dashboard.** The kill switch button in the header halts all
   trading instantly. Use it.

---

## How to read the dashboard

The Command Center has six panels:

### Top bar
- **Mode pill** (`PAPER` / `LIVE`) — running mode.
- **Status pill** (`RUNNING` / `HALTED`) — kill switch state.
- **LLM pill** — which NLP provider produced the most recent signal.
- **Run one cycle** — fires the orchestrator immediately (useful for demos).
- **Kill switch** — halts all new trades; auto-engages on drawdown breach.

### Portfolio
- **Equity** — total mark-to-market value.
- **24h PnL** — rolling 24h realized.
- **Realized** — sum over closed positions.
- **Unrealized** — sum over open positions.
- **Open size** — total USDC currently deployed.
- **Cash** — `1000 − open_size + realized` (starting bank = $1000 in paper mode).

### Equity curve
Cumulative realized PnL through time. Hover to see exact values.

### Trade log
Every trade. Click any row to open the **rationale drawer**:
- The trade decision (price, model_p, edge, size).
- The signal that caused it (sentiment, confidence, LR, posterior).
- The source news article (with link to original).
- The market snapshot at trade time.

### Signals (Quant)
Recent LLM extractions. The pill colors:
- 🟢 green = bullish
- 🔴 red = bearish
- gray = neutral

`p 0.18 ← 0.50` means: prior 0.50, posterior 0.18.

### Watched markets (Oracle)
Latest snapshot per market. `bid`/`ask`/`liq`/`24h vol` give you context.

### News stream (Scout)
Every ingested article, linked to the source.

### Decision log
Every Overseer decision. Most entries will say "Skip: confidence below
threshold" or "Skip: no matching market" — that's a feature. You want to
see what the agent considered and rejected.

---

## Extending the agent

Some natural next steps:

### Trade NO instead of YES on bearish signals
Currently the agent only buys YES. To also sell into bearish news:

```python
# orchestrator.py
def _decide_side_and_target_prob(signal, snap_price):
    target, _ = intelligence.bayesian_update(snap_price, signal.sentiment, signal.confidence)
    if target > snap_price:
        return "BUY_YES", target
    else:
        return "BUY_NO", 1 - target   # match against the NO outcome snapshot
```

### Add Twitter/X as a signal source
The `Scout` is the only place that needs to change. Drop a new
`_fetch_twitter` function that queries the X API and yields `RawNews`. The
rest of the pipeline doesn't care where text comes from.

### Better market matching
Today the matching from signal-topic to market is keyword overlap. Swap
in semantic similarity via OpenAI embeddings or `sentence-transformers`
for production quality.

### Limit orders instead of market orders
The CLOB supports limit orders. Build a `_place_limit` helper that posts
at `posterior − N bps` and rests for X seconds before canceling.

### Position sizing by Kelly criterion
Today every trade is `MAX_USDC_PER_TRADE`. Replace with Kelly fraction:
`size = bankroll * (edge / (1 - edge))` clamped to the max.

### Auto-close on alpha decay
Add a watcher that closes positions when (a) the news article is N hours
old, (b) the edge has reverted, or (c) the model's posterior has flipped.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| "No trades yet" | Edge threshold high vs heuristic signals | Set `GROQ_API_KEY` for stronger signals; or lower `EDGE_THRESHOLD` to `0.03` for demo. |
| `watched_markets: 0` in status | No active markets matched your keywords | Pin specific markets via `WATCH_MARKETS=<condition_id>` or broaden `MARKET_KEYWORDS`. |
| `llm_provider: heuristic` | No LLM key loaded | Set `GROQ_API_KEY` in `.env` or your host's env vars |
| `KILL_SWITCH active` rejection | Drawdown triggered auto-kill | Inspect `/api/logs?component=risk`, decide if you want to resume via dashboard toggle. |
| Repeated trades on same article | Should not happen | Check `idem_key` uniqueness in DB; if duplicate, `signal_id` is being regenerated — investigate ingestion. |
| Slow first deploy | First Docker build is ~5 min | Subsequent deploys are ~30s with cached layers. |

---

## Repository layout

```
.
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app + lifespan + SPA serving
│   │   ├── config.py            # Pydantic settings (env-driven)
│   │   ├── database.py          # SQLAlchemy engine + session scope
│   │   ├── models.py            # ORM models
│   │   ├── schemas.py           # Pydantic API schemas
│   │   ├── orchestrator.py      # The agent loop
│   │   ├── modules/
│   │   │   ├── ingestion.py     # Scout
│   │   │   ├── intelligence.py  # Quant (LLM + Bayes)
│   │   │   ├── market.py        # Oracle (Polymarket)
│   │   │   ├── execution.py     # Trader (paper + live stub)
│   │   │   └── risk.py          # Overseer
│   │   └── api/routes.py        # REST endpoints
│   ├── requirements.txt
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── App.tsx              # Dashboard layout + state
│   │   ├── api.ts               # Typed API client
│   │   └── components/
│   │       ├── Panel.tsx        # Card / Stat / Pill primitives
│   │       ├── EquityChart.tsx  # Recharts curve
│   │       └── TradeDrawer.tsx  # Rationale drawer
│   ├── package.json
│   ├── tailwind.config.js
│   └── vite.config.ts
├── Dockerfile                   # Multi-stage build (Node 20 + Python 3.12)
├── docker-entrypoint.sh         # DB init + optional demo seed + uvicorn
├── LICENSE                      # MIT
└── README.md                    # This file
```

---

## License

[MIT](./LICENSE).

---

## Disclaimer

This is a research project. It is not financial advice. Real-money
prediction-market trading is risky and unregulated in many jurisdictions.
The `LIVE` execution path is intentionally unimplemented in this repo —
do not flip it on without a thorough security review, small position
sizes, and a written stop-loss plan.
