"""Route-level tests for the free API surface (offline, seeded DB)."""
from __future__ import annotations

from app.database import session_scope
from app.models import Trade


def test_healthz(client):
    body = client.get("/healthz").json()
    assert body["ok"] is True
    assert body["mode"] == "PAPER"


def test_public_ping_reports_paywall_off_in_tests(client):
    body = client.get("/api/public/ping").json()
    assert body["ok"] is True
    assert body["x402_enabled"] is False
    assert body["x402_price"] is None


def test_status_shape(client):
    body = client.get("/api/status").json()
    assert body["mode"] == "PAPER"
    assert isinstance(body["kill_switch"], bool)
    assert body["llm_provider"] == "heuristic"


def test_trades_list_marks_seeded_rows_demo(client, seeded_demo_trade):
    trades = client.get("/api/trades").json()
    assert len(trades) == 1
    assert trades[0]["demo"] is True
    assert "Seeded demo trade" in trades[0]["notes"]


def test_portfolio_flags_demo_contamination(client, seeded_demo_trade):
    body = client.get("/api/portfolio").json()
    assert body["includes_demo_data"] is True


def test_portfolio_clean_without_demo_rows(client):
    with session_scope() as s:
        s.add(
            Trade(
                idem_key="real-1",
                condition_id="0xreal",
                outcome="YES",
                side="BUY",
                price=0.5,
                size_usdc=5.0,
                shares=10.0,
                model_probability=0.6,
                edge=0.1,
            )
        )
    body = client.get("/api/portfolio").json()
    assert body["includes_demo_data"] is False


def test_equity_curve_points_carry_demo_flag(client, seeded_demo_trade):
    points = client.get("/api/equity-curve").json()
    assert len(points) == 1
    assert points[0]["demo"] is True
    assert set(points[0]) == {"t", "pnl", "demo"}


def test_seed_scripts_are_idempotent(client, seeded_demo_trade):
    import seed_demo

    seed_demo.main()  # second run must not duplicate
    trades = client.get("/api/trades").json()
    assert len(trades) == 1
