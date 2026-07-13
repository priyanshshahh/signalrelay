"""Central configuration loaded from environment variables.

Keep this thin and import everywhere — it's the single contract between
operator (env) and runtime.
"""
from __future__ import annotations

from typing import List, Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # General
    log_level: str = "INFO"
    database_url: str = "sqlite:///./doa.db"
    host: str = "0.0.0.0"
    port: int = 8000

    # CORS — comma-separated list of allowed browser origins.
    # Defaults cover local dev (Vite on 5173, FastAPI-served build on 8000).
    cors_origins: str = (
        "http://localhost:5173,http://127.0.0.1:5173,"
        "http://localhost:8000,http://127.0.0.1:8000"
    )

    # Agent loop
    loop_interval_seconds: int = 30
    edge_threshold: float = 0.08
    min_signal_confidence: float = 0.55

    # Risk
    max_usdc_per_trade: float = 10.0
    max_open_positions: int = 5
    daily_drawdown_usdc: float = 25.0
    kill_switch: bool = False

    # Trading mode
    trading_mode: Literal["PAPER", "LIVE"] = "PAPER"
    wallet_private_key: str = ""
    polygon_rpc_url: str = "https://polygon-rpc.com"

    # Data
    rss_feeds: str = (
        "https://www.coindesk.com/arc/outboundfeeds/rss/,"
        "https://cointelegraph.com/rss,"
        "https://decrypt.co/feed"
    )
    cryptopanic_api_key: str = ""

    # LLM
    groq_api_key: str = ""
    groq_model: str = "llama-3.1-8b-instant"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5"

    # Market focus
    watch_markets: str = ""
    market_keywords: str = "bitcoin,ethereum,crypto,sec,etf,fed"
    max_markets: int = 5

    # x402 paywall (Base Sepolia via https://x402.org/facilitator)
    # When x402_enabled is true, x402_pay_to MUST be a real address —
    # startup fails otherwise (see x402_setup.py).
    x402_enabled: bool = False
    x402_pay_to: str = ""
    x402_price: str = "$0.01"
    x402_facilitator_url: str = "https://x402.org/facilitator"
    x402_network: str = "eip155:84532"

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def rss_list(self) -> List[str]:
        return [u.strip() for u in self.rss_feeds.split(",") if u.strip()]

    @property
    def keyword_list(self) -> List[str]:
        return [k.strip().lower() for k in self.market_keywords.split(",") if k.strip()]

    @property
    def watch_list(self) -> List[str]:
        return [m.strip() for m in self.watch_markets.split(",") if m.strip()]


settings = Settings()
