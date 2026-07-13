# Poly Agent — Headless Vibe Workshop

Workshop guide: [singleton.ai/w2](https://singleton.ai/w2)

This project is a **Polymarket sentiment-trading agent** with a React command center.
It follows the Headless Vibe workshop flow: public API, agent skills, x402 micropayments
on Base Sepolia.

**Operator:** Priyansh Shah  
**GitHub:** https://github.com/priyanshshahh/polymarket-sentiment-agent

---

## Goals

1. Run a modular trading agent (Scout → Quant → Oracle → Overseer → Trader).
2. Expose a **public API** for external tools (Lovable, curl, Claude skills).
3. Monetize premium data via **x402** (USDC on Base Sepolia, $0.01/call).
4. Use **project-scoped skills** from [zingleton/workshop](https://github.com/zingleton/workshop).

---

## Skills (project scope)

Skills live in `.cursor/skills/` (installed from the workshop repo):

| Skill | Use when |
| --- | --- |
| `email-triage` | "check email", `/email`, morning inbox triage |
| `x402-pay` | create OWS wallet, pay for x402-protected APIs |
| `workshop` | workshop agenda reference |
| `skill-creator` | authoring new skills |
| `query-token-info` | token lookups |

Commands in `.cursor/commands/`: `/email`, `/summary`.

To refresh skills from upstream:

```bash
git clone --depth 1 https://github.com/zingleton/workshop.git /tmp/workshop
cp -R /tmp/workshop/skills/* .cursor/skills/
cp /tmp/workshop/commands/*.md .cursor/commands/
```

---

## Gmail connector (Anthropic)

The `email-triage` skill uses **Gmail MCP tools** in Claude Code / Claude Desktop.

1. Open **Claude Code** or **Claude Desktop** settings.
2. Add the **Gmail** connector (Anthropic email integration).
3. Authorize your Google account.
4. Run `/email` or ask "check my email" — the `email-triage` skill loads automatically.

No Gmail credentials go in this repo. The connector is configured in your Claude client only.

---

## Crypto wallet (x402)

- **Wallet name:** `poly-agent` (OWS, keys in `~/.ows/wallets/`)
- **EVM address** (all EVM chains, incl. Base Sepolia): `0x5190715b3aFd1076b1416F20e7E64F53B90e054e`
- **Payment network:** Base Sepolia testnet (chain ID **84532**, CAIP-2 `eip155:84532`)
- **USDC on Base Sepolia:** `0x036CbD53842c5426634e7929541eC2318f3dCF7e`
- **Facilitator:** https://x402.org/facilitator (free, testnet)

### Fund the wallet

1. **USDC (required to pay):** https://faucet.circle.com/ → select **Base Sepolia** → paste `0x5190715b3aFd1076b1416F20e7E64F53B90e054e` → Send 20 USDC.
2. **ETH (optional):** x402 facilitator pays gas; you typically only need USDC.

Check balance: `ows fund balance --wallet poly-agent`

### Pay for a paywalled API call

```bash
cd .cursor/skills/x402-pay/scripts
npm install
npx tsx pay.ts --url http://localhost:8000/api/trade/1/rationale --method GET
```

---

## Public API (free)

```bash
# Ping from Lovable / anywhere (no payment)
curl http://localhost:8000/api/public/ping

# Agent status
curl http://localhost:8000/api/status
```

## Paywalled API (x402)

```bash
# Returns HTTP 402 with payment instructions
curl -i http://localhost:8000/api/trade/1/rationale

# Pay with the x402-pay skill script (see above)
```

---

## Deploy

Render blueprint at the repo root (`render.yaml`). Set `X402_ENABLED=true`,
`X402_PAY_TO=<your address>`, and `DATABASE_URL=<Postgres URL>` in the Render
dashboard.
