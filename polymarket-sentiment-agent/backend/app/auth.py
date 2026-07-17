"""Bearer-token auth for the unauthenticated control endpoints.

CORS does not stop curl. /api/kill-switch and /api/loop/* can flip trading
state or kick off cycles for anyone who can reach the port, so they're
gated behind a single shared-secret bearer token (ADMIN_TOKEN).

If ADMIN_TOKEN is unset, the endpoints are disabled (503) rather than left
open — no silent "auth off" fallback.
"""
from __future__ import annotations

import hmac

from fastapi import Header, HTTPException

from .config import settings


def require_admin_token(authorization: str | None = Header(default=None)) -> None:
    if not settings.admin_token:
        raise HTTPException(
            status_code=503,
            detail="Admin endpoints disabled: ADMIN_TOKEN is not set.",
        )

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization[len("Bearer ") :].strip()

    # Constant-time comparison — no early-exit timing signal on how much
    # of the token matched.
    if not token or not hmac.compare_digest(token, settings.admin_token):
        raise HTTPException(status_code=401, detail="Invalid bearer token")
