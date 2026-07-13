"""The Quant — turns text into a calibrated probability.

CRITICAL DESIGN PRINCIPLE: The LLM is used ONLY as an NLP parser. It
extracts structured variables (sentiment, confidence, topic, entities).
The probability itself is computed by a deterministic Bayesian update
in plain Python. LLMs hallucinate confidence; math doesn't.

Providers tried in order: Groq -> OpenAI -> Anthropic -> heuristic.
"""
from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, asdict
from typing import List, Optional, Tuple

import httpx

from ..config import settings
from ..database import session_scope
from ..models import NewsItem, Signal

log = logging.getLogger("quant")


# ---------------------------------------------------------------------------
# LLM-extracted structure (NOT a probability — see module docstring).
# ---------------------------------------------------------------------------

@dataclass
class Extraction:
    sentiment: str            # "bullish" | "bearish" | "neutral"
    confidence: float         # 0..1, model's confidence in its OWN parse
    topic: str                # short label, e.g. "SEC", "FED", "BTC"
    entities: List[str]
    rationale: str
    provider: str             # which backend produced this


SYSTEM_PROMPT = (
    "You are a strict JSON extractor for a quantitative trading agent. "
    "Given a financial news headline + summary, extract a structured judgment. "
    "DO NOT predict prices. DO NOT recommend trades. Only label sentiment.\n"
    "Output a single JSON object with keys: sentiment (one of: bullish, bearish, neutral), "
    "confidence (float 0-1, your confidence in this LABEL only), "
    "topic (short uppercase tag like SEC, FED, ETF, BTC, ETH, MACRO), "
    "entities (array of relevant tickers/orgs), "
    "rationale (one short sentence).\n"
    "Return ONLY the JSON, no prose."
)


def _build_user_msg(title: str, summary: str) -> str:
    return f"HEADLINE: {title}\n\nSUMMARY:\n{summary[:1500]}"


def _safe_json(text: str) -> Optional[dict]:
    # tolerate code fences / leading text
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text).rstrip("`").strip()
    # find first { ... last }
    a, b = text.find("{"), text.rfind("}")
    if a == -1 or b == -1:
        return None
    try:
        return json.loads(text[a : b + 1])
    except Exception:
        return None


def _normalize(d: dict, provider: str) -> Extraction:
    sent = str(d.get("sentiment", "neutral")).lower().strip()
    if sent not in {"bullish", "bearish", "neutral"}:
        sent = "neutral"
    try:
        conf = float(d.get("confidence", 0.5))
    except Exception:
        conf = 0.5
    conf = max(0.0, min(1.0, conf))
    ents = d.get("entities") or []
    if isinstance(ents, str):
        ents = [ents]
    return Extraction(
        sentiment=sent,
        confidence=conf,
        topic=str(d.get("topic", "GEN"))[:32].upper() or "GEN",
        entities=[str(x)[:48] for x in ents][:8],
        rationale=str(d.get("rationale", ""))[:512],
        provider=provider,
    )


# ---------------------------------------------------------------------------
# LLM providers
# ---------------------------------------------------------------------------

async def _call_groq(client: httpx.AsyncClient, title: str, summary: str) -> Optional[Extraction]:
    if not settings.groq_api_key:
        return None
    try:
        r = await client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            json={
                "model": settings.groq_model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": _build_user_msg(title, summary)},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.1,
                "max_tokens": 300,
            },
            timeout=20.0,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        data = _safe_json(content)
        return _normalize(data, "groq") if data else None
    except Exception as e:
        log.warning("Groq call failed: %s", e)
        return None


async def _call_openai(client: httpx.AsyncClient, title: str, summary: str) -> Optional[Extraction]:
    if not settings.openai_api_key:
        return None
    try:
        r = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.openai_api_key}"},
            json={
                "model": settings.openai_model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": _build_user_msg(title, summary)},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.1,
            },
            timeout=25.0,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        data = _safe_json(content)
        return _normalize(data, "openai") if data else None
    except Exception as e:
        log.warning("OpenAI call failed: %s", e)
        return None


async def _call_anthropic(client: httpx.AsyncClient, title: str, summary: str) -> Optional[Extraction]:
    if not settings.anthropic_api_key:
        return None
    try:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": settings.anthropic_api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": settings.anthropic_model,
                "max_tokens": 400,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": _build_user_msg(title, summary)}],
            },
            timeout=25.0,
        )
        r.raise_for_status()
        content = r.json()["content"][0]["text"]
        data = _safe_json(content)
        return _normalize(data, "anthropic") if data else None
    except Exception as e:
        log.warning("Anthropic call failed: %s", e)
        return None


# ---------------------------------------------------------------------------
# Heuristic fallback — works with zero API keys. Useful for demos.
# ---------------------------------------------------------------------------

_BULL = {
    "approve", "approved", "adopt", "adoption", "surge", "rally", "jump", "soar",
    "bullish", "record high", "all-time high", "ath", "buy", "accumulate", "gain",
    "win", "wins", "passes", "green light", "etf", "inflow", "inflows", "upgrade",
    "partnership", "breakout", "milestone", "launch",
}
_BEAR = {
    "reject", "rejected", "ban", "banned", "crash", "plunge", "fall", "drop",
    "bearish", "lawsuit", "sue", "sued", "charged", "fraud", "hack", "exploit",
    "outflow", "outflows", "downgrade", "delist", "delisted", "halts", "halted",
    "selloff", "sell-off", "investigation", "subpoena",
}
_TOPIC_MAP = [
    ("SEC", ("sec", "securities and exchange")),
    ("FED", ("fed", "fomc", "powell", "rate cut", "rate hike")),
    ("ETF", ("etf", "spot etf")),
    ("BTC", ("bitcoin", "btc")),
    ("ETH", ("ethereum", "eth")),
    ("MACRO", ("inflation", "cpi", "ppi", "gdp", "jobs")),
]


def _heuristic(title: str, summary: str) -> Extraction:
    blob = f"{title} {summary}".lower()
    bull = sum(1 for w in _BULL if w in blob)
    bear = sum(1 for w in _BEAR if w in blob)
    if bull == bear:
        sent, conf = "neutral", 0.5
    elif bull > bear:
        sent = "bullish"
        conf = min(0.85, 0.5 + 0.1 * (bull - bear))
    else:
        sent = "bearish"
        conf = min(0.85, 0.5 + 0.1 * (bear - bull))
    topic = "GEN"
    for tag, keys in _TOPIC_MAP:
        if any(k in blob for k in keys):
            topic = tag
            break
    return Extraction(
        sentiment=sent,
        confidence=round(conf, 2),
        topic=topic,
        entities=[],
        rationale=f"Heuristic: {bull} bullish vs {bear} bearish keywords.",
        provider="heuristic",
    )


async def extract(title: str, summary: str) -> Extraction:
    async with httpx.AsyncClient() as client:
        for fn in (_call_groq, _call_openai, _call_anthropic):
            res = await fn(client, title, summary)
            if res is not None:
                return res
    return _heuristic(title, summary)


# ---------------------------------------------------------------------------
# Bayesian update — pure math, no LLM involvement.
# ---------------------------------------------------------------------------

def bayesian_update(prior: float, sentiment: str, confidence: float) -> Tuple[float, float]:
    """Update a binary 'YES' probability given a labeled news signal.

    Maps (sentiment, confidence) -> a likelihood ratio LR. We then do a
    Bayes update in log-odds space for numerical stability.

    LR interpretation:
      - bullish + high confidence -> LR > 1 (boosts YES)
      - bearish + high confidence -> LR < 1 (cuts YES)
      - neutral -> LR ~ 1

    The mapping is intentionally conservative: even max-confidence
    bullish caps LR at ~5. We are sentiment traders, not oracles.
    """
    prior = min(max(prior, 1e-4), 1 - 1e-4)
    confidence = min(max(confidence, 0.0), 1.0)

    if sentiment == "bullish":
        lr = 1.0 + 4.0 * confidence       # 1..5
    elif sentiment == "bearish":
        lr = 1.0 / (1.0 + 4.0 * confidence)  # 1..0.2
    else:
        lr = 1.0

    # log-odds Bayes update
    log_odds = math.log(prior / (1 - prior)) + math.log(lr)
    posterior = 1 / (1 + math.exp(-log_odds))
    # Never emit a hard 0/1 — downstream edge math assumes open interval,
    # and round() alone can push an extreme prior to exactly 1.0.
    posterior = min(max(posterior, 1e-4), 1 - 1e-4)
    return round(posterior, 4), round(lr, 4)


# ---------------------------------------------------------------------------
# Pipeline entry point.
# ---------------------------------------------------------------------------

async def analyze_news_item(news: NewsItem, prior: float = 0.5) -> Signal:
    extr = await extract(news.title, news.summary or "")
    posterior, lr = bayesian_update(prior, extr.sentiment, extr.confidence)
    sig = Signal(
        news_item_id=news.id,
        sentiment=extr.sentiment,
        confidence=extr.confidence,
        topic=extr.topic,
        entities=json.dumps(extr.entities),
        rationale=extr.rationale,
        llm_provider=extr.provider,
        prior=prior,
        posterior=posterior,
        likelihood_ratio=lr,
    )
    with session_scope() as s:
        s.add(sig)
        s.flush()
    return sig
