from __future__ import annotations

import numpy as np
import pandas as pd

from models.ablation import _classify_features, run_ablation


def _synthetic_panel(n_days: int = 360, symbols=None):
    """Build a FeatureAgent-shaped feature frame and a LabelAgent-shaped label frame."""
    if symbols is None:
        symbols = ["BTC", "ETH", "SOL", "ADA", "AVAX"]
    rng = np.random.default_rng(7)
    dates = pd.date_range("2022-01-01", periods=n_days, freq="D", tz="UTC")

    feat_rows = []
    label_rows = []
    for sym in symbols:
        base_ret = rng.normal(0.001, 0.02, n_days)
        # Market features (no on-chain hint tokens in the names).
        log_ret_7d = pd.Series(base_ret).rolling(7).sum().to_numpy()
        momentum_7_30 = pd.Series(base_ret).rolling(30).mean().to_numpy()
        realized_vol_30d = pd.Series(base_ret).rolling(30).std().to_numpy()
        # On-chain features (names carry ONCHAIN_HINTS tokens).
        nvt_tx_proxy = rng.normal(10, 2, n_days)
        mvrv_current = rng.normal(1.5, 0.3, n_days)
        # A weak label correlated with momentum so IC is well-defined.
        fwd = 0.5 * np.nan_to_num(momentum_7_30) + rng.normal(0, 0.02, n_days)
        for i in range(n_days):
            feat_rows.append({
                "symbol": sym,
                "date_ts": dates[i],
                "log_ret_7d": log_ret_7d[i],
                "momentum_7_30": momentum_7_30[i],
                "realized_vol_30d": realized_vol_30d[i],
                "nvt_tx_proxy": nvt_tx_proxy[i],
                "mvrv_current": mvrv_current[i],
            })
            label_rows.append({
                "symbol": sym,
                "date_ts": dates[i],
                "horizon_days": 7,
                "label_fwd_logret": fwd[i],
            })
    return pd.DataFrame(feat_rows), pd.DataFrame(label_rows)


_CFG = {
    "project": {"seed": 42},
    "modeling": {
        "default_horizon": 7,
        "walk_forward": {
            "initial_train_days": 120,
            "test_days": 20,
            "step_days": 20,
            "embargo_days": 7,
            "min_train_rows": 100,
            "min_test_rows": 10,
            "min_test_symbols": 3,
        },
    },
}


def test_classify_features_splits_market_and_onchain():
    feat, label = _synthetic_panel()
    panel = feat.merge(label, on=["symbol", "date_ts"])
    market_only, all_features = _classify_features(panel, "label_fwd_logret")
    assert "nvt_tx_proxy" not in market_only
    assert "mvrv_current" not in market_only
    assert "log_ret_7d" in market_only
    assert "nvt_tx_proxy" in all_features
    assert "mvrv_current" in all_features
    assert set(market_only).issubset(set(all_features))


def test_run_ablation_produces_both_variants_with_folds(tmp_path):
    feat, label = _synthetic_panel()
    results = run_ablation(feat, label, _CFG, output_dir=tmp_path)

    for variant in ("market_only", "market_plus_onchain"):
        assert variant in results
        r = results[variant]
        assert "error" not in r, r
        assert r["n_folds"] >= 1
        assert r["mean_rank_ic"] is not None
        assert r["label_col"] == "label_fwd_logret"

    # market_plus_onchain must use strictly more features than market_only.
    assert results["market_plus_onchain"]["n_features"] > results["market_only"]["n_features"]

    # Study is persisted to disk.
    assert (tmp_path / "ablation_results.json").exists()


def test_run_ablation_reports_missing_label():
    feat, _ = _synthetic_panel()
    bad_label = pd.DataFrame({"symbol": ["BTC"], "date_ts": [pd.Timestamp("2022-01-01", tz="UTC")]})
    out = run_ablation(feat, bad_label, _CFG)
    assert out == {"error": "No label column found"}
