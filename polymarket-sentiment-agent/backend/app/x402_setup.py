"""x402 payment middleware for paywalled API routes.

Uses the free x402.org facilitator on Base Sepolia (eip155:84532).
Activates when X402_ENABLED=true; in that case X402_PAY_TO must be a
real (non-zero) address or startup fails hard. Silently running a
paywall that routes revenue to the zero address is not a failure mode
we want to discover in production.
"""
from __future__ import annotations

import logging
import re

from fastapi import FastAPI

from .config import settings

log = logging.getLogger("x402")

_ZERO_ADDRESS = "0x" + "0" * 40
_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


def validate_pay_to(pay_to: str) -> str:
    """Return the address if usable; raise RuntimeError otherwise."""
    if not pay_to:
        raise RuntimeError(
            "X402_ENABLED=true but X402_PAY_TO is not set. "
            "Set X402_PAY_TO to your Base Sepolia receive address, "
            "or set X402_ENABLED=false to run without the paywall."
        )
    if not _ADDRESS_RE.match(pay_to):
        raise RuntimeError(f"X402_PAY_TO is not a valid 0x address: {pay_to!r}")
    if pay_to.lower() == _ZERO_ADDRESS:
        raise RuntimeError("X402_PAY_TO is the zero address; refusing to start.")
    return pay_to


def setup_x402(app: FastAPI) -> None:
    if not settings.x402_enabled:
        log.info("x402 paywall disabled (set X402_ENABLED=true to enable)")
        return

    pay_to = validate_pay_to(settings.x402_pay_to)

    from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
    from x402.http.middleware.fastapi import PaymentMiddlewareASGI
    from x402.http.types import RouteConfig
    from x402.mechanisms.evm.exact import ExactEvmServerScheme
    from x402.server import x402ResourceServer

    facilitator = HTTPFacilitatorClient(
        FacilitatorConfig(url=settings.x402_facilitator_url)
    )
    server = x402ResourceServer(facilitator)
    server.register(settings.x402_network, ExactEvmServerScheme())

    routes = {
        "GET /api/trade/:trade_id/rationale": RouteConfig(
            accepts=[
                PaymentOption(
                    scheme="exact",
                    pay_to=pay_to,
                    price=settings.x402_price,
                    network=settings.x402_network,
                ),
            ],
            mime_type="application/json",
            description=(
                "Trade rationale: news article, LLM signal, and market snapshot "
                "that produced this trade."
            ),
        ),
    }

    app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)
    log.info(
        "x402 paywall enabled: GET /api/trade/:trade_id/rationale -> %s @ %s (%s)",
        pay_to,
        settings.x402_price,
        settings.x402_network,
    )
