# CHF Agent Contracts

This repo implements deterministic pipeline workers, not autonomous AI agents. Each stage follows the `AgentBase` lifecycle:

`prepare -> run -> persist`

The public pipeline order is:

`universe -> market -> onchain -> features -> labels -> models -> portfolio -> backtest`

`AlphaResearchAgent` is a separate signal-screening sweep reachable only via
`python main.py alpha_research`; it is structurally incapable of self-certifying
alpha (only `BacktestAgent` can). See `docs/ARCHITECTURE.md` for the full system map.

> **Filenames are canonical single files.** The pipeline writes one unified file
> per artifact (e.g. `full_features_pruned.parquet`, `model_predictions.parquet`),
> not per-symbol or per-model files. There is a single unified `FeatureAgent`
> (no `FeatureAgentV1`/`V2`). `ModelAgent` does not write `.pkl` files and does not
> call MLflow.

## UniverseAgent

- Purpose: Build the eligible monthly crypto universe.
- Upstream inputs: `configs/run_config.yaml`, `configs/universe_exclusions.yaml`
- Output artifacts:
  - `data/raw/universe/universe_monthly.parquet`
  - `data/raw/universe/universe_membership.parquet`
  - `data/raw/universe/exclusions_monthly.parquet`
  - `data/raw/universe/universe_coverage_report.parquet`
  - `data/raw/universe/universe_manifest.json`
- Core logic: fetch top-N assets, exclude stablecoins/wrapped/bridged/LST/synthetic, apply 365-day maturity + exchange-tradability + on-chain-coverage gates, persist eligibility snapshot.
- Failure modes: upstream API failure, invalid config, empty universe snapshot.
- Done when: `universe_monthly.parquet` and `universe_manifest.json` exist and contain eligible assets.

## MarketDataAgent

- Purpose: Fetch daily OHLCV history for the eligible universe.
- Upstream inputs: latest universe snapshot, `market_data` config
- Output artifacts:
  - `data/raw/market/market_ohlcv.parquet` (canonical combined frame)
  - `data/raw/market/by_symbol/{SYMBOL}.parquet`
  - `data/raw/market/market_coverage_report.parquet`
  - `data/raw/market/market_manifest.json`
- Core logic: exchange-first via ccxt (Coinbase/Kraken/KuCoin/Gemini) with a 4-provider close-only fallback; hard-bans Binance and USDT-quoted pairs; emits per-symbol coverage QA.
- Failure modes: exchange/API failure, no symbols, empty fetches, low coverage.
- Done when: `market_ohlcv.parquet`, coverage report, and manifest exist and pass the verifier.

## OnChainAgent

- Purpose: Collect daily on-chain/DeFi fundamentals aligned to each symbol's market calendar.
- Upstream inputs: latest universe snapshot, `onchain` config
- Output artifacts:
  - `data/raw/onchain/onchain_wide.parquet`
  - `data/raw/onchain/onchain_observations.parquet`
  - `data/raw/onchain/onchain_coverage_report.parquet`
  - `data/raw/onchain/onchain_manifest.json`
- Core logic: fetch source-specific metrics from 6 providers, align to each symbol's market dates, deliberately *not* forward-filling.
- Failure modes: missing provider coverage, API failures, empty merged frames.
- Done when: `onchain_wide.parquet`/`onchain_observations.parquet` and the coverage report exist.

## FeatureAgent

- Purpose: Build market + lagged on-chain features and emit final feature selection metadata.
- Upstream inputs:
  - `data/raw/market/market_ohlcv.parquet`
  - `data/raw/onchain/onchain_wide.parquet`, `onchain_observations.parquet`
  - `data/raw/universe/universe_monthly.parquet`
- Output artifacts:
  - `data/features/market_features.parquet`
  - `data/features/onchain_features.parquet`
  - `data/features/full_features.parquet`
  - `data/features/full_features_pruned.parquet`
  - `data/features/feature_dictionary.json`, `feature_keep_list.json`, `feature_manifest.json`
- Core logic: compute returns/momentum, risk, mean-reversion, liquidity, range/drawdown, BTC beta, and lagged on-chain transforms; cross-sectionally winsorize + z-score; correlation + VIF pruning to 20–60 features. A `PROHIBITED_COLUMN_TOKENS` denylist blocks leaky column names.
- Failure modes: missing canonical inputs, empty concatenation, all features pruned.
- Done when: `full_features_pruned.parquet` exists with one row per `symbol/date_ts` and numeric feature columns.

## LabelAgent

- Purpose: Generate leakage-safe forward-return targets and the modeling dataset.
- Upstream inputs: `data/raw/market/market_ohlcv.parquet`, feature store + manifests
- Output artifacts:
  - `data/labels/labels_{horizon}d.parquet`
  - `data/labels/label_matrix.parquet`
  - `data/labels/modeling_dataset.parquet` (features + labels joined, pruned)
  - `data/labels/modeling_dataset_unpruned.parquet` (optional)
  - `data/labels/label_coverage_report.parquet`, `label_manifest.json`
- Core logic: compute `label_fwd_logret = ln(P[t+h] / P[t])` per symbol at horizons [7, 14, 30]d with exact-calendar-horizon enforcement; drop incomplete tails; prohibited-column leakage scan.
- Failure modes: non-positive prices, malformed timestamps, empty histories, detected leakage.
- Done when: horizon parquet files and `modeling_dataset.parquet` exist and contain `label_fwd_logret` (+ `label_simple_return`, `label_direction`, `horizon_days`).

## ModelAgent

- Purpose: Train tabular models with purged + embargoed walk-forward CV and persist predictions/metrics.
- Upstream inputs: `data/labels/modeling_dataset.parquet`, feature manifest + keep list
- Output artifacts:
  - `data/predictions/model_predictions.parquet`
  - `data/predictions/model_leaderboard.parquet`
  - `data/predictions/fold_metrics.parquet`
  - `data/predictions/feature_importance.parquet`
  - `data/predictions/model_manifest.json`, `data_quality_model.md`
- Core logic: baseline-mean / RandomForest / LightGBM across horizon × feature-set, purged + embargoed walk-forward CV, and a signal gate (rank-IC ≥ 0.01, t-stat ≥ 1.5, coverage ≥ 0.80, folds ≥ 3). Predictions carry `model_name`, `feature_set`, `horizon_days`, `prediction`, and realized `actual_forward_return`/rank columns used only for the leaderboard.
- Failure modes: missing modeling dataset, no valid splits, LightGBM unavailable, empty OOS predictions.
- Done when: `model_predictions.parquet` and `model_leaderboard.parquet` are written.

## PortfolioAgent

- Purpose: Turn predictions into rebalance weights across allocation strategies.
- Upstream inputs:
  - `data/predictions/model_predictions.parquet`, `model_leaderboard.parquet`
  - `data/raw/market/market_ohlcv.parquet` (for liquidity/execution prices)
- Output artifacts:
  - `data/allocations/allocations_from_predictions.parquet` (canonical, all strategies)
  - `data/allocations/allocations_{strategy}.parquet`
  - `data/allocations/allocation_coverage_report.parquet`
  - `data/allocations/allocation_manifest.json`
- Core logic: select a model/horizon/feature-set (best available from the leaderboard, else configured fallback), filter to usable predictions, compute weights across 5 strategies. Blocks label-leaking inputs via `FORBIDDEN_INPUT_TERMS` unless a diagnostic override is set. Emits `weight`, `strategy_name`, `symbol`, `date_ts`.
- Failure modes: missing predictions, forbidden realized columns present, no usable predictions for the selected combo, empty allocations.
- Done when: `allocations_from_predictions.parquet` exists and is non-empty.

## BacktestAgent

- Purpose: Evaluate the allocation strategy against benchmarks with transaction costs and a strict alpha gate.
- Upstream inputs:
  - `data/allocations/allocations_from_predictions.parquet` (+ manifest)
  - `data/raw/market/market_ohlcv.parquet`
- Output artifacts:
  - `data/backtests/equity_curves.parquet`
  - `data/backtests/backtest_summary.parquet`
  - `data/backtests/benchmark_summary.parquet`
  - `data/backtests/strategy_comparison.parquet`, `cost_sweep.parquet`, `drawdown_series.parquet`
  - `data/reports/alpha_report.json`, `alpha_report.md`
- Core logic: run the main strategy against 5 benchmarks with 20bps costs + a cost sweep, execution-date-after-signal-date checks, and a strict multi-condition alpha gate that only `BacktestAgent` can satisfy. All performance metrics are hand-rolled pandas/numpy (`_perf_from_returns`). Emits `strategy_name`, `sharpe`, `total_return`, and drawdown metrics.
- Failure modes: no allocation files, no market prices, malformed allocation artifacts.
- Done when: `backtest_summary.parquet` exists with populated risk/return metrics.

## Demo Mode

- Purpose: Emit canonical synthetic artifacts for dashboard/API loading and offline acceptance checks.
- Entry point: `python main.py demo`
- Output artifacts: canonical raw/features/labels/predictions/allocations/backtests files matching the live pipeline naming above.
- Done when: dashboard/API loaders can read the generated files without special-case paths.
