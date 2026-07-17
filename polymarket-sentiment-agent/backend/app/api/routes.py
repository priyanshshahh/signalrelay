"""Dashboard REST endpoints — read-mostly with a couple of admin actions."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc

from ..auth import require_admin_token
from ..config import settings
from ..database import session_scope
from ..models import AgentState, LogEvent, MarketSnapshot, NewsItem, Signal, Trade
from ..modules import ingestion, intelligence, market as oracle, risk
from ..orchestrator import agent_loop, _run_once
from ..schemas import (
    KillSwitchIn,
    MarketSnapshotOut,
    NewsItemOut,
    PortfolioOut,
    SignalOut,
    StatusOut,
    TradeOut,
)

router = APIRouter()


# ---------- Public (no auth, no x402) — for external / Lovable pings -----

@router.get("/public/ping")
def public_ping():
    """Public health + agent snapshot for external integrations."""
    with session_scope() as s:
        last = s.get(AgentState, "last_loop_at")
        trade_count = s.query(Trade).count()
        signal_count = s.query(Signal).count()
    x402_on = settings.x402_enabled and bool(settings.x402_pay_to)
    return {
        "ok": True,
        "service": "poly-agent",
        "mode": settings.trading_mode,
        "x402_enabled": x402_on,
        "x402_price": settings.x402_price if x402_on else None,
        "x402_network": settings.x402_network if x402_on else None,
        "last_loop_at": last.value if last else None,
        "trade_count": trade_count,
        "signal_count": signal_count,
        "paywalled_endpoints": [
            "GET /api/trade/{trade_id}/rationale",
        ],
        "docs": "https://github.com/priyanshshahh/polymarket-sentiment-agent",
    }


# ---------- Status & control ---------------------------------------------

def _llm_provider() -> str:
    if settings.groq_api_key:
        return "groq"
    if settings.openai_api_key:
        return "openai"
    if settings.anthropic_api_key:
        return "anthropic"
    return "heuristic"


@router.get("/status", response_model=StatusOut)
def status():
    with session_scope() as s:
        last = s.get(AgentState, "last_loop_at")
        ks = s.get(AgentState, "kill_switch")
        kill = (ks.value.lower() == "true") if ks and ks.value else settings.kill_switch
        last_dt = None
        if last and last.value:
            try:
                last_dt = datetime.fromisoformat(last.value)
            except Exception:
                pass
        watched = s.query(MarketSnapshot.condition_id).distinct().count()

    return StatusOut(
        mode=settings.trading_mode,
        kill_switch=kill,
        loop_interval_seconds=settings.loop_interval_seconds,
        edge_threshold=settings.edge_threshold,
        min_signal_confidence=settings.min_signal_confidence,
        max_usdc_per_trade=settings.max_usdc_per_trade,
        daily_drawdown_usdc=settings.daily_drawdown_usdc,
        llm_provider=_llm_provider(),
        watched_markets=watched,
        last_loop_at=last_dt,
    )


@router.post("/kill-switch", dependencies=[Depends(require_admin_token)])
def kill_switch(body: KillSwitchIn):
    risk.set_kill_switch(body.enabled)
    return {"kill_switch": body.enabled}


@router.post("/loop/run-once", dependencies=[Depends(require_admin_token)])
async def run_once():
    await _run_once()
    return {"ok": True}


@router.post("/loop/start", dependencies=[Depends(require_admin_token)])
def loop_start():
    agent_loop.start()
    return {"running": True}


@router.post("/loop/stop", dependencies=[Depends(require_admin_token)])
async def loop_stop():
    await agent_loop.stop()
    return {"running": False}


# ---------- Data feeds ---------------------------------------------------

@router.get("/news", response_model=List[NewsItemOut])
def list_news(limit: int = Query(50, le=200)):
    with session_scope() as s:
        rows = s.query(NewsItem).order_by(desc(NewsItem.ingested_at)).limit(limit).all()
        return [NewsItemOut.model_validate(r) for r in rows]


@router.get("/signals", response_model=List[SignalOut])
def list_signals(limit: int = Query(50, le=200)):
    with session_scope() as s:
        rows = s.query(Signal).order_by(desc(Signal.created_at)).limit(limit).all()
        return [SignalOut.model_validate(r) for r in rows]


@router.get("/markets", response_model=List[MarketSnapshotOut])
def latest_markets():
    """Latest snapshot per (condition_id, outcome)."""
    with session_scope() as s:
        # Naive: last 500 snapshots, dedupe in Python by (cid, outcome).
        rows = (
            s.query(MarketSnapshot)
            .order_by(desc(MarketSnapshot.captured_at))
            .limit(500)
            .all()
        )
        seen = set()
        out: List[MarketSnapshotOut] = []
        for r in rows:
            key = (r.condition_id, r.outcome)
            if key in seen:
                continue
            seen.add(key)
            out.append(MarketSnapshotOut.model_validate(r))
        return out


@router.get("/trades", response_model=List[TradeOut])
def list_trades(limit: int = Query(100, le=500)):
    with session_scope() as s:
        rows = s.query(Trade).order_by(desc(Trade.created_at)).limit(limit).all()
        return [TradeOut.model_validate(r) for r in rows]


@router.get("/portfolio", response_model=PortfolioOut)
def portfolio():
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).replace(tzinfo=None)
    with session_scope() as s:
        trades = s.query(Trade).filter(Trade.status == "FILLED").all()
        open_trades = [t for t in trades if t.closed_at is None]
        closed_trades = [t for t in trades if t.closed_at is not None]
        realized = sum(t.pnl_usdc or 0.0 for t in closed_trades)
        unrealized = sum(t.pnl_usdc or 0.0 for t in open_trades)
        open_size = sum(t.size_usdc for t in open_trades)

        def _naive(dt):
            return dt.replace(tzinfo=None) if dt and dt.tzinfo else dt

        daily = sum(
            t.pnl_usdc or 0.0 for t in trades if t.created_at and _naive(t.created_at) >= cutoff
        )
        # Cash = simulated starting bank - open size
        starting_cash = 1000.0
        cash = starting_cash - open_size + realized
        equity = cash + unrealized + open_size  # open positions held at cost basis
        return PortfolioOut(
            cash_usdc=round(cash, 2),
            open_positions_usdc=round(open_size, 2),
            realized_pnl_usdc=round(realized, 2),
            unrealized_pnl_usdc=round(unrealized, 2),
            total_equity_usdc=round(equity + unrealized, 2),
            daily_pnl_usdc=round(daily, 2),
            open_positions=[TradeOut.model_validate(t) for t in open_trades],
            includes_demo_data=any(t.demo for t in trades),
        )


@router.get("/trade/{trade_id}/rationale")
def trade_rationale(trade_id: int):
    """The 'why we made this trade' view — joins trade -> signal -> news -> snapshot."""
    with session_scope() as s:
        t = s.get(Trade, trade_id)
        if not t:
            return {"error": "not found"}
        sig = s.get(Signal, t.signal_id) if t.signal_id else None
        news = s.get(NewsItem, sig.news_item_id) if sig else None
        snap = s.get(MarketSnapshot, t.snapshot_id) if t.snapshot_id else None
        return {
            "demo": bool(t.demo),
            "trade": TradeOut.model_validate(t).model_dump(mode="json"),
            "signal": SignalOut.model_validate(sig).model_dump(mode="json") if sig else None,
            "news": NewsItemOut.model_validate(news).model_dump(mode="json") if news else None,
            "snapshot": MarketSnapshotOut.model_validate(snap).model_dump(mode="json") if snap else None,
        }


@router.get("/demo/rationale/{trade_id}")
def demo_rationale(trade_id: int):
    """Free, truncated TEASER of the paid rationale endpoint.

    The monetized endpoint is GET /api/trade/{id}/rationale (x402-paywalled).
    This one intentionally returns only a preview — never the full payload —
    so there is no free bypass of the paywall. Every response carries
    "demo": true.
    """
    with session_scope() as s:
        t = s.get(Trade, trade_id)
        if not t:
            return {"demo": True, "error": "not found"}
        sig = s.get(Signal, t.signal_id) if t.signal_id else None
        rationale = (sig.rationale or "") if sig else ""
        teaser = rationale[:80] + ("…" if len(rationale) > 80 else "")
        return {
            "demo": True,
            "teaser": True,
            "note": (
                "Truncated preview. The full rationale (signal, source news, "
                "market snapshot, posterior and edge) is served by "
                "GET /api/trade/{trade_id}/rationale behind an x402 paywall."
            ),
            "trade": {
                "id": t.id,
                "market_question": t.market_question,
                "outcome": t.outcome,
                "side": t.side,
                "mode": t.mode,
            },
            "signal_preview": {
                "sentiment": sig.sentiment if sig else None,
                "topic": sig.topic if sig else None,
                "rationale_preview": teaser,
            },
        }


@router.get("/logs")
def logs(limit: int = Query(100, le=500), component: Optional[str] = None):
    with session_scope() as s:
        q = s.query(LogEvent).order_by(desc(LogEvent.created_at))
        if component:
            q = q.filter(LogEvent.component == component)
        rows = q.limit(limit).all()
        return [
            {
                "id": r.id,
                "created_at": r.created_at,
                "level": r.level,
                "component": r.component,
                "message": r.message,
                "data": json.loads(r.data or "{}"),
            }
            for r in rows
        ]


@router.get("/equity-curve")
def equity_curve():
    """Time series of realized PnL for charting."""
    with session_scope() as s:
        rows = (
            s.query(Trade)
            .filter(Trade.status == "FILLED")
            .order_by(Trade.created_at)
            .all()
        )
        cum = 0.0
        points = []
        for r in rows:
            cum += r.pnl_usdc or 0.0
            points.append(
                {"t": r.created_at.isoformat(), "pnl": round(cum, 2), "demo": bool(r.demo)}
            )
        return points
