#!/usr/bin/env python3
"""
CHF Smoke Test
==============
Fast, fully-offline sanity check that the core modules import and their current
public APIs work. This is a lightweight complement to the pytest suite (run
`make test` for the real coverage), not a substitute for it.

Usage:
  python scripts/smoke_test.py

Exit code 0 = all checks passed, 1 = one or more failed.
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import pandas as pd

PASS = 0
FAIL = 0
RESULTS = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        RESULTS.append(f"  [PASS] {name}")
    else:
        FAIL += 1
        RESULTS.append(f"  [FAIL] {name}" + (f" — {detail}" if detail else ""))


def run_smoke_test():
    print("=" * 60)
    print("CHF Smoke Test")
    print("=" * 60)

    # ── 1. Imports ────────────────────────────────────────────────
    print("\n[1] Testing imports...")
    modules_to_import = [
        "configs.config",
        "agents.base",
        "agents.universe_agent",
        "agents.market_data_agent",
        "agents.onchain_agent",
        "agents.feature_agent",
        "agents.label_agent",
        "agents.model_agent",
        "agents.portfolio_agent",
        "agents.backtest_agent",
        "features.feature_engineering",
        "models.walk_forward",
        "models.ablation",
        "pipelines.pipeline_runner",
        "pipelines.duckdb_engine",
    ]
    for mod in modules_to_import:
        try:
            __import__(mod)
            check(f"import {mod}", True)
        except Exception as e:
            check(f"import {mod}", False, str(e))

    # ── 2. Feature engineering ────────────────────────────────────
    print("\n[2] Testing feature engineering...")
    try:
        from features.feature_engineering import (
            safe_log_ratio, rolling_zscore, rolling_downside_vol, rolling_beta_and_corr,
        )
        prices = pd.Series(100 * np.cumprod(1 + np.random.default_rng(42).normal(0.001, 0.02, 200)))
        log_ret = safe_log_ratio(prices, prices.shift(7))
        check("safe_log_ratio", not log_ret.isna().all())
        check("rolling_zscore", not rolling_zscore(prices, 30).isna().all())
        daily = np.log(prices / prices.shift(1))
        check("rolling_downside_vol", not rolling_downside_vol(daily, 30).isna().all())
        btc_ret = pd.Series(np.random.default_rng(1).normal(0.001, 0.02, 200))
        beta, corr = rolling_beta_and_corr(daily, btc_ret, 60)
        check("rolling_beta_and_corr", not beta.isna().all())
    except Exception as e:
        check("feature_engineering module", False, str(e))
        traceback.print_exc()

    # ── 3. Purged walk-forward splits ─────────────────────────────
    print("\n[3] Testing purged walk-forward splits...")
    try:
        from models.walk_forward import generate_purged_walk_forward_splits
        rng = np.random.default_rng(42)
        symbols = ["BTC", "ETH", "SOL", "ADA", "UNI"]
        dates = pd.date_range("2022-01-01", periods=400, freq="D", tz="UTC")
        rows = [{"date_ts": d, "symbol": s, "f": rng.normal()} for s in symbols for d in dates]
        panel = pd.DataFrame(rows).sort_values(["date_ts", "symbol"]).reset_index(drop=True)
        splits = list(generate_purged_walk_forward_splits(
            panel, initial_train_days=200, test_days=30, step_days=30,
            embargo_days=7, min_train_rows=100, min_test_rows=20, min_test_symbols=3,
        ))
        check("walk-forward produces splits", len(splits) >= 1, f"got {len(splits)}")
        for i, sp in enumerate(splits):
            check(f"fold {i} train/test disjoint", len(set(sp.train_idx) & set(sp.test_idx)) == 0)
            check(f"fold {i} train precedes test", max(sp.train_idx) < min(sp.test_idx))
    except Exception as e:
        check("walk_forward module", False, str(e))
        traceback.print_exc()

    # ── 4. Ablation study ─────────────────────────────────────────
    print("\n[4] Testing ablation study...")
    try:
        from models.ablation import run_ablation
        rng = np.random.default_rng(42)
        symbols = ["BTC", "ETH", "SOL", "BNB", "ADA"]
        dates = pd.date_range("2022-01-01", periods=360, freq="D", tz="UTC")
        feat_rows, label_rows = [], []
        for s in symbols:
            for d in dates:
                feat_rows.append({
                    "symbol": s, "date_ts": d,
                    "log_ret_7d": rng.normal(), "momentum_7_30": rng.normal(),
                    "nvt_tx_proxy": rng.normal(), "mvrv_current": rng.normal(),
                })
                label_rows.append({"symbol": s, "date_ts": d, "horizon_days": 7, "label_fwd_logret": rng.normal(0, 0.05)})
        cfg = {"project": {"seed": 42}, "modeling": {"default_horizon": 7, "walk_forward": {
            "initial_train_days": 120, "test_days": 20, "step_days": 20, "embargo_days": 7,
            "min_train_rows": 100, "min_test_rows": 10, "min_test_symbols": 3}}}
        results = run_ablation(pd.DataFrame(feat_rows), pd.DataFrame(label_rows), cfg, output_dir=None)
        check("ablation market_only", "market_only" in results and "error" not in results["market_only"])
        check("ablation market_plus_onchain", "market_plus_onchain" in results)
        check("ablation IC computed", results.get("market_only", {}).get("mean_rank_ic") is not None)
    except Exception as e:
        check("ablation module", False, str(e))
        traceback.print_exc()

    # ── 5. DuckDB engine ──────────────────────────────────────────
    print("\n[5] Testing DuckDB engine...")
    try:
        from pipelines.duckdb_engine import DuckDBEngine
        engine = DuckDBEngine({"_project_root": str(PROJECT_ROOT), "paths": {}})
        df = pd.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
        result = engine.query_dataframe(df, "SELECT sum(a) AS total FROM df")
        check("duckdb query", int(result["total"].iloc[0]) == 6)
    except Exception as e:
        check("duckdb_engine", False, str(e))
        traceback.print_exc()

    # ── Summary ───────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("SMOKE TEST RESULTS")
    print("=" * 60)
    for line in RESULTS:
        print(line)
    print()
    print(f"PASSED: {PASS}  |  FAILED: {FAIL}  |  TOTAL: {PASS + FAIL}")
    print("=" * 60)

    if FAIL > 0:
        print(f"\n{FAIL} check(s) FAILED.")
        sys.exit(1)
    print("\nALL CHECKS PASSED")
    sys.exit(0)


if __name__ == "__main__":
    run_smoke_test()
