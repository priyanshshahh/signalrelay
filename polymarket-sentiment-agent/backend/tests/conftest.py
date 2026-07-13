"""Test bootstrap: force a throwaway SQLite DB and safe settings BEFORE any
app module is imported (the engine is created at import time).

All tests run fully offline — external HTTP is either mocked or never
reached.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_TMPDIR = tempfile.mkdtemp(prefix="polyagent-tests-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMPDIR}/test.db"
os.environ["X402_ENABLED"] = "false"
os.environ["X402_PAY_TO"] = ""
os.environ["TRADING_MODE"] = "PAPER"
os.environ["CORS_ORIGINS"] = "http://localhost:5173,http://testclient.example"

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import pytest  # noqa: E402

from app.database import init_db, engine, Base, session_scope  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_db():
    """Recreate all tables before every test for isolation."""
    init_db()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.main import app

    # No context manager: skips lifespan, so the agent loop never starts.
    return TestClient(app)


@pytest.fixture()
def seeded_demo_trade():
    """Run the real seed script and return the seeded trade id."""
    import seed_demo

    seed_demo.main()
    from app.models import Trade

    with session_scope() as s:
        t = s.query(Trade).filter(Trade.idem_key == seed_demo.IDEM).one()
        return t.id
