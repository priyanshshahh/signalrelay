"""
CHF DuckDB Analytics Engine
Thin DuckDB helper over the Parquet data lake: ad-hoc SQL plus a canonical
market-data loader. The per-artifact loaders that used to live here globbed
pre-refactor per-symbol filenames (`*_ohlcv.parquet`, `*_onchain.parquet`, ...)
that the unified agents no longer emit, so they returned empty and were removed.
Read canonical single files directly (or via `query`) instead.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from configs.config import get_config
from configs.logging_config import get_logger

logger = get_logger("pipelines.duckdb_engine")


class DuckDBEngine:
    """DuckDB-based analytics helper for the CHF Parquet data lake."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.cfg = config or get_config()
        self._project_root = Path(self.cfg["_project_root"])
        self._conn = None

    def _get_conn(self):
        """Lazily initialize an in-memory DuckDB connection."""
        if self._conn is None:
            try:
                import duckdb
            except ImportError:
                raise ImportError("duckdb not installed. Run: pip install duckdb")
            self._conn = duckdb.connect(database=":memory:")
            logger.info("DuckDB in-memory connection established")
        return self._conn

    def _resolve(self, key: str) -> Path:
        """Resolve a data path from config relative to the project root."""
        raw = self.cfg["paths"].get(key, key)
        p = Path(raw)
        if not p.is_absolute():
            p = self._project_root / p
        return p

    def load_market_data(self, symbols: Optional[List[str]] = None) -> pd.DataFrame:
        """Load canonical OHLCV (`market_ohlcv.parquet`) into a DataFrame."""
        market_path = self._resolve("raw") / "market" / "market_ohlcv.parquet"
        if not market_path.exists():
            return pd.DataFrame()
        conn = self._get_conn()
        df = conn.execute(
            f"SELECT * FROM read_parquet('{market_path}') ORDER BY symbol, date_ts"
        ).df()
        if symbols:
            df = df[df["symbol"].isin([s.upper() for s in symbols])]
        return df.reset_index(drop=True)

    def query(self, sql: str) -> pd.DataFrame:
        """Execute arbitrary SQL against the DuckDB connection."""
        return self._get_conn().execute(sql).df()

    def query_dataframe(self, df: "pd.DataFrame", sql: str) -> "pd.DataFrame":
        """Execute SQL against an in-memory DataFrame registered as `df`."""
        import duckdb
        conn = duckdb.connect(":memory:")
        conn.register("df", df)
        return conn.execute(sql).df()
