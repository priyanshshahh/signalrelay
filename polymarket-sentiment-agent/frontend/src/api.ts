export type Status = {
  mode: "PAPER" | "LIVE";
  kill_switch: boolean;
  loop_interval_seconds: number;
  edge_threshold: number;
  min_signal_confidence: number;
  max_usdc_per_trade: number;
  daily_drawdown_usdc: number;
  llm_provider: string;
  watched_markets: number;
  last_loop_at: string | null;
};

export type NewsItem = {
  id: number;
  source: string;
  url: string;
  title: string;
  summary: string;
  published_at: string | null;
  ingested_at: string;
};

export type Signal = {
  id: number;
  news_item_id: number;
  created_at: string;
  sentiment: string;
  confidence: number;
  topic: string;
  entities: string;
  rationale: string;
  llm_provider: string;
  prior: number;
  posterior: number;
  likelihood_ratio: number;
};

export type MarketSnapshot = {
  id: number;
  captured_at: string;
  condition_id: string;
  slug: string;
  question: string;
  outcome: string;
  token_id: string;
  price: number;
  best_bid: number;
  best_ask: number;
  liquidity: number;
  volume_24h: number;
};

export type Trade = {
  id: number;
  created_at: string;
  idem_key: string;
  mode: string;
  status: string;
  condition_id: string;
  market_question: string;
  outcome: string;
  side: string;
  price: number;
  size_usdc: number;
  shares: number;
  fees_usdc: number;
  model_probability: number;
  edge: number;
  signal_id: number | null;
  snapshot_id: number | null;
  closed_at: string | null;
  exit_price: number | null;
  pnl_usdc: number;
  tx_hash: string;
  notes: string;
};

export type Portfolio = {
  cash_usdc: number;
  open_positions_usdc: number;
  realized_pnl_usdc: number;
  unrealized_pnl_usdc: number;
  total_equity_usdc: number;
  daily_pnl_usdc: number;
  open_positions: Trade[];
};

export type EquityPoint = { t: string; pnl: number };

export type LogEvent = {
  id: number;
  created_at: string;
  level: string;
  component: string;
  message: string;
  data: Record<string, unknown>;
};

async function j<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json() as Promise<T>;
}

export const api = {
  status: () => j<Status>("/api/status"),
  news: () => j<NewsItem[]>("/api/news?limit=30"),
  signals: () => j<Signal[]>("/api/signals?limit=30"),
  markets: () => j<MarketSnapshot[]>("/api/markets"),
  trades: () => j<Trade[]>("/api/trades?limit=50"),
  portfolio: () => j<Portfolio>("/api/portfolio"),
  equityCurve: () => j<EquityPoint[]>("/api/equity-curve"),
  logs: () => j<LogEvent[]>("/api/logs?limit=100"),
  rationale: (id: number) =>
    j<{ trade: Trade; signal: Signal | null; news: NewsItem | null; snapshot: MarketSnapshot | null }>(
      `/api/trade/${id}/rationale`
    ),
  setKill: (enabled: boolean) =>
    j<{ kill_switch: boolean }>("/api/kill-switch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }),
  runOnce: () => j<{ ok: boolean }>("/api/loop/run-once", { method: "POST" }),
  demoRationale: (id: number) =>
    j<{ trade: Trade; signal: Signal | null; news: NewsItem | null; snapshot: MarketSnapshot | null }>(
      `/api/demo/rationale/${id}`
    ),
};

export type X402Terms = {
  network: string;
  asset: string;
  amount: string;
  payTo: string;
  resource?: string;
};

/** Hit the REAL paywalled endpoint, expect a 402, and decode the x402 terms. */
export async function fetchX402Challenge(id: number): Promise<{ status: number; terms: X402Terms | null; raw: string | null }> {
  const r = await fetch(`/api/trade/${id}/rationale`);
  const header = r.headers.get("payment-required") || r.headers.get("www-authenticate");
  let terms: X402Terms | null = null;
  if (header) {
    try {
      const decoded = JSON.parse(atob(header));
      const a = decoded?.accepts?.[0] ?? {};
      terms = {
        network: a.network ?? "eip155:84532",
        asset: a.asset ?? "",
        amount: a.amount ?? "",
        payTo: a.payTo ?? "",
        resource: decoded?.resource?.url,
      };
    } catch {
      terms = null;
    }
  }
  return { status: r.status, terms, raw: header };
}
