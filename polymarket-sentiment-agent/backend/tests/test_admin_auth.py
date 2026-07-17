"""Bearer-token auth on the control endpoints.

/api/kill-switch and /api/loop/* can flip trading state or kick off a
cycle for anyone who can reach the port — CORS doesn't stop curl. These
must require ADMIN_TOKEN, and must fail closed (503) when it's unset
rather than run open.
"""
from __future__ import annotations

import pytest

from app.config import settings
from app.orchestrator import agent_loop

CONTROL_ENDPOINTS = [
    ("POST", "/api/kill-switch", {"enabled": True}),
    ("POST", "/api/loop/run-once", None),
    ("POST", "/api/loop/start", None),
    ("POST", "/api/loop/stop", None),
]


def _call(client, method, path, body):
    return client.post(path, json=body) if body is not None else client.post(path)


@pytest.fixture(autouse=True)
def _no_admin_token_by_default(monkeypatch):
    """Every test starts from the unset (disabled) state unless it opts in."""
    monkeypatch.setattr(settings, "admin_token", "")


@pytest.mark.parametrize("method,path,body", CONTROL_ENDPOINTS)
def test_disabled_when_admin_token_unset(client, method, path, body):
    r = _call(client, method, path, body)
    assert r.status_code == 503


@pytest.mark.parametrize("method,path,body", CONTROL_ENDPOINTS)
def test_no_token_rejected(client, monkeypatch, method, path, body):
    monkeypatch.setattr(settings, "admin_token", "s3cret")
    r = _call(client, method, path, body)
    assert r.status_code == 401


@pytest.mark.parametrize("method,path,body", CONTROL_ENDPOINTS)
def test_wrong_token_rejected(client, monkeypatch, method, path, body):
    monkeypatch.setattr(settings, "admin_token", "s3cret")
    r = client.post(
        path,
        json=body,
        headers={"Authorization": "Bearer not-the-token"},
    )
    assert r.status_code == 401


def test_correct_token_flips_kill_switch(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "s3cret")
    r = client.post(
        "/api/kill-switch",
        json={"enabled": True},
        headers={"Authorization": "Bearer s3cret"},
    )
    assert r.status_code == 200
    assert r.json() == {"kill_switch": True}


def test_correct_token_allows_loop_start_and_stop(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "s3cret")
    headers = {"Authorization": "Bearer s3cret"}

    started = {"called": False}
    stopped = {"called": False}

    def fake_start():
        started["called"] = True

    async def fake_stop():
        stopped["called"] = True

    monkeypatch.setattr(agent_loop, "start", fake_start)
    monkeypatch.setattr(agent_loop, "stop", fake_stop)

    r = client.post("/api/loop/start", headers=headers)
    assert r.status_code == 200
    assert r.json() == {"running": True}
    assert started["called"] is True

    r = client.post("/api/loop/stop", headers=headers)
    assert r.status_code == 200
    assert r.json() == {"running": False}
    assert stopped["called"] is True


def test_correct_token_allows_run_once(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "s3cret")
    headers = {"Authorization": "Bearer s3cret"}

    called = {"count": 0}

    async def fake_run_once():
        called["count"] += 1

    monkeypatch.setattr("app.api.routes._run_once", fake_run_once)

    r = client.post("/api/loop/run-once", headers=headers)
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert called["count"] == 1


def test_malformed_authorization_header_rejected(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", "s3cret")
    r = client.post(
        "/api/kill-switch",
        json={"enabled": True},
        headers={"Authorization": "s3cret"},  # missing "Bearer " prefix
    )
    assert r.status_code == 401
