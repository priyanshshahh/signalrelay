"""Oracle (Polymarket client) parsing tests with mocked httpx transports."""
from __future__ import annotations

import json

import httpx
import pytest

from app.modules import market


# Keep a handle on the real class: tests monkeypatch httpx.AsyncClient.
_RealAsyncClient = httpx.AsyncClient


def _mock_client(handler):
    return _RealAsyncClient(transport=httpx.MockTransport(handler))


GAMMA_MARKET = {
    "conditionId": "0xabc123",
    "slug": "will-btc-hit-100k",
    "question": "Will Bitcoin hit $100k?",
    "endDateIso": "2026-12-31",
    "volume24hr": 12345.0,
    "liquidityNum": 999.0,
    "outcomes": json.dumps(["Yes", "No"]),
    "clobTokenIds": json.dumps(["111", "222"]),
}


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path == "/markets":
        return httpx.Response(200, json=[GAMMA_MARKET])
    if path == "/midpoint":
        return httpx.Response(200, json={"mid": "0.63"})
    if path == "/price":
        side = request.url.params.get("side")
        return httpx.Response(200, json={"price": "0.62" if side == "BUY" else "0.64"})
    return httpx.Response(404)


# ---------- _safe_loads ------------------------------------------------------

def test_safe_loads_accepts_json_string_list_and_none():
    assert market._safe_loads('["Yes", "No"]') == ["Yes", "No"]
    assert market._safe_loads(["Yes"]) == ["Yes"]
    assert market._safe_loads(None) == []
    assert market._safe_loads("not json") == []


# ---------- fetch_markets ----------------------------------------------------

@pytest.mark.anyio
async def test_fetch_markets_parses_gamma_and_clob(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _mock_client(_handler))
    results = await market.fetch_markets()
    assert len(results) == 1
    m = results[0]
    assert m.condition_id == "0xabc123"
    assert m.question == "Will Bitcoin hit $100k?"
    assert m.volume_24h == 12345.0
    assert [o.name for o in m.outcomes] == ["Yes", "No"]
    yes = m.outcomes[0]
    assert yes.price == pytest.approx(0.63)
    assert yes.best_bid == pytest.approx(0.62)
    assert yes.best_ask == pytest.approx(0.64)


@pytest.mark.anyio
async def test_fetch_markets_skips_mismatched_token_ids(monkeypatch):
    bad = dict(GAMMA_MARKET, clobTokenIds=json.dumps(["only-one"]))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/markets":
            return httpx.Response(200, json=[bad])
        return httpx.Response(200, json={})

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _mock_client(handler))
    assert await market.fetch_markets() == []


@pytest.mark.anyio
async def test_fetch_markets_survives_gamma_failure(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _mock_client(handler))
    assert await market.fetch_markets() == []


@pytest.mark.anyio
async def test_book_price_defaults_when_clob_down():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    async with _mock_client(handler) as client:
        out = await market._book_price(client, "111")
    assert out == {"price": 0.5, "best_bid": 0.0, "best_ask": 1.0}


@pytest.mark.anyio
async def test_discover_markets_filters_by_keywords(monkeypatch):
    relevant = dict(GAMMA_MARKET)
    irrelevant = dict(
        GAMMA_MARKET,
        conditionId="0xother",
        slug="who-wins-the-oscars",
        question="Who wins Best Picture?",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/markets":
            return httpx.Response(200, json=[relevant, irrelevant])
        return httpx.Response(200, json={})

    monkeypatch.setattr(market.settings, "watch_markets", "")
    monkeypatch.setattr(market.settings, "market_keywords", "bitcoin")
    async with _mock_client(handler) as client:
        raw = await market._discover_markets(client)
    assert [m["conditionId"] for m in raw] == ["0xabc123"]


def test_persist_snapshot_writes_rows_per_outcome():
    m = market.Market(
        condition_id="0xabc123",
        slug="s",
        question="q",
        end_date=None,
        volume_24h=1.0,
        liquidity=2.0,
        outcomes=[
            market.Outcome(name="Yes", token_id="111", price=0.6, best_bid=0.59, best_ask=0.61),
            market.Outcome(name="No", token_id="222", price=0.4, best_bid=0.39, best_ask=0.41),
        ],
    )
    saved = market.persist_snapshot([m])
    assert len(saved) == 2
    assert {r.outcome for r in saved} == {"Yes", "No"}
    assert all(r.demo is False or r.demo == 0 for r in saved)
