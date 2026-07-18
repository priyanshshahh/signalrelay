"""Track-record: prediction logging, resolution join, and honest scoring."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.database import session_scope
from app.models import MarketResolution, PredictionRecord, Signal, Trade
from app.modules import track_record

_RealAsyncClient = httpx.AsyncClient


def _seed_predictions(n_correct: int, n_wrong: int, *, prob: float = 0.8, resolve: bool = True):
    """Create n predictions on distinct markets; mark them resolved YES/NO."""
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with session_scope() as s:
        i = 0
        for correct in [True] * n_correct + [False] * n_wrong:
            cid = f"0xcid{i}"
            s.add(PredictionRecord(
                created_at=base + timedelta(hours=i),
                condition_id=cid, outcome="Yes", market_question=f"Q{i}?",
                model_probability=prob, market_probability=0.5, edge=prob - 0.5,
                llm_provider="groq", model_version="groq:llama",
            ))
            if resolve:
                # If our predicted outcome (Yes) should be correct, resolve Yes.
                s.add(MarketResolution(condition_id=cid,
                                       resolved_outcome="Yes" if correct else "No"))
            i += 1


# ---------- parse_resolution ------------------------------------------------

def test_parse_resolution_picks_settled_winner():
    market = {"closed": True, "outcomes": json.dumps(["Yes", "No"]),
              "outcomePrices": json.dumps(["1", "0"])}
    assert track_record.parse_resolution(market) == "Yes"
    market2 = {"closed": True, "outcomes": json.dumps(["Yes", "No"]),
               "outcomePrices": json.dumps(["0", "1"])}
    assert track_record.parse_resolution(market2) == "No"


def test_parse_resolution_ignores_open_or_ambiguous():
    assert track_record.parse_resolution({"closed": False}) is None
    ambiguous = {"closed": True, "outcomes": json.dumps(["Yes", "No"]),
                 "outcomePrices": json.dumps(["0.5", "0.5"])}
    assert track_record.parse_resolution(ambiguous) is None


# ---------- scoring ---------------------------------------------------------

def test_insufficient_data_below_threshold():
    _seed_predictions(3, 1)  # only 4 resolved
    out = track_record.compute_track_record(min_resolved=10)
    assert out["status"] == "insufficient_data"
    assert "metrics" not in out
    assert out["resolved_predictions"] == 4
    assert out["start_date"] is not None


def test_metrics_computed_above_threshold():
    # 12 correct @0.8, 0 wrong -> high accuracy, low Brier.
    _seed_predictions(12, 0, prob=0.8)
    out = track_record.compute_track_record(min_resolved=10)
    assert out["status"] == "ok"
    m = out["metrics"]
    assert m["accuracy"] == pytest.approx(1.0)
    # Brier for p=0.8, actual=1 is (0.8-1)^2 = 0.04.
    assert m["brier_score"] == pytest.approx(0.04, abs=1e-6)
    assert m["log_loss"] > 0
    assert len(out["calibration"]) == 5
    assert out["resolved_predictions"] == 12


def test_pending_predictions_counted_but_not_scored():
    _seed_predictions(11, 0, resolve=True)
    _seed_predictions(0, 0)  # no-op
    # Add an unresolved prediction.
    with session_scope() as s:
        s.add(PredictionRecord(condition_id="0xopen", outcome="Yes",
                               model_probability=0.7, market_probability=0.5))
    out = track_record.compute_track_record(min_resolved=10)
    assert out["resolved_predictions"] == 11
    assert out["pending_predictions"] >= 1


# ---------- resolution join (mocked Gamma) ----------------------------------

@pytest.mark.anyio
async def test_resolve_open_predictions_writes_resolution(monkeypatch):
    with session_scope() as s:
        s.add(PredictionRecord(condition_id="0xwinme", outcome="Yes",
                               model_probability=0.9, market_probability=0.5))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/markets":
            return httpx.Response(200, json=[{
                "conditionId": "0xwinme", "closed": True,
                "outcomes": json.dumps(["Yes", "No"]),
                "outcomePrices": json.dumps(["1", "0"]),
                "umaResolutionStatus": "resolved",
            }])
        return httpx.Response(404)

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _RealAsyncClient(transport=httpx.MockTransport(handler)))
    n = await track_record.resolve_open_predictions()
    assert n == 1
    with session_scope() as s:
        res = s.get(MarketResolution, "0xwinme")
        assert res is not None and res.resolved_outcome == "Yes"


# ---------- backfill --------------------------------------------------------

def test_backfill_from_trades_is_reconstructible_and_idempotent():
    with session_scope() as s:
        s.add(Trade(idem_key="t1", condition_id="0xbt", market_question="Q?",
                    outcome="Yes", side="BUY", price=0.4, size_usdc=1.0, shares=2.5,
                    model_probability=0.7, edge=0.3, signal_id=None))
    assert track_record.backfill_from_trades() == 1
    # Idempotent: a second run inserts nothing.
    assert track_record.backfill_from_trades() == 0
    with session_scope() as s:
        rec = s.query(PredictionRecord).filter(PredictionRecord.condition_id == "0xbt").one()
        assert rec.backfilled is True
        assert rec.model_version == "reconstructed_from_trade"


# ---------- API + provenance ------------------------------------------------

def test_track_record_endpoint_reports_insufficient(client):
    _seed_predictions(2, 1)
    body = client.get("/api/track-record").json()
    assert body["status"] == "insufficient_data"
    assert isinstance(body["log"], list)
    assert "methodology" in body


def test_resolve_endpoint_requires_admin(client):
    # ADMIN_TOKEN unset in tests -> control endpoints disabled (503).
    r = client.post("/api/track-record/resolve")
    assert r.status_code == 503


def test_paid_rationale_carries_provenance_and_receipt(client, seeded_demo_trade):
    body = client.get(f"/api/trade/{seeded_demo_trade}/rationale").json()
    assert "provenance" in body
    assert body["provenance"]["estimator"].startswith("bayesian_update")
    assert body["provenance"]["track_record_endpoint"] == "/api/track-record"
    assert "x402_receipt" in body
    assert body["x402_receipt"]["settlement_tx_hash_header"] == "X-PAYMENT-RESPONSE"


def test_teaser_does_not_leak_provenance(client, seeded_demo_trade):
    body = client.get(f"/api/demo/rationale/{seeded_demo_trade}").json()
    assert body["demo"] is True
    assert "provenance" not in body
    assert "x402_receipt" not in body
    assert "snapshot" not in body
