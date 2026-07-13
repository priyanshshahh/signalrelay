"""Pydantic schemas for API responses and inter-module data."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class NewsItemOut(BaseModel):
    id: int
    source: str
    url: str
    title: str
    summary: str
    published_at: Optional[datetime]
    ingested_at: datetime
    demo: bool = False

    model_config = {"from_attributes": True}


class SignalOut(BaseModel):
    id: int
    news_item_id: int
    created_at: datetime
    sentiment: Optional[str]
    confidence: float
    topic: Optional[str]
    entities: str
    rationale: str
    llm_provider: str
    prior: float
    posterior: float
    likelihood_ratio: float
    demo: bool = False

    model_config = {"from_attributes": True}


class MarketSnapshotOut(BaseModel):
    id: int
    captured_at: datetime
    condition_id: str
    slug: str
    question: str
    outcome: str
    token_id: str
    price: float
    best_bid: float
    best_ask: float
    liquidity: float
    volume_24h: float
    demo: bool = False

    model_config = {"from_attributes": True}


class TradeOut(BaseModel):
    id: int
    created_at: datetime
    idem_key: str
    mode: str
    status: str
    condition_id: str
    market_question: str
    outcome: str
    side: str
    price: float
    size_usdc: float
    shares: float
    fees_usdc: float
    model_probability: float
    edge: float
    signal_id: Optional[int]
    snapshot_id: Optional[int]
    closed_at: Optional[datetime]
    exit_price: Optional[float]
    pnl_usdc: float
    tx_hash: str
    notes: str
    demo: bool = False

    model_config = {"from_attributes": True, "protected_namespaces": ()}


class PortfolioOut(BaseModel):
    cash_usdc: float
    open_positions_usdc: float
    realized_pnl_usdc: float
    unrealized_pnl_usdc: float
    total_equity_usdc: float
    daily_pnl_usdc: float
    open_positions: List[TradeOut]
    # True when any counted trade is seeded demo data — treat PnL as illustrative.
    includes_demo_data: bool = False


class StatusOut(BaseModel):
    mode: str
    kill_switch: bool
    loop_interval_seconds: int
    edge_threshold: float
    min_signal_confidence: float
    max_usdc_per_trade: float
    daily_drawdown_usdc: float
    llm_provider: str
    watched_markets: int
    last_loop_at: Optional[datetime] = None


class KillSwitchIn(BaseModel):
    enabled: bool = Field(..., description="Halt all trading if true")
