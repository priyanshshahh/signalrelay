"""
CHF Ablation Study
==================
Runs two model variants to isolate the marginal value of on-chain features:

  1. market_only        — only price/volume-derived features
  2. market_plus_onchain — all features, including on-chain fundamentals

Feature membership is classified dynamically from the real FeatureAgent output
(via the same ``ONCHAIN_HINTS`` token list ``ModelAgent`` uses to build its
``market_only`` / ``market_plus_onchain`` feature sets), so this study never
drifts out of sync with the pipeline's actual column names. Each variant runs
the pipeline's canonical purged + embargoed walk-forward CV and reports Rank IC.

Run command
-----------
python main.py ablation

Success criterion
-----------------
data/reports/ablation_results.json exists with both variants' Rank IC values.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from agents.model_agent import DIAGNOSTIC_FEATURE_COLUMNS, MODEL_METADATA_COLUMNS, ONCHAIN_HINTS

# Preferred label columns produced by LabelAgent, in priority order.
_LABEL_COLUMN_CANDIDATES = ("label_fwd_logret", "label_simple_return")


def _is_onchain(col: str) -> bool:
    lower = col.lower()
    return any(hint in lower for hint in ONCHAIN_HINTS)


def _classify_features(panel: pd.DataFrame, label_col: str) -> tuple[list[str], list[str]]:
    """Return (market_only_features, all_features) from the panel's numeric columns."""
    reserved = set(MODEL_METADATA_COLUMNS) | set(DIAGNOSTIC_FEATURE_COLUMNS) | {label_col}
    candidates: List[str] = []
    for col in panel.columns:
        if col in reserved or col.startswith("label_") or col in ("symbol", "date_ts", "horizon_days"):
            continue
        if pd.api.types.is_numeric_dtype(panel[col]):
            candidates.append(col)
    market_only = sorted(c for c in candidates if not _is_onchain(c))
    all_features = sorted(candidates)
    return market_only, all_features


def run_ablation(
    feature_df: pd.DataFrame,
    label_df: pd.DataFrame,
    cfg: Dict[str, Any],
    output_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Run ablation study comparing market-only vs market+onchain feature sets.

    Parameters
    ----------
    feature_df : pd.DataFrame
        Full feature store (real FeatureAgent output), keyed by symbol + date_ts.
    label_df : pd.DataFrame
        Label DataFrame (real LabelAgent output) with a forward-return label column.
    cfg : dict
        Project config dict.
    output_dir : Path, optional
        Where to save ablation_results.json.

    Returns
    -------
    dict with keys 'market_only' and 'market_plus_onchain', each containing
    walk-forward Rank IC statistics.
    """
    from models.walk_forward import generate_purged_walk_forward_splits

    model_cfg = cfg.get("modeling", {})
    target_horizon = int(model_cfg.get("default_horizon", 7))

    # Resolve the label column against the real LabelAgent schema.
    label_col = next((c for c in _LABEL_COLUMN_CANDIDATES if c in label_df.columns), None)
    if label_col is None:
        fwd_cols = [c for c in label_df.columns if "return" in c.lower() and c.startswith("label")]
        if not fwd_cols:
            return {"error": "No label column found"}
        label_col = fwd_cols[0]

    labels = label_df
    if "horizon_days" in labels.columns:
        labels = labels[labels["horizon_days"] == target_horizon].copy()

    panel = feature_df.merge(
        labels[["symbol", "date_ts", label_col]],
        on=["symbol", "date_ts"],
        how="inner",
    ).dropna(subset=[label_col])
    panel = panel.sort_values(["date_ts", "symbol"]).reset_index(drop=True)

    market_only, all_features = _classify_features(panel, label_col)

    # Walk-forward parameters (scale-aware; small studies pass smaller windows via cfg).
    wf = model_cfg.get("walk_forward", {}) if isinstance(model_cfg.get("walk_forward"), dict) else {}
    split_kwargs = dict(
        horizon_days=target_horizon,
        initial_train_days=int(wf.get("initial_train_days", model_cfg.get("initial_train_days", 252))),
        test_days=int(wf.get("test_days", model_cfg.get("test_size_days", 30))),
        step_days=int(wf.get("step_days", model_cfg.get("step_days", 30))),
        embargo_days=int(wf.get("embargo_days", model_cfg.get("embargo_days", target_horizon))),
        min_train_rows=int(wf.get("min_train_rows", 200)),
        min_test_rows=int(wf.get("min_test_rows", 20)),
        min_test_symbols=int(wf.get("min_test_symbols", 3)),
    )
    seed = int(cfg.get("project", {}).get("seed", 42))

    results: Dict[str, Any] = {}
    for variant_name, feature_cols in [
        ("market_only", market_only),
        ("market_plus_onchain", all_features),
    ]:
        available = [c for c in feature_cols if c in panel.columns]
        if not available:
            results[variant_name] = {"error": f"No features available for {variant_name}"}
            continue

        fold_ics: List[float] = []
        fold_hit_rates: List[float] = []

        for split in generate_purged_walk_forward_splits(panel, **split_kwargs):
            train = panel.iloc[split.train_idx]
            test = panel.iloc[split.test_idx]
            X_train = train[available].replace([np.inf, -np.inf], np.nan)
            X_test = test[available].replace([np.inf, -np.inf], np.nan)
            medians = X_train.median(numeric_only=True)
            X_train = X_train.fillna(medians).fillna(0.0)
            X_test = X_test.fillna(medians).fillna(0.0)
            y_train = train[label_col].to_numpy()
            y_test = test[label_col].to_numpy()

            try:
                import lightgbm as lgb
                model = lgb.LGBMRegressor(
                    n_estimators=100,
                    learning_rate=0.05,
                    max_depth=4,
                    num_leaves=15,
                    random_state=seed,
                    verbose=-1,
                )
            except ImportError:
                from sklearn.ensemble import RandomForestRegressor
                model = RandomForestRegressor(n_estimators=100, max_depth=5, random_state=seed)

            model.fit(X_train, y_train)
            preds = np.asarray(model.predict(X_test), dtype=float)

            from scipy.stats import spearmanr
            ic, _ = spearmanr(preds, y_test)
            if not np.isnan(ic):
                fold_ics.append(float(ic))
            fold_hit_rates.append(float(np.mean(np.sign(preds) == np.sign(y_test))))

        results[variant_name] = {
            "n_features": len(available),
            "features_used": available,
            "n_folds": len(fold_ics),
            "mean_rank_ic": float(np.mean(fold_ics)) if fold_ics else None,
            "std_rank_ic": float(np.std(fold_ics)) if fold_ics else None,
            "mean_hit_rate": float(np.mean(fold_hit_rates)) if fold_hit_rates else None,
            "fold_ics": fold_ics,
            "label_col": label_col,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    # Compute marginal value of on-chain features
    if "market_only" in results and "market_plus_onchain" in results:
        mo_ic = results["market_only"].get("mean_rank_ic")
        mc_ic = results["market_plus_onchain"].get("mean_rank_ic")
        if mo_ic is not None and mc_ic is not None:
            results["onchain_marginal_ic_lift"] = round(mc_ic - mo_ic, 6)
            results["onchain_features_help"] = mc_ic > mo_ic

    # Save results
    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / "ablation_results.json"
        with open(out_path, "w") as f:
            json.dump(results, f, indent=2, default=str)
        print(f"[Ablation] Results saved to {out_path}")

    return results


def print_ablation_summary(results: Dict[str, Any]) -> None:
    """Print a human-readable ablation summary."""
    print("\n" + "=" * 60)
    print("ABLATION STUDY RESULTS")
    print("=" * 60)
    for variant in ("market_only", "market_plus_onchain"):
        if variant not in results:
            continue
        r = results[variant]
        if "error" in r:
            print(f"\n[{variant}] ERROR: {r['error']}")
            continue
        print(f"\n[{variant}]")
        print(f"  Features used : {r['n_features']}")
        print(f"  Folds         : {r['n_folds']}")
        ic = r.get("mean_rank_ic")
        std = r.get("std_rank_ic")
        hr = r.get("mean_hit_rate")
        print(f"  Mean Rank IC  : {ic:.4f} ± {std:.4f}" if ic is not None else "  Mean Rank IC  : N/A")
        print(f"  Mean Hit Rate : {hr:.4f}" if hr is not None else "  Mean Hit Rate : N/A")

    lift = results.get("onchain_marginal_ic_lift")
    if lift is not None:
        print(f"\nOn-chain marginal IC lift : {lift:+.4f}")
        print(f"On-chain features help    : {results.get('onchain_features_help')}")
    print("=" * 60 + "\n")
