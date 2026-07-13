"""CORS must be an explicit allowlist, never a wildcard."""
from __future__ import annotations

from app.config import Settings, settings


def test_default_origins_are_localhost_dev_only():
    fresh = Settings(_env_file=None)
    assert "http://localhost:5173" in fresh.cors_origin_list
    assert "*" not in fresh.cors_origin_list


def test_cors_origins_env_parsing_strips_and_drops_empties():
    s = Settings(_env_file=None, cors_origins=" https://a.example , https://b.example ,")
    assert s.cors_origin_list == ["https://a.example", "https://b.example"]


def test_allowed_origin_gets_cors_headers(client):
    r = client.get("/healthz", headers={"Origin": "http://localhost:5173"})
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_disallowed_origin_gets_no_cors_headers(client):
    r = client.get("/healthz", headers={"Origin": "https://evil.example"})
    assert r.status_code == 200
    assert "access-control-allow-origin" not in r.headers


def test_preflight_rejected_for_unknown_origin(client):
    r = client.options(
        "/api/status",
        headers={
            "Origin": "https://evil.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert r.headers.get("access-control-allow-origin") != "https://evil.example"


def test_app_settings_do_not_use_wildcard():
    assert "*" not in settings.cors_origin_list
