import { useEffect, useState } from "react";
import {
  api,
  type EquityPoint,
  type LogEvent,
  type MarketSnapshot,
  type NewsItem,
  type Portfolio,
  type Signal,
  type Status,
  type Trade,
} from "../api";
import { EquityChart } from "../components/EquityChart";
import { Panel, Pill, Stat } from "../components/Panel";
import { TradeDrawer } from "../components/TradeDrawer";

export default function Dashboard() {
  const [status, setStatus] = useState<Status | null>(null);
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [news, setNews] = useState<NewsItem[]>([]);
  const [markets, setMarkets] = useState<MarketSnapshot[]>([]);
  const [equity, setEquity] = useState<EquityPoint[]>([]);
  const [logs, setLogs] = useState<LogEvent[]>([]);
  const [openTrade, setOpenTrade] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function refresh() {
    try {
      const [s, p, t, sg, n, m, e, l] = await Promise.all([
        api.status(),
        api.portfolio(),
        api.trades(),
        api.signals(),
        api.news(),
        api.markets(),
        api.equityCurve(),
        api.logs(),
      ]);
      setStatus(s);
      setPortfolio(p);
      setTrades(t);
      setSignals(sg);
      setNews(n);
      setMarkets(m);
      setEquity(e);
      setLogs(l);
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, []);

  async function toggleKill() {
    if (!status) return;
    setBusy(true);
    try {
      await api.setKill(!status.kill_switch);
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  async function runOnce() {
    setBusy(true);
    try {
      await api.runOnce();
      await refresh();
    } finally {
      setBusy(false);
    }
  }

  const pnlTone = (v: number) => (v > 0 ? "positive" : v < 0 ? "negative" : "neutral");

  return (
    <main className="max-w-[1400px] mx-auto px-6 py-6 space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {status && (
            <>
              <Pill tone={status.mode === "LIVE" ? "negative" : "neutral"}>{status.mode}</Pill>
              <Pill tone={status.kill_switch ? "negative" : "positive"}>
                {status.kill_switch ? "HALTED" : "RUNNING"}
              </Pill>
              <Pill>LLM · {status.llm_provider}</Pill>
              <Pill>{status.watched_markets} markets</Pill>
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={runOnce}
            disabled={busy}
            className="text-xs border border-edge rounded px-3 py-1 hover:bg-edge disabled:opacity-50"
          >
            Run one cycle
          </button>
          <button
            onClick={toggleKill}
            disabled={busy || !status}
            className={`text-xs rounded px-3 py-1 border ${
              status?.kill_switch
                ? "border-accent/40 text-accent hover:bg-accent/10"
                : "border-danger/40 text-danger hover:bg-danger/10"
            } disabled:opacity-50`}
          >
            {status?.kill_switch ? "Resume" : "Kill switch"}
          </button>
        </div>
      </div>

      {err && (
        <div className="bg-danger/10 text-danger text-xs px-4 py-2 border border-danger/30 rounded">
          {err}
        </div>
      )}

      <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Panel title="Portfolio" className="lg:col-span-1">
          {portfolio && (
            <div className="grid grid-cols-2 gap-y-4">
              <Stat label="Equity" value={`$${portfolio.total_equity_usdc.toFixed(2)}`} />
              <Stat
                label="24h PnL"
                value={`${portfolio.daily_pnl_usdc >= 0 ? "+" : ""}$${portfolio.daily_pnl_usdc.toFixed(2)}`}
                tone={pnlTone(portfolio.daily_pnl_usdc)}
              />
              <Stat
                label="Realized"
                value={`${portfolio.realized_pnl_usdc >= 0 ? "+" : ""}$${portfolio.realized_pnl_usdc.toFixed(2)}`}
                tone={pnlTone(portfolio.realized_pnl_usdc)}
              />
              <Stat
                label="Unrealized"
                value={`${portfolio.unrealized_pnl_usdc >= 0 ? "+" : ""}$${portfolio.unrealized_pnl_usdc.toFixed(2)}`}
                tone={pnlTone(portfolio.unrealized_pnl_usdc)}
              />
              <Stat label="Open size" value={`$${portfolio.open_positions_usdc.toFixed(2)}`} />
              <Stat label="Cash" value={`$${portfolio.cash_usdc.toFixed(2)}`} />
            </div>
          )}
        </Panel>

        <Panel title="Equity curve (realized PnL)" className="lg:col-span-2">
          {equity.length > 0 ? (
            <EquityChart data={equity} />
          ) : (
            <div className="text-muted text-xs h-64 flex items-center justify-center">
              No trades yet — agent is scouting…
            </div>
          )}
        </Panel>
      </section>

      <Panel
        title="Trade log"
        right={<span className="text-xs text-muted">{trades.length} total · click for rationale</span>}
      >
        {trades.length === 0 ? (
          <div className="text-muted text-xs">
            No trades yet. The Overseer is gating on edge ≥ {status?.edge_threshold.toFixed(2)} and
            confidence ≥ {status?.min_signal_confidence.toFixed(2)}.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-muted uppercase">
                <tr>
                  <th className="text-left py-2 pr-4">Time</th>
                  <th className="text-left pr-4">Market</th>
                  <th className="text-left pr-4">Outcome</th>
                  <th className="text-right pr-4">Price</th>
                  <th className="text-right pr-4">Model p</th>
                  <th className="text-right pr-4">Edge</th>
                  <th className="text-right pr-4">Size</th>
                  <th className="text-left">Status</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((t) => (
                  <tr
                    key={t.id}
                    onClick={() => setOpenTrade(t.id)}
                    className="border-t border-edge/60 hover:bg-edge/30 cursor-pointer"
                  >
                    <td className="py-2 pr-4 text-muted">{new Date(t.created_at).toLocaleTimeString()}</td>
                    <td className="pr-4 max-w-[400px] truncate" title={t.market_question}>
                      {t.market_question || t.condition_id.slice(0, 12)}
                    </td>
                    <td className="pr-4">{t.outcome}</td>
                    <td className="pr-4 text-right">{t.price.toFixed(3)}</td>
                    <td className="pr-4 text-right">{t.model_probability.toFixed(3)}</td>
                    <td className={`pr-4 text-right ${t.edge > 0 ? "text-accent" : "text-danger"}`}>
                      {t.edge > 0 ? "+" : ""}
                      {t.edge.toFixed(3)}
                    </td>
                    <td className="pr-4 text-right">${t.size_usdc.toFixed(2)}</td>
                    <td>
                      <Pill tone={t.status === "FILLED" ? "positive" : t.status === "FAILED" ? "negative" : "warn"}>
                        {t.status}
                      </Pill>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Panel title="Signals (Quant · Bayesian)">
          {signals.length === 0 ? (
            <div className="text-muted text-xs">Waiting for news…</div>
          ) : (
            <ul className="divide-y divide-edge/60 max-h-80 overflow-y-auto">
              {signals.slice(0, 12).map((s) => (
                <li key={s.id} className="py-2 text-xs">
                  <div className="flex items-center justify-between mb-1">
                    <div className="flex gap-2">
                      <Pill
                        tone={s.sentiment === "bullish" ? "positive" : s.sentiment === "bearish" ? "negative" : "neutral"}
                      >
                        {s.sentiment}
                      </Pill>
                      <Pill>{s.topic}</Pill>
                      <Pill>conf {s.confidence.toFixed(2)}</Pill>
                    </div>
                    <span className="text-muted">
                      p {s.posterior.toFixed(2)} ← {s.prior.toFixed(2)}
                    </span>
                  </div>
                  <div className="text-muted line-clamp-2">{s.rationale}</div>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Watched markets (Polymarket)">
          {markets.length === 0 ? (
            <div className="text-muted text-xs">Loading market snapshots…</div>
          ) : (
            <ul className="divide-y divide-edge/60 max-h-80 overflow-y-auto">
              {markets.slice(0, 16).map((m) => (
                <li key={m.id} className="py-2 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <div className="truncate" title={m.question}>
                      {m.question || m.slug || m.condition_id.slice(0, 12)}
                    </div>
                    <div className="flex gap-2 flex-shrink-0">
                      <Pill>{m.outcome}</Pill>
                      <Pill tone={m.price > 0.5 ? "positive" : "neutral"}>{m.price.toFixed(3)}</Pill>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </section>

      <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Panel title="News stream (Scout)">
          {news.length === 0 ? (
            <div className="text-muted text-xs">No headlines yet.</div>
          ) : (
            <ul className="divide-y divide-edge/60 max-h-80 overflow-y-auto">
              {news.slice(0, 14).map((n) => (
                <li key={n.id} className="py-2 text-xs">
                  <a href={n.url} target="_blank" rel="noreferrer" className="text-white hover:text-accent">
                    {n.title}
                  </a>
                  <div className="text-muted mt-0.5">
                    {n.source} · {new Date(n.ingested_at).toLocaleTimeString()}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Decision log">
          {logs.length === 0 ? (
            <div className="text-muted text-xs">Idle.</div>
          ) : (
            <ul className="divide-y divide-edge/60 max-h-80 overflow-y-auto">
              {logs.slice(0, 20).map((l) => (
                <li key={l.id} className="py-2 text-xs">
                  <div className="flex items-center justify-between">
                    <div className="flex gap-2">
                      <Pill tone={l.level === "ERROR" ? "negative" : l.level === "WARN" ? "warn" : "neutral"}>
                        {l.level}
                      </Pill>
                      <Pill>{l.component}</Pill>
                    </div>
                    <span className="text-muted">{new Date(l.created_at).toLocaleTimeString()}</span>
                  </div>
                  <div className="text-muted mt-1">{l.message}</div>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </section>

      <TradeDrawer tradeId={openTrade} onClose={() => setOpenTrade(null)} />
    </main>
  );
}
