"""The conductor. Runs the agent loop and coordinates modules.

One loop = (Scout pull) -> (Quant analyze) -> (Oracle refresh) ->
          (decision: any edge?) -> (Overseer check) -> (Trader execute) ->
          (mark-to-market).

If any sub-step throws, the loop logs and moves on. Modules are
designed to be independently restartable.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from .config import settings
from .database import session_scope
from .models import AgentState, MarketSnapshot, NewsItem, PredictionRecord, Signal
from .modules import execution, ingestion, intelligence, market, risk

log = logging.getLogger("orchestrator")


def _model_version(provider: str) -> str:
    """A stable provenance string for the 'model' that produced a probability.

    There is no MLflow here: the estimator is the deterministic Bayesian update
    over an LLM sentiment label, so the version is (provider:model)."""
    model = {
        "groq": settings.groq_model,
        "openai": settings.openai_model,
        "anthropic": settings.anthropic_model,
    }.get((provider or "").lower(), "")
    return f"{provider}:{model}" if model else (provider or "heuristic")


def _log_prediction(sig: Signal, snap: MarketSnapshot, target: float, edge: float) -> None:
    """Append one falsifiable prediction to the track-record log."""
    try:
        with session_scope() as s:
            s.add(PredictionRecord(
                condition_id=snap.condition_id,
                token_id=snap.token_id,
                outcome=snap.outcome,
                market_question=snap.question,
                model_probability=float(target),
                market_probability=float(snap.price),
                edge=float(edge),
                sentiment=sig.sentiment or "",
                confidence=float(sig.confidence or 0.0),
                llm_provider=sig.llm_provider or "heuristic",
                model_version=_model_version(sig.llm_provider or "heuristic"),
                signal_id=sig.id,
                demo=bool(getattr(sig, "demo", False)),
            ))
    except Exception:
        log.exception("Failed to log prediction for signal %s", getattr(sig, "id", "?"))


def _set_state(key: str, value: str) -> None:
    with session_scope() as s:
        row = s.get(AgentState, key)
        if row is None:
            s.add(AgentState(key=key, value=value))
        else:
            row.value = value


def _topic_to_keywords(topic: str) -> List[str]:
    topic = (topic or "").upper()
    return {
        "BTC": ["bitcoin", "btc"],
        "ETH": ["ethereum", "eth"],
        "SEC": ["sec", "securities"],
        "FED": ["fed", "rate", "fomc", "powell"],
        "ETF": ["etf"],
        "MACRO": ["inflation", "cpi", "gdp", "jobs"],
    }.get(topic, [])


def _match_market_for_signal(
    signal: Signal, snapshots: List[MarketSnapshot]
) -> Optional[MarketSnapshot]:
    """Pick the YES-side snapshot whose question best matches the signal topic.

    Crude but effective for an MVP: substring / keyword overlap.
    """
    if not snapshots:
        return None
    keywords = _topic_to_keywords(signal.topic or "")
    if not keywords:
        keywords = settings.keyword_list

    best: Tuple[int, Optional[MarketSnapshot]] = (0, None)
    for snap in snapshots:
        if snap.outcome.lower() not in {"yes", "true"}:
            continue
        blob = f"{snap.question} {snap.slug}".lower()
        score = sum(1 for k in keywords if k in blob)
        if score > best[0]:
            best = (score, snap)
    return best[1]


def _decide_side_and_target_prob(signal: Signal, snap_price: float) -> Tuple[str, float]:
    """Compute the decision-time target probability.

    Key insight: the *market price* is the prior. The Signal stored a
    posterior from a flat 0.5 prior (useful for analytics), but at trade
    time we re-run the Bayesian update against the actual market.

    Returns (side, target_prob). Side is always BUY in MVP: we BUY YES
    if news pushed posterior > price, otherwise we'd want NO — which we
    skip for clarity. Extend to flip-to-NO in v2.
    """
    target, _lr = intelligence.bayesian_update(snap_price, signal.sentiment, signal.confidence)
    return "BUY", target


async def _run_once() -> None:
    log.info("---- agent loop tick ----")

    # 1) Scout
    try:
        new_items = await ingestion.ingest_once()
    except Exception:
        log.exception("Ingestion failed")
        new_items = []

    # 2) Quant — only analyze fresh items to keep LLM costs sane
    signals: List[Signal] = []
    for item in new_items:
        try:
            sig = await intelligence.analyze_news_item(item, prior=0.5)
            if sig:
                signals.append(sig)
        except Exception:
            log.exception("Analysis failed for item %s", getattr(item, "id", "?"))

    # 3) Oracle
    try:
        markets = await market.fetch_markets()
        snapshots = market.persist_snapshot(markets)
    except Exception:
        log.exception("Market fetch failed")
        markets, snapshots = [], []

    # 4) Decide + 5) Risk + 6) Execute
    for sig in signals:
        if sig.confidence < settings.min_signal_confidence:
            risk.record_event(
                "decision",
                "INFO",
                "Skip: confidence below threshold",
                {"signal_id": sig.id, "confidence": sig.confidence},
            )
            continue

        snap = _match_market_for_signal(sig, snapshots)
        if snap is None:
            risk.record_event(
                "decision",
                "INFO",
                "Skip: no matching market",
                {"signal_id": sig.id, "topic": sig.topic},
            )
            continue

        side, target = _decide_side_and_target_prob(sig, snap.price)
        edge = target - snap.price

        # Log every emitted probability estimate to the track record, whether or
        # not it clears the edge threshold and trades below.
        _log_prediction(sig, snap, target, edge)

        plan = risk.TradePlan(
            condition_id=snap.condition_id,
            market_question=snap.question,
            outcome=snap.outcome,
            token_id=snap.token_id,
            side=side,
            price=snap.price,
            model_probability=target,
            edge=edge,
            size_usdc=settings.max_usdc_per_trade,
            signal_id=sig.id,
            snapshot_id=snap.id,
            idem_key=execution.make_idem_key(snap.condition_id, snap.outcome, sig.id),
        )
        decision = risk.evaluate(plan)
        if not decision.approved:
            risk.record_event(
                "risk",
                "INFO",
                f"Trade rejected: {decision.reason}",
                {"plan": plan.__dict__},
            )
            continue

        try:
            trade = execution.execute(decision.plan)
            if trade is not None:
                risk.record_event(
                    "trade",
                    "INFO",
                    "Trade fired",
                    {"trade_id": trade.id, "edge": trade.edge, "size": trade.size_usdc},
                )
        except Exception as e:
            log.exception("Execution failed")
            risk.record_event("trade", "ERROR", f"Execution failed: {e}", {})

    # 7) Mark-to-market against the freshest snapshot table.
    price_lookup: Dict[Tuple[str, str], float] = {
        (snap.condition_id, snap.outcome.lower()): snap.price for snap in snapshots
    }

    def _lookup(cid: str, outcome: str) -> Optional[float]:
        return price_lookup.get((cid, outcome.lower()))

    try:
        execution.mark_to_market(_lookup)
    except Exception:
        log.exception("Mark-to-market failed")

    _set_state("last_loop_at", datetime.now(timezone.utc).isoformat())


class AgentLoop:
    """Runs `_run_once` on a fixed interval as an asyncio task."""

    def __init__(self) -> None:
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await _run_once()
            except Exception:
                log.exception("Loop tick crashed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=settings.loop_interval_seconds)
            except asyncio.TimeoutError:
                pass

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run())
        log.info("Agent loop started; interval=%ss", settings.loop_interval_seconds)

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except asyncio.TimeoutError:
                self._task.cancel()
        log.info("Agent loop stopped")


agent_loop = AgentLoop()
