"""End-to-end integration across the refactored downstream agents.

This test exercises the real post-refactor seam:

    ModelAgent  →  PortfolioAgent  →  BacktestAgent

Each agent consumes the *actual* canonical output of the previous one
(`model_predictions.parquet` → `allocations_from_predictions.parquet` →
`backtest_summary.parquet`), so it guards against exactly the filename/column
drift the code audit flagged. The upstream FeatureAgent/LabelAgent stages have
their own dedicated research-mode suites; here we start from a synthetic
canonical `modeling_dataset.parquet` plus a matching `market_ohlcv.parquet`.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd

from agents.backtest_agent import BacktestAgent
from agents.model_agent import ModelAgent
from agents.portfolio_agent import PortfolioAgent
from configs.config import load_config

SYMBOLS = ["BTC", "ETH", "SOL", "ADA", "UNI", "LINK", "AAVE", "DOGE"]
PERIODS = 260
HORIZON = 7


def _cfg(tmp_path: Path) -> dict:
    cfg = copy.deepcopy(load_config())
    cfg["_project_root"] = str(tmp_path)

    modeling = dict(cfg.get("modeling", {}))
    modeling.update(cfg.get("modeling_smoke", {}))
    modeling["input_path"] = "data/labels/modeling_dataset.parquet"
    modeling["model_names"] = ["baseline_cross_sectional_mean"]
    modeling["horizons"] = [HORIZON]
    modeling["default_horizon"] = HORIZON
    modeling["feature_sets"] = ["market_only"]
    modeling["min_prediction_rows"] = 10
    modeling["min_assets_per_prediction_date"] = 3
    modeling["walk_forward"] = dict(modeling.get("walk_forward", {}))
    modeling["walk_forward"].update({"min_train_rows": 20, "min_test_rows": 6, "min_test_symbols": 3})
    cfg["modeling"] = modeling

    pcfg = dict(cfg.get("portfolio", {}))
    pcfg.update(cfg.get("portfolio_smoke", {}))
    pcfg["output_dir"] = "data/allocations"
    pcfg["strategies"] = ["top_k_equal_weight"]
    pcfg["default_top_k"] = 5
    pcfg["horizon_days"] = HORIZON
    # ModelAgent writes realized actuals into model_predictions.parquet for its own
    # leaderboard/diagnostics; PortfolioAgent (correctly) refuses leaky columns by
    # default. This is a diagnostic research run, so we opt into the documented flag.
    pcfg["allow_realized_columns_in_predictions_for_diagnostics"] = True
    cfg["portfolio"] = pcfg

    btcfg = dict(cfg.get("backtesting", {}))
    btcfg.update(cfg.get("backtesting_smoke", {}))
    btcfg["allocation_path"] = "data/allocations/allocations_from_predictions.parquet"
    btcfg["allocation_manifest_path"] = "data/allocations/allocation_manifest.json"
    btcfg["market_path"] = "data/raw/market/market_ohlcv.parquet"
    btcfg["output_dir"] = "data/backtests"
    cfg["backtesting"] = btcfg
    return cfg


def _write_inputs(tmp_path: Path) -> None:
    dates = pd.date_range("2025-01-01", periods=PERIODS, freq="D", tz="UTC")
    rng = np.random.default_rng(11)

    model_rows = []
    market_rows = []
    for s_idx, symbol in enumerate(SYMBOLS):
        drift = 0.0006 * (s_idx + 1)
        rets = rng.normal(drift, 0.02, PERIODS)
        prices = (100 + 12 * s_idx) * np.cumprod(1 + rets)
        for i, dt in enumerate(dates):
            fwd = float(np.sum(rets[i + 1 : i + 1 + HORIZON])) if i + HORIZON < PERIODS else np.nan
            model_rows.append({
                "date_ts": dt,
                "symbol": symbol,
                "snapshot_id": "feat-snap",
                "run_id": "label-run",
                "created_at_utc": "2025-06-01T00:00:00+00:00",
                "log_ret_1d": float(rets[i]),
                "realized_vol_7d": 0.1 + abs(float(rets[i])),
                "momentum_7_30": float(np.mean(rets[max(0, i - 30) : i + 1])),
                "market_data_available": 1,
                "is_forward_filled_market": 0,
                "feature_set": "full",
                "feature_version": "full_v1",
                f"label_fwd_logret_{HORIZON}d": fwd,
            })
            market_rows.append({
                "date_ts": dt,
                "symbol": symbol,
                "exchange": "coinbase",
                "exchange_symbol": f"{symbol}/USD",
                "open": prices[i] * 0.99,
                "high": prices[i] * 1.02,
                "low": prices[i] * 0.98,
                "close": float(prices[i]),
                "volume": 1_000_000 + i,
                "source": "coinbase",
                "snapshot_id": "market-snap",
                "fetched_at_utc": "2025-06-01T00:00:00+00:00",
                "is_forward_filled": False,
                "is_incomplete_dropped": False,
                "data_type": "exchange_ohlcv",
                "is_full_ohlcv": True,
                "quote_currency": "USD",
            })

    labels_dir = tmp_path / "data" / "labels"
    market_dir = tmp_path / "data" / "raw" / "market"
    feat_dir = tmp_path / "data" / "features"
    for d in (labels_dir, market_dir, feat_dir):
        d.mkdir(parents=True, exist_ok=True)

    pd.DataFrame(model_rows).to_parquet(labels_dir / "modeling_dataset.parquet", index=False)
    with open(labels_dir / "label_manifest.json", "w") as fh:
        json.dump({"recommended_embargo_days": 7}, fh)

    pd.DataFrame(market_rows).to_parquet(market_dir / "market_ohlcv.parquet", index=False)
    with open(market_dir / "market_manifest.json", "w") as fh:
        json.dump({"snapshot_id": "market-snap"}, fh)

    keep = ["log_ret_1d", "realized_vol_7d", "momentum_7_30", "market_data_available", "is_forward_filled_market"]
    with open(feat_dir / "feature_manifest.json", "w") as fh:
        json.dump({"final_kept_feature_count": len(keep)}, fh)
    with open(feat_dir / "feature_keep_list.json", "w") as fh:
        json.dump({"kept_features": keep}, fh)


def test_downstream_agents_run_end_to_end(tmp_path):
    cfg = _cfg(tmp_path)
    _write_inputs(tmp_path)

    assert ModelAgent(cfg).execute(max_retries=1)
    assert PortfolioAgent(cfg).execute(max_retries=1)
    assert BacktestAgent(cfg).execute(max_retries=1)

    # Canonical filenames (post-refactor) — not the legacy per-model/per-strategy names.
    preds_path = tmp_path / "data" / "predictions" / "model_predictions.parquet"
    alloc_path = tmp_path / "data" / "allocations" / "allocations_from_predictions.parquet"
    summary_path = tmp_path / "data" / "backtests" / "backtest_summary.parquet"
    for expected in (preds_path, alloc_path, summary_path):
        assert expected.exists(), f"missing canonical pipeline output: {expected}"

    preds = pd.read_parquet(preds_path)
    assert {"date_ts", "symbol", "model_name", "horizon_days", "prediction"}.issubset(preds.columns)
    assert not preds.empty

    alloc = pd.read_parquet(alloc_path)
    assert {"date_ts", "symbol", "weight", "strategy_name"}.issubset(alloc.columns)
    assert not alloc.empty

    summary = pd.read_parquet(summary_path)
    assert {"strategy_name", "sharpe", "total_return"}.issubset(summary.columns)
    assert not summary.empty
