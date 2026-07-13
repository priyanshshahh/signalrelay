"""SQLAlchemy models. These ARE the audit trail.

Design notes:
- `NewsItem` is the raw input artifact.
- `Signal` is the LLM-extracted structured belief.
- `MarketSnapshot` captures market state at decision time.
- `Trade` joins everything: news -> signal -> snapshot -> action.
  This is what lets you post-mortem any trade with one query.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Boolean,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class NewsItem(Base):
    __tablename__ = "news_items"

    id = Column(Integer, primary_key=True)
    source = Column(String(64), nullable=False)
    url = Column(String(1024), unique=True, nullable=False)
    title = Column(String(1024), nullable=False)
    summary = Column(Text, default="")
    published_at = Column(DateTime, default=_utcnow)
    ingested_at = Column(DateTime, default=_utcnow, index=True)
    # True for seeded/illustrative rows (not produced by the live pipeline).
    demo = Column(Boolean, default=False, nullable=False)

    signals = relationship("Signal", back_populates="news_item")


class Signal(Base):
    """Structured output of the Quant module (LLM + Bayesian)."""
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True)
    news_item_id = Column(Integer, ForeignKey("news_items.id"), nullable=False)
    created_at = Column(DateTime, default=_utcnow, index=True)

    # LLM-extracted structured fields (do NOT let LLM output the probability).
    sentiment = Column(String(16))           # bullish | bearish | neutral
    confidence = Column(Float, default=0.0)  # 0-1
    topic = Column(String(64))               # e.g. SEC, FED, BTC
    entities = Column(Text, default="[]")    # JSON array of strings
    rationale = Column(Text, default="")     # LLM short explanation
    llm_provider = Column(String(32), default="heuristic")

    # Deterministic Bayesian outputs (computed in Python, not LLM).
    prior = Column(Float, default=0.5)
    posterior = Column(Float, default=0.5)
    likelihood_ratio = Column(Float, default=1.0)

    # True for seeded/illustrative rows.
    demo = Column(Boolean, default=False, nullable=False)

    news_item = relationship("NewsItem", back_populates="signals")


class MarketSnapshot(Base):
    """Polymarket state at a point in time, per outcome."""
    __tablename__ = "market_snapshots"

    id = Column(Integer, primary_key=True)
    captured_at = Column(DateTime, default=_utcnow, index=True)
    condition_id = Column(String(128), index=True, nullable=False)
    slug = Column(String(256), default="")
    question = Column(String(1024), default="")
    outcome = Column(String(64), nullable=False)        # YES / NO
    token_id = Column(String(128), default="")
    price = Column(Float, default=0.5)                  # implied probability
    best_bid = Column(Float, default=0.0)
    best_ask = Column(Float, default=1.0)
    liquidity = Column(Float, default=0.0)
    volume_24h = Column(Float, default=0.0)
    # True for seeded/illustrative rows.
    demo = Column(Boolean, default=False, nullable=False)


class Trade(Base):
    """A decision + execution record. Idempotent via `idem_key`."""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=_utcnow, index=True)
    idem_key = Column(String(128), unique=True, nullable=False)

    mode = Column(String(8), default="PAPER")            # PAPER | LIVE
    status = Column(String(16), default="FILLED")        # PENDING | FILLED | FAILED | CANCELED

    condition_id = Column(String(128), index=True, nullable=False)
    market_question = Column(String(1024), default="")
    outcome = Column(String(64), nullable=False)
    side = Column(String(4), nullable=False)             # BUY | SELL

    price = Column(Float, nullable=False)                # entry price (0-1)
    size_usdc = Column(Float, nullable=False)            # USDC spent
    shares = Column(Float, nullable=False)               # shares acquired
    fees_usdc = Column(Float, default=0.0)

    model_probability = Column(Float, nullable=False)    # what we thought
    edge = Column(Float, nullable=False)                 # model_prob - price

    signal_id = Column(Integer, ForeignKey("signals.id"))
    snapshot_id = Column(Integer, ForeignKey("market_snapshots.id"))

    # Realized at settlement / close.
    closed_at = Column(DateTime, nullable=True)
    exit_price = Column(Float, nullable=True)
    pnl_usdc = Column(Float, default=0.0)

    tx_hash = Column(String(128), default="")            # filled only in LIVE mode
    notes = Column(Text, default="")
    # True for seeded/illustrative rows — demo PnL is NOT real performance.
    demo = Column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("ix_trades_status_created", "status", "created_at"),
    )


class AgentState(Base):
    """Single-row key/value store for runtime flags & counters."""
    __tablename__ = "agent_state"

    key = Column(String(64), primary_key=True)
    value = Column(Text, default="")
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class LogEvent(Base):
    """Structured operational log distinct from Python logger output."""
    __tablename__ = "log_events"

    id = Column(Integer, primary_key=True)
    created_at = Column(DateTime, default=_utcnow, index=True)
    level = Column(String(16), default="INFO")
    component = Column(String(32), default="agent")
    message = Column(Text, default="")
    data = Column(Text, default="{}")  # JSON
