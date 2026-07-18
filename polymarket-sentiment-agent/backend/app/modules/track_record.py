"""Track record: join emitted predictions to real Polymarket resolutions and
score them with standard metrics (Brier, log-loss, calibration).

Honesty rules baked in:
  - Only predictions that stored a real model probability are scored.
  - Outcomes come from Polymarket's public Gamma API (closed=true markets carry
    the resolved outcome); nothing is invented.
  - Below a minimum resolved-sample threshold the summary returns
    status="insufficient_data" instead of a noisy curve.
  - The record's start date is the earliest stored prediction — reported as-is.
"""
from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx
from sqlalchemy import select

from ..config import settings
from ..database import session_scope
from ..models import MarketResolution, PredictionRecord, Trade

log = logging.getLogger("track_record")

GAMMA = "https://gamma-api.polymarket.com"

# Below this many resolved predictions we refuse to show metrics/curves.
MIN_RESOLVED_FOR_METRICS = 10
_EPS = 1e-6


def _safe_loads(v) -> list:
    if isinstance(v, list):
        return v
    try:
        return json.loads(v) if v else []
    except Exception:
        return []


def parse_resolution(market_obj: Dict[str, Any]) -> Optional[str]:
    """Return the winning outcome name for a closed Gamma market, else None.

    A resolved Gamma market is `closed: true` with an `outcomePrices` array in
    which the winning outcome settles to ~1.0 and the losers to ~0.0.
    """
    if not market_obj or not market_obj.get("closed"):
        return None
    outcomes = [str(o) for o in _safe_loads(market_obj.get("outcomes"))]
    prices = _safe_loads(market_obj.get("outcomePrices"))
    if not outcomes or len(prices) != len(outcomes):
        return None
    try:
        fprices = [float(p) for p in prices]
    except (TypeError, ValueError):
        return None
    top = max(range(len(fprices)), key=lambda i: fprices[i])
    # Require a decisive settlement (avoid mid-priced/ambiguous rows).
    if fprices[top] < 0.99:
        return None
    return outcomes[top]


async def _fetch_market(client: httpx.AsyncClient, condition_id: str) -> Optional[Dict[str, Any]]:
    try:
        r = await client.get(
            f"{GAMMA}/markets", params={"condition_ids": condition_id, "limit": 1}, timeout=15.0
        )
        r.raise_for_status()
        arr = r.json()
        if isinstance(arr, list) and arr:
            return arr[0]
    except Exception as e:
        log.warning("Gamma resolution lookup failed for %s: %s", condition_id, e)
    return None


async def resolve_open_predictions(limit: int = 200) -> int:
    """Resolve any predicted markets that have since closed. Returns #newly resolved."""
    with session_scope() as s:
        predicted = {r[0] for r in s.execute(select(PredictionRecord.condition_id)).all()}
        already = {r[0] for r in s.execute(select(MarketResolution.condition_id)).all()}
    pending = [cid for cid in predicted if cid and cid not in already][:limit]
    if not pending:
        return 0

    resolved = 0
    async with httpx.AsyncClient() as client:
        for cid in pending:
            market_obj = await _fetch_market(client, cid)
            if market_obj is None:
                continue
            winner = parse_resolution(market_obj)
            if winner is None:
                continue
            with session_scope() as s:
                if s.get(MarketResolution, cid) is not None:
                    continue
                s.add(MarketResolution(
                    condition_id=cid,
                    resolved_outcome=winner,
                    resolved_at=datetime.now(timezone.utc),
                    source="gamma",
                    raw=json.dumps({
                        "outcomes": market_obj.get("outcomes"),
                        "outcomePrices": market_obj.get("outcomePrices"),
                        "umaResolutionStatus": market_obj.get("umaResolutionStatus"),
                    }),
                ))
            resolved += 1
    log.info("Resolved %s/%s pending predicted markets", resolved, len(pending))
    return resolved


def backfill_from_trades() -> int:
    """Seed the prediction log from historical trades (genuinely stored data).

    Each Trade recorded a model_probability on a condition_id at a timestamp, so
    it reconstructs to a real prediction. Rows are marked backfilled=True. Only
    trades with no existing prediction for the same (signal, condition, outcome)
    are inserted, so this is idempotent.
    """
    inserted = 0
    with session_scope() as s:
        existing = {
            (r.signal_id, r.condition_id, r.outcome)
            for r in s.execute(select(
                PredictionRecord.signal_id, PredictionRecord.condition_id, PredictionRecord.outcome
            )).all()
        }
        for t in s.execute(select(Trade)).scalars().all():
            key = (t.signal_id, t.condition_id, t.outcome)
            if key in existing:
                continue
            s.add(PredictionRecord(
                created_at=t.created_at,
                condition_id=t.condition_id,
                token_id="",
                outcome=t.outcome,
                market_question=t.market_question or "",
                model_probability=float(t.model_probability),
                market_probability=float(t.price),
                edge=float(t.edge),
                llm_provider="",
                model_version="reconstructed_from_trade",
                signal_id=t.signal_id,
                backfilled=True,
                demo=bool(t.demo),
            ))
            existing.add(key)
            inserted += 1
    return inserted


def _resolved_rows(include_demo: bool) -> List[Dict[str, Any]]:
    """Predictions joined to their market resolution, with a binary actual."""
    rows: List[Dict[str, Any]] = []
    with session_scope() as s:
        resolutions = {r.condition_id: r for r in s.execute(select(MarketResolution)).scalars().all()}
        for p in s.execute(select(PredictionRecord)).scalars().all():
            if p.demo and not include_demo:
                continue
            res = resolutions.get(p.condition_id)
            if res is None:
                continue
            actual = 1 if str(res.resolved_outcome).lower() == str(p.outcome).lower() else 0
            rows.append({
                "id": p.id,
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "condition_id": p.condition_id,
                "market_question": p.market_question,
                "outcome": p.outcome,
                "model_probability": round(float(p.model_probability), 4),
                "market_probability": round(float(p.market_probability), 4),
                "resolved_outcome": res.resolved_outcome,
                "actual": actual,
                "backfilled": bool(p.backfilled),
                "model_version": p.model_version,
                "llm_provider": p.llm_provider,
            })
    rows.sort(key=lambda r: r["created_at"] or "")
    return rows


def _brier(probs: List[float], actuals: List[int]) -> float:
    return sum((p - a) ** 2 for p, a in zip(probs, actuals)) / len(probs)


def _log_loss(probs: List[float], actuals: List[int]) -> float:
    total = 0.0
    for p, a in zip(probs, actuals):
        p = min(max(p, _EPS), 1 - _EPS)
        total += -(a * math.log(p) + (1 - a) * math.log(1 - p))
    return total / len(probs)


def _calibration(probs: List[float], actuals: List[int], n_bins: int = 5) -> List[Dict[str, Any]]:
    bins: List[Dict[str, Any]] = []
    for b in range(n_bins):
        lo, hi = b / n_bins, (b + 1) / n_bins
        idx = [i for i, p in enumerate(probs) if (p >= lo and (p < hi or (b == n_bins - 1 and p <= hi)))]
        if not idx:
            bins.append({"bin_lower": round(lo, 2), "bin_upper": round(hi, 2), "count": 0,
                         "mean_predicted": None, "observed_frequency": None})
            continue
        mp = sum(probs[i] for i in idx) / len(idx)
        of = sum(actuals[i] for i in idx) / len(idx)
        bins.append({"bin_lower": round(lo, 2), "bin_upper": round(hi, 2), "count": len(idx),
                     "mean_predicted": round(mp, 4), "observed_frequency": round(of, 4)})
    return bins


def compute_track_record(include_demo: bool = False,
                         min_resolved: int = MIN_RESOLVED_FOR_METRICS) -> Dict[str, Any]:
    """Score the resolved prediction log. Metrics only above min_resolved rows."""
    with session_scope() as s:
        total_predictions = s.query(PredictionRecord).count() if include_demo else \
            s.query(PredictionRecord).filter(PredictionRecord.demo.is_(False)).count()
        first = s.execute(
            select(PredictionRecord.created_at).order_by(PredictionRecord.created_at.asc()).limit(1)
        ).scalar()

    rows = _resolved_rows(include_demo)
    start_date = first.isoformat() if first else None
    resolved_n = len(rows)

    base = {
        "start_date": start_date,
        "total_predictions": total_predictions,
        "resolved_predictions": resolved_n,
        "pending_predictions": total_predictions - resolved_n,
        "min_resolved_for_metrics": min_resolved,
        "methodology": (
            "Each row is a model probability the agent emitted on a Polymarket "
            "outcome at a point in time. Outcomes come from Polymarket's public "
            "Gamma API (closed markets). Metrics are computed only over resolved "
            "rows; below the threshold we report insufficient data rather than a "
            "noisy curve. This is a young, live, out-of-sample record — small "
            "samples, favorite-longshot bias, and LLM-sentiment lookahead risk all apply."
        ),
    }

    if resolved_n < min_resolved:
        base["status"] = "insufficient_data"
        base["log"] = rows
        return base

    probs = [r["model_probability"] for r in rows]
    mkt = [r["market_probability"] for r in rows]
    actuals = [r["actual"] for r in rows]
    accuracy = sum(1 for p, a in zip(probs, actuals) if (p >= 0.5) == bool(a)) / resolved_n

    base["status"] = "ok"
    base["metrics"] = {
        "accuracy": round(accuracy, 4),
        "brier_score": round(_brier(probs, actuals), 4),
        "log_loss": round(_log_loss(probs, actuals), 4),
        "market_baseline_brier": round(_brier(mkt, actuals), 4),
        "base_rate": round(sum(actuals) / resolved_n, 4),
    }
    base["calibration"] = _calibration(probs, actuals)
    base["log"] = rows
    return base
