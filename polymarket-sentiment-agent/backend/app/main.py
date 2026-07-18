"""FastAPI entry point. Spins up the DB and the agent loop."""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api.routes import router as api_router
from .config import settings
from .database import init_db
from .orchestrator import agent_loop
from .x402_setup import setup_x402

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    log.info("DB initialized; trading_mode=%s", settings.trading_mode)
    agent_loop.start()
    try:
        yield
    finally:
        await agent_loop.stop()


app = FastAPI(
    title="Poly Agent — Polymarket Sentiment Trader",
    version="0.2.0",
    description="Modular MVP: Scout -> Quant -> Oracle -> Trader, with Overseer gating.",
    lifespan=lifespan,
)

# Explicit origin allowlist — set CORS_ORIGINS (comma-separated) in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-PAYMENT-RESPONSE", "PAYMENT-RESPONSE", "PAYMENT-REQUIRED"],
)

# Paywall selected routes via x402 (Base Sepolia). Requires X402_PAY_TO.
setup_x402(app)

app.include_router(api_router, prefix="/api")


@app.get("/healthz")
def healthz():
    return {"ok": True, "mode": settings.trading_mode}


# ---------------------------------------------------------------------------
# Static frontend (single-deploy mode).
# Looks for a built React app at FRONTEND_DIST or ../frontend/dist.
# In dev you'll be running Vite separately; this block becomes a no-op then.
# ---------------------------------------------------------------------------
_dist_env = os.environ.get("FRONTEND_DIST")
_default_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
_dist = Path(_dist_env) if _dist_env else _default_dist

if _dist.is_dir():
    log.info("Serving frontend from %s", _dist)
    assets = _dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/")
    def root_index():
        return FileResponse(_dist / "index.html")

    @app.get("/{path:path}")
    def spa_fallback(path: str):
        # any non-API path falls back to index.html for the SPA router
        candidate = _dist / path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_dist / "index.html")
else:
    log.info("No frontend build at %s; running API only", _dist)
