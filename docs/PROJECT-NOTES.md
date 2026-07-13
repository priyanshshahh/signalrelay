# Project Notes — prod-hardening pass (July 2026)

Engineering log for the `prod-hardening` branch: what changed, why, and what is still open.
Written for a reviewer who wants the honest state of the repo, not the pitch.

## What changed in this pass

1. **alphanet-core removed** — the unrelated sub-app moved to its own repository; this
   repo is now provider + consumer + chf research engine only.
2. **Deploy path: Render** (`render.yaml`); the Fly.io path was dropped to keep one
   documented deploy story.
3. **CORS hardened** — wildcard replaced with an env-driven allowlist
   (`CORS_ORIGINS`, see `polymarket-sentiment-agent/backend/app/config.py`).
4. **x402 fail-hard** — with `X402_ENABLED=true` and no real `X402_PAY_TO`, startup
   aborts (`app/x402_setup.py`). The free route `/api/demo/rationale/{id}` now returns a
   truncated teaser instead of the full paid payload — there is no free bypass.
5. **Demo data labeled end to end** — `demo` column on news/signals/snapshots/trades,
   surfaced through every API response, and rendered in the UI (DEMO pills, "PnL
   illustrative" badges on portfolio + equity). Seeded records are never presented as
   real performance.
6. **Persistence** — `DATABASE_URL`-driven: Postgres in production, SQLite for dev/tests
   (URL normalization in `app/database.py`).
7. **Bayesian posterior clamped** away from hard 0/1 so a single headline can never
   produce certainty.
8. **Offline backend test suite** — `polymarket-sentiment-agent/backend/tests`,
   55 tests, no network, in-memory SQLite.
9. **CI** — `.github/workflows/ci.yml`: backend pytest, chf pytest, frontend
   `tsc --noEmit` + `vite build`.
10. **chf** — added missing `tabulate` dependency (pandas `to_markdown` in reports).

## Test status (run locally 2026-07-12, Python 3.12)

| Suite | Result |
| --- | --- |
| Backend app tier | 55 passed |
| chf (full) | 239 passed, 4 failed of 243 |
| chf (CI selection) | 239 passed, 4 deselected |
| Frontend | tsc clean, vite build green |

The 4 chf failures are not code bugs: `test_cmd_features_runs_both_feature_stages`,
`test_cache_is_used_before_live_api`,
`test_verifier_does_not_falsely_fail_on_valid_10x365_output`, and
`test_pipeline_agents_run_end_to_end_from_market_data` all require pipeline-generated
artifacts under `chf/data/raw/` (gitignored, absent in a fresh checkout). CI deselects
exactly these, with the reason inline in the workflow.

## Live verification (2026-07-12)

Real Groq call (`llama-3.1-8b-instant`) through `app/modules/intelligence.py` on a Fed
headline: `sentiment=bullish, confidence=0.8, topic=FED, entities=['FOMC']`;
`bayesian_update(prior=0.62)` → `posterior=0.8727`, `likelihood_ratio=4.2`. Keys are
loaded from the operator's environment at runtime only — never committed.

## Design positions

- **LLM as parser, math in Python.** The model extracts structured sentiment; the
  posterior is a deterministic, clamped Bayesian update. Reproducible and auditable.
- **Paper trading by default.** LIVE mode exists but requires an explicit private key and
  is off by default; risk limits (per-trade cap, max positions, daily drawdown, kill
  switch) sit in front of it.
- **Research integrity via chf.** Point-in-time universes, leakage-audited features,
  deterministic seeds, and a verifier stage that fails on malformed artifacts.

## Known limitations / open items

- The 4 data-dependent chf tests need a documented fixture-generation path (or committed
  minimal fixtures) so the full 243 can run in CI.
- Paper fills are simulated at snapshot price — no slippage/liquidity model.
- The equity curve mixes seeded demo trades with any real paper trades; it is labeled,
  but a demo-free filter toggle would be better.
- Single-process agent loop; no horizontal scaling story (fine at this scope).
- x402 is testnet (Base Sepolia). Mainnet would need pricing, receipts, and abuse limits.
