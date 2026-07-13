"""Parsing/normalization tests for the Quant module (no LLM, no network)."""
from __future__ import annotations

from app.modules.intelligence import _heuristic, _normalize, _safe_json


# ---------- _safe_json ----------------------------------------------------

def test_safe_json_plain_object():
    assert _safe_json('{"a": 1}') == {"a": 1}


def test_safe_json_code_fence():
    assert _safe_json('```json\n{"sentiment": "bullish"}\n```') == {"sentiment": "bullish"}


def test_safe_json_with_prose_around():
    assert _safe_json('Sure! Here you go: {"x": 2} hope that helps') == {"x": 2}


def test_safe_json_garbage_returns_none():
    assert _safe_json("not json at all") is None
    assert _safe_json("{broken: json") is None


# ---------- _normalize ----------------------------------------------------

def test_normalize_bad_sentiment_falls_back_to_neutral():
    e = _normalize({"sentiment": "TO THE MOON", "confidence": 0.9}, "test")
    assert e.sentiment == "neutral"


def test_normalize_clamps_confidence():
    assert _normalize({"confidence": 7}, "t").confidence == 1.0
    assert _normalize({"confidence": -3}, "t").confidence == 0.0
    assert _normalize({"confidence": "oops"}, "t").confidence == 0.5


def test_normalize_entities_string_becomes_list_and_is_truncated():
    e = _normalize({"entities": "BTC"}, "t")
    assert e.entities == ["BTC"]
    e2 = _normalize({"entities": [str(i) for i in range(20)]}, "t")
    assert len(e2.entities) == 8


def test_normalize_provider_passthrough():
    assert _normalize({}, "groq").provider == "groq"


# ---------- _heuristic -----------------------------------------------------

def test_heuristic_bullish_keywords():
    e = _heuristic("Bitcoin ETF approved, price surges to record high", "")
    assert e.sentiment == "bullish"
    assert e.confidence > 0.5
    assert e.provider == "heuristic"


def test_heuristic_bearish_keywords():
    e = _heuristic("SEC lawsuit: exchange sued for fraud, tokens delisted", "")
    assert e.sentiment == "bearish"
    assert e.confidence > 0.5


def test_heuristic_neutral_when_balanced_or_empty():
    e = _heuristic("Quarterly report published", "")
    assert e.sentiment == "neutral"
    assert e.confidence == 0.5


def test_heuristic_topic_mapping():
    assert _heuristic("Powell hints at FOMC rate cut", "").topic == "FED"
    assert _heuristic("Ethereum upgrade ships", "").topic == "ETH"
    assert _heuristic("nothing to see here", "").topic == "GEN"
