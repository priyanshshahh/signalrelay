"""Seed a short history of ILLUSTRATIVE closed trades so the equity curve
has something to render in the demo. All rows are flagged demo=True and the
PnL numbers are fabricated for display — they are NOT real trading results.
Idempotent via fixed idem_keys.

Keeps the primary x402 demo trade (seed_demo.py, id=1) intact.
"""
from __future__ import annotations

import datetime as dt

from app.database import session_scope
from app.models import NewsItem, Signal, MarketSnapshot, Trade
from app.modules import intelligence

# (idem, topic, question, sentiment, conf, prior, exit_price, size, hours_ago)
ROWS = [
    ("hist-btc-etf-001", "ETF", "Will a spot BTC ETF see net inflows this week?", "bullish", 0.74, 0.58, 0.69, 6.0, 5),
    ("hist-sec-001", "SEC", "Will the SEC drop its case against a major exchange in 2026?", "bullish", 0.66, 0.41, 0.52, 5.0, 4),
    ("hist-eth-001", "ETH", "Will ETH close above $4k this month?", "bearish", 0.61, 0.55, 0.47, 5.0, 3),
    ("hist-fed-002", "FED", "Will the Fed hold rates at the next meeting?", "bullish", 0.70, 0.60, 0.66, 7.0, 2),
    ("hist-btc-002", "BTC", "Will BTC make a new all-time high in Q3?", "bullish", 0.80, 0.63, 0.74, 8.0, 1),
]


def main() -> None:
    now = dt.datetime.utcnow()
    created = 0
    with session_scope() as s:
        for idem, topic, q, sentiment, conf, prior, exit_price, size, hrs in ROWS:
            if s.query(Trade).filter(Trade.idem_key == idem).first():
                continue
            ts = now - dt.timedelta(hours=hrs)
            news = NewsItem(
                source="coindesk",
                url=f"https://www.coindesk.com/markets/demo/{idem}",
                title=q,
                summary=f"Signal context for {topic}.",
                published_at=ts,
                ingested_at=ts,
                demo=True,
            )
            s.add(news)
            s.flush()
            posterior, lr = intelligence.bayesian_update(prior, sentiment, conf)
            sig = Signal(
                news_item_id=news.id,
                created_at=ts,
                sentiment=sentiment,
                confidence=conf,
                topic=topic,
                entities=f'["{topic}"]',
                rationale=f"{sentiment.title()} {topic} signal; posterior {posterior:.2f} vs prior {prior:.2f}.",
                llm_provider="heuristic",
                prior=prior,
                posterior=posterior,
                likelihood_ratio=lr,
                demo=True,
            )
            s.add(sig)
            s.flush()
            snap = MarketSnapshot(
                captured_at=ts,
                condition_id=f"0xdemo{idem}",
                slug=idem,
                question=q,
                outcome="YES",
                token_id="0",
                price=prior,
                best_bid=prior - 0.01,
                best_ask=prior + 0.01,
                liquidity=90000.0,
                volume_24h=300000.0,
                demo=True,
            )
            s.add(snap)
            s.flush()
            side = "BUY" if sentiment == "bullish" else "SELL"
            shares = round(size / prior, 4)
            pnl = round(shares * (exit_price - prior) * (1 if side == "BUY" else -1), 2)
            s.add(
                Trade(
                    idem_key=idem,
                    mode="PAPER",
                    status="FILLED",
                    condition_id=snap.condition_id,
                    market_question=q,
                    outcome="YES",
                    side=side,
                    price=prior,
                    size_usdc=size,
                    shares=shares,
                    fees_usdc=0.0,
                    model_probability=posterior,
                    edge=round(posterior - prior, 4),
                    signal_id=sig.id,
                    snapshot_id=snap.id,
                    created_at=ts,
                    closed_at=ts + dt.timedelta(hours=1),
                    exit_price=exit_price,
                    pnl_usdc=pnl,
                    notes="Seeded history for equity curve (illustrative, not real PnL).",
                    demo=True,
                )
            )
            created += 1
        s.flush()
    print(f"Seeded {created} historical trades.")


if __name__ == "__main__":
    main()
