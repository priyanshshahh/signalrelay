# SignalRelay — internal code audit

Honest, internal, "document only" audit of `chf/` and `polymarket-sentiment-agent/`. Nothing
here was fixed — this is a map of weak spots, dead code, duplication, over-engineering, and
things that would trip up a reviewer, ranked roughly by value-to-fix (impact of fixing it vs.
effort required). See `docs/ARCHITECTURE.md` for the system map these findings refer into.

---

## 1. chf has one systemic root cause behind most of its rough edges: refactor drift

**Highest value-to-fix — one coordinated cleanup pass resolves ~7 separate-looking problems.**

At some point chf was refactored from a two-stage `FeatureAgentV1`/`V2` design with
per-symbol/per-model output files to unified agents writing canonical single files (e.g.
`full_features_pruned.parquet` instead of per-symbol feature files, `model_predictions.parquet`
instead of `predictions_{model}_h{horizon}d.parquet`). The agent code itself and 240/243 tests
were updated. Nothing else was:

- `chf/docs/agent_contracts.md` still documents the old per-symbol/per-model filenames and
  describes `FeatureAgentV1`/`V2` as two real sequential agents — they are actually empty alias
  subclasses of one unified `FeatureAgent` (`chf/agents/feature_agent.py:860-866`).
- `chf/app/api.py` — 3 of 6 endpoints (`/weights`, `/signals`, `/latest_snapshot`) read
  filenames that only the legacy demo generator produces; they silently return empty/404
  against a real pipeline run.
- `chf/app/dashboard.py` — 2 of 6 Streamlit pages (Signal Monitor, Portfolio Weights) have the
  same problem; only work in demo mode despite no visible indication to the operator that
  they're broken in "real data" mode.
- `chf/models/ablation.py` — hardcodes feature names from the legacy schema (`ret_7d`,
  `nvt_ratio`, `tvl_ratio`, none of which exist in real `FeatureAgent` output) **and**
  separately calls `WalkForwardValidator(n_splits=..., test_size_days=...)` with kwargs the
  current `generate_purged_walk_forward_splits()` signature doesn't accept. `python main.py
  ablation` is reproducibly broken two independent ways, has zero pytest coverage, and only
  surfaces in `scripts/smoke_test.py` (which currently fails on it).
- `chf/pipelines/duckdb_engine.py` — glob patterns predate the refactor (`*_onchain.parquet`,
  `qa_report.parquet`) and return empty against real output; effectively dead.
- `chf/scripts/smoke_test.py` — currently `21/25` passing for the same reasons (stale
  `feature_engineering` import names, the `WalkForwardValidator` kwarg mismatch twice).
- 2 of the 3 known-failing pytest tests (`test_cli_commands.py`,
  `test_pipeline_integration.py`) are frozen at the pre-refactor architecture.

**Why it matters**: a reviewer opening `agent_contracts.md` or the dashboard first will get an
actively wrong model of the system. This is exactly the kind of thing that erodes trust in a
"243-test" pipeline claim — the tests are fine, but everything *around* them lagged.

**Fix effort**: moderate but mechanical — one pass to either delete/rewrite the stale docs and
fix the 3 broken consumers to read the current filenames, or delete the dead consumers
entirely (see #6).

---

## 2. x402 payment verification is 100% delegated to a remote, third-party facilitator

The paywalled route (`GET /api/trade/{id}/rationale`) never performs its own cryptographic
check of the EIP-3009 payment authorization. `HTTPFacilitatorClient.verify()` and `.settle()`
(x402 pip package) are both plain HTTP POSTs to `X402_FACILITATOR_URL` (default:
`https://x402.org/facilitator`, a free public Base Sepolia facilitator this project does not
operate), and the backend trusts whatever `is_valid` comes back with zero independent
verification — no local signature recovery, no local RPC balance/nonce check.

This is how the x402 protocol is *designed* to work (resource server delegates verify/settle
to a facilitator), and the failure mode is fail-closed (402/502 on facilitator error or
timeout, never fail-open), so this is not a bug in the implementation. It is, however, a
trust-model fact worth stating plainly rather than glossing over: **if the configured
facilitator is compromised, buggy, or simply misconfigured to always return
`is_valid: true`, the paywall provides no real security.** For a hackathon demo against a free
public testnet facilitator this is a reasonable trade-off; it would need re-examining (self-hosted
facilitator, or a second independent verification path) before this pattern is reused with real
value at stake.

**Fix effort**: none required for the demo's stated scope; worth a one-line disclaimer in
user-facing docs and a decision point before any production/mainnet use.

---

## 3. `chf`'s `clean` pipeline stage is silently broken and produces nothing

`chf/pipelines/data_cleaner.py`: `MarketDataCleaner.clean_all_symbols()` globs
`*_ohlcv.parquet` non-recursively in `data/raw/market/`, which only matches the combined
multi-symbol `market_ohlcv.parquet` (per-symbol files live one level down in `by_symbol/`, so
they're never seen). It derives a nonsense symbol name (`"market"`) and
`clean_ohlcv()`'s `set_index("date_ts").reindex(...)` raises `ValueError: cannot reindex on an
axis with duplicate labels` against that multi-symbol frame — reproduced live during this
audit. The exception is swallowed per-file inside `clean_all_symbols`, so the stage "succeeds"
while writing nothing. `OnChainDataCleaner` globs `*_onchain.parquet`, which matches none of
the real on-chain output filenames (`onchain_wide.parquet`, `onchain_observations.parquet`) — a
silent zero-iteration no-op.

Nothing downstream reads `data/cleaned/` — `FeatureAgent` reads the raw stage outputs
directly — so the stage is functionally dead weight, not a data-integrity risk. But it *is*
inconsistent across orchestrators: `chf/main.py`/`pipeline_runner.py` include `clean` in the
canonical stage list, while `run_all.sh` skips it entirely — meaning the two orchestrators
already silently disagree on what the pipeline does.

**Fix effort**: low — either fix the glob patterns and the reindex bug, or delete the stage and
its scheduler job (`chf/jobs/scheduler.py` bundles it into the daily features job) since
nothing consumes its output today.

---

## 4. Three redundant pipeline orchestration entry points (ponytail: pick one)

`chf/main.py` (argparse CLI), `chf/pipelines/pipeline_runner.py` (its own `main()`, slightly
different stage vocabulary — includes `clean`, excludes `alpha_research`/`ablation`), and
`chf/run_all.sh` (shell wrapper calling `main.py` per stage, then the verifier) all exist to do
the same job: run the DAG stage by stage with validation gates in between.
`run_all.sh` additionally re-runs the *previous* stage's verifier before stages 3, 5, and 6 —
straightforward copy-paste redundancy inside the one entry point that's supposed to be the
simple wrapper.

Nothing about the three-entry-point design adds capability that a single well-parameterized
CLI (`main.py --full`, already present) couldn't cover; the divergence is exactly how `clean`
ended up silently included in two of the three and excluded from the third (#3).

**Fix effort**: low-medium — collapse to one canonical entry point (`main.py` is the most
complete) and either delete or thin the other two to trivial wrappers around it.

---

## 5. Provider HTTP resilience logic is duplicated three-to-four times

`chf/providers/http_client.py`'s `CachedHttpClient` is genuinely solid: per-provider disk cache
(supports fully offline test/demo runs), monotonic-clock throttling, per-request timeout,
exponential-backoff retry honoring `Retry-After`, and clean fail-fast/rate-limit/DNS-failure
classification. 12 of 16 providers use it.

The other four reimplement pieces of the same problem independently:

- `chf/providers/ccxt_market.py` (lines 248-316) — its own parallel throttle/backoff/retry
  loop, reusing only exception *types* from `http_client.py`.
- `chf/providers/ccxt_binance.py` — a third, slightly different retry loop (no jitter, no
  cache) — moot, since this file is dead code (#6).
- `chf/providers/exchange_tradability.py` — a bare `try/except` with **no retry logic at all**.

That's ~150 lines of copy-pasted/reinvented backoff math across the codebase for what is
already a well-built shared utility one import away. It's also unverified whether
`CCXTMarketProvider`'s configured `request_timeout_seconds`/`max_retries` are actually
forwarded into the underlying `ccxt` client objects — worth a reviewer double-checking before
relying on it for a real live-data window.

**Fix effort**: medium — route `ccxt_market.py` and `exchange_tradability.py` through
`CachedHttpClient` (or a thin ccxt-specific wrapper around the same retry policy), delete
`ccxt_binance.py`.

---

## 6. Dead code cluster (safe deletes, mostly zero risk)

| File / area | Evidence it's dead |
|---|---|
| `chf/providers/ccxt_binance.py` (236 lines) | Never imported anywhere; the only reference in the repo is a regression test asserting it's **absent** from `market_data_agent`'s source |
| `chf/schemas/schemas.py` (267 lines) | Zero imports anywhere in the codebase (grep-verified); also stale vs. real column sets (e.g. missing `market_cap`/`data_type` on `OHLCVBar`, `FeatureRow` modeled long-format when the real store is wide) |
| `chf/pipelines/duckdb_engine.py` (216 lines) | Only real DuckDB usage is `load_market_data()`; everything else is stale-glob pandas concat that returns empty against real output; only referenced by `smoke_test.py` and an import check in `bootstrap.py` — no agent or app code uses it |
| `chf/backtesting/`, `chf/portfolio/` | Both are 0-byte-`__init__.py`-only stub packages; all real logic lives in `agents/backtest_agent.py` / `agents/portfolio_agent.py` — vestige of an abandoned layered-architecture plan |
| `chf/agents/feature_agent.py:860-866` | `FeatureAgentV1`/`FeatureAgentV2` — empty alias subclasses kept alive only by the one stale test in #1 |
| `chf/models/walk_forward.py:206-216` | `compute_fold_metrics`/`aggregate_fold_metrics` — legacy-name stubs that just `raise NotImplementedError` |
| `chf/reports/alpha_analysis.py` | Used only by the `main.py` demo generator; `BacktestAgent` has its own independent alpha-report code path — two diverging "alpha report" implementations that happen to share a name |

None of these are called from a live code path other than each other's stale
tests/references — this whole cluster (roughly 900+ lines) can be deleted with low risk once
someone confirms nothing external depends on the import paths.

**Fix effort**: low — mostly deletions plus removing the one test that monkeypatches
`FeatureAgentV1`/`V2`.

---

## 7. Committed model-artifact binaries that current code can no longer even produce

`chf/artifacts/` is tracked in git (not gitignored, unlike `chf/metadata/*.db`), including
`chf/artifacts/models/lightgbm_h7d.pkl` (572K) and `random_forest_h7d.pkl` (628K) plus
feature-importance CSVs and fold-metrics JSONs. This is doubly stale: the *current* `ModelAgent`
doesn't write `.pkl` files at all (no `joblib.dump`/`pickle.dump`/MLflow call anywhere in
`agents/` or `models/` — grep-verified), so these are relics of a pre-refactor design, sitting
in git history as dead weight with no code path that regenerates or consumes them.

**Fix effort**: low — delete, add `chf/artifacts/models/*.pkl` (or the whole directory) to
`.gitignore`, note in a follow-up commit if repo-size history cleanup is also wanted.

---

## 8. `ablation.py` is a structurally broken, untested CLI command

Called out under #1 for its role in refactor drift, but worth its own line because it's a
*user-facing* command (`python main.py ablation`, wired into `chf/Makefile`) that currently
cannot succeed against real pipeline output for two independent reasons (stale hardcoded
feature names; a `WalkForwardValidator` kwarg mismatch causing a `TypeError`), and has **zero**
pytest coverage — only the currently-failing `smoke_test.py` touches it. A reviewer who runs
the documented `make` targets in order will hit this and reasonably wonder what else is
similarly untested.

**Fix effort**: medium — needs an actual current-schema feature list and a corrected call
signature, plus at least one regression test to keep it honest going forward.

---

## 9. Stale hackathon-era docs actively misdescribe the current architecture

Beyond `chf/docs/agent_contracts.md` (covered in #1), the *repo-root* docs have two eras that
contradict each other, and the older era describes integration that no longer exists:
`docs/ARCHITECTURE_BLUEPRINT.md` ("AlphaNet-402 merges... Project CHF... unified application
code lives under `/alphanet-core`"), `docs/HACKATHON_CONCEPT.md` ("How the Repositories
Merge"), `CURSOR_DOCS.md`, `docs/DEMO_GUIDE.md`, `docs/PITCH_DECK_PRESENT.md`,
`docs/DEPLOYMENT_AZURE_DO_DIGITALOCEAN_SENTRY.md`, `docs/AWAL_WALLET_SETUP.md`, and the prior
`docs/ARCHITECTURE.md` (Scout/Quant/Risk/Command-Center "AlphaNet-402" narrative citing Tavily
and AWAL, neither of which appears anywhere in the current backend or consumer code). All of
these reference a merged `alphanet-core/` app, routes (`/api/state`, `/api/cycle`,
`/demo/embed`), and env vars (`TAVILY_API_KEY`, `OUR_AWAL_WALLET_ADDRESS`) that do not exist in
the current codebase. `docs/PROJECT-NOTES.md` confirms this merged app was built and then
explicitly removed from the repo.

This is exactly the kind of thing that trips up a new reviewer or judge: reading the docs in
the wrong order produces a materially wrong mental model of whether chf and the polymarket
agent are integrated (see `docs/ARCHITECTURE.md`'s "the seam" section for the current,
evidence-based answer: they are not).

**Fix effort**: low — either delete the stale docs outright or move them to a clearly-labeled
`docs/archive/` so they stop reading as current.

---

## 10. Miscellaneous but real: config duplication, provenance weakness, unauthenticated pipeline control, inert config surface

A grab-bag of smaller, real issues that don't individually rank as high but are worth a
reviewer knowing about:

- **Duplicate config sections**: `chf/configs/run_config.yaml` has two near-byte-identical
  sections, `onchain:` (lines ~513-627) and `on_chain:` (lines ~651-765). This is only
  load-bearing because `OnChainAgent` defensively does
  `self.cfg.get("onchain") or self.cfg.get("on_chain", {})` — the defensive fallback masks what
  is otherwise a straightforward copy-paste-and-rename duplication bug waiting to bite the
  moment someone edits one section and not the other.
- **Config provenance is coarser than it claims**: `get_config_hash()` hashes the *entire*
  1494-line YAML rather than the subset of config actually used by a given stage/run, so two
  runs with identical stage-relevant config but an unrelated edit elsewhere in the file get
  different provenance hashes — weakens the "reproducible run" story the manifests are meant to
  support.
- **Unauthenticated pipeline control surface**: `chf/app/dashboard.py`'s Pipeline Control page
  (lines ~826-955) fire-and-forget `subprocess.Popen`s `pipeline_runner.py --stage X` with no
  auth, no confirmation step, and no concurrency lock — repeated clicks (or multiple dashboard
  users) can spawn concurrent live-API pipeline runs writing to the same data directories.
  Low risk today since the dashboard isn't deployed publicly, but worth flagging before it
  ever is.
- **Config surface with no effect**: `WALLET_PRIVATE_KEY` (polymarket backend) is loaded into
  settings but never referenced anywhere except its own declaration — `TRADING_MODE=live`'s
  execution path (`execution.py::_execute_live`) unconditionally raises `NotImplementedError`.
  This is a deliberate, documented safety stub (not an oversight), but an operator skimming
  `.env.example` could reasonably assume setting the key does something.
- **Claimed-but-unused dependencies**: chf's `Makefile` advertises `make mlflow` and the
  README/docs reference MLflow/XGBoost/SHAP in `ModelAgent`, but grep across `agents/` and
  `models/` finds zero references to any of them; similarly `chf/agents/backtest_agent.py`
  does `import vectorbt as vbt  # noqa: F401` and never calls it — all backtest metrics are
  hand-rolled pandas/numpy (`_perf_from_returns`). Not harmful, but it's dependency and
  documentation surface that oversells what the code does.

**Fix effort**: low per item; mostly a matter of someone doing a focused half-day cleanup pass
across config, dashboard auth, and doc/dependency claims.

---

## What's *not* wrong (worth stating, since an audit that only lists problems reads as unbalanced)

- chf's leakage discipline is real and consistently enforced: prohibited-column token
  denylists, exact-calendar-horizon labels, purged + embargoed walk-forward CV, execution-date-
  after-signal-date checks in both `PortfolioAgent` and `BacktestAgent`, and a strict
  multi-condition alpha gate that only `BacktestAgent` can satisfy (`AlphaResearchAgent` is
  structurally prevented from self-certifying).
- The provider HTTP layer (`http_client.py`) that most of chf's providers actually use is
  well-built: cache-first for offline reproducibility, per-provider throttling, proper
  timeout/retry/backoff with `Retry-After` handling, and clean error classification.
  The duplication problem (#5) is that a few providers don't use it — not that it's weak.
- The polymarket backend's admin-token auth (#/control-plane) is correctly implemented:
  constant-time comparison, fail-closed when unset (503, not open access), 16 dedicated tests.
- The polymarket agent's LLM integration degrades gracefully: Groq → OpenAI → Anthropic →
  local heuristic keyword scorer, each wrapped in its own try/except, so an LLM outage never
  crashes the trading loop — it silently (and by design) falls back to a weaker but functional
  signal.
- Both test suites are genuinely offline/hermetic (mocked HTTP, temp SQLite, `use_fixtures`),
  which is why they're fast and reproducible — 3.24s for 71 backend tests, ~167s for 243 chf
  tests with zero live network calls in either.
