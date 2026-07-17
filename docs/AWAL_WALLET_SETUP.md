# Agentic Wallet (AWAL) — authenticate before x402 pay

Prerequisite for `npx awal x402 pay` (Tavily 402, on-chain settlement). See also the CDP docs index at https://docs.cdp.coinbase.com/llms.txt

## 1. Check status

```bash
npx awal@latest status
npx awal@latest status --json
```

## 2. Email OTP login

```bash
npx awal@latest auth login <your-email>
# Note the printed flowId, check email for 6-digit code

npx awal@latest auth verify <flowId> <otp>
```

## 3. Base Sepolia (hackathon / test USDC)

```bash
npx awal@latest balance --chain base-sepolia
npx awal@latest address --json
```

Fund the printed address from the **Coinbase Base Sepolia faucet** before running `TRADING_MODE=LIVE`.

## 4. JSON output (for scripts)

All commands support `--json` for machine-readable output.

## Reference

| Command | Purpose |
| --- | --- |
| `npx awal@latest status` | Health + auth |
| `npx awal@latest auth login <email>` | Start OTP flow → `flowId` |
| `npx awal@latest auth verify <flowId> <otp>` | Complete session |
| `npx awal@latest balance` | USDC balance |
| `npx awal@latest address` | Wallet address |
| `npx awal x402 pay <url> ...` | Pay 402-gated HTTP resources |
