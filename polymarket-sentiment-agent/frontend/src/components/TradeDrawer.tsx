import { useEffect, useState } from "react";
import { api, type DemoTeaser, type Rationale } from "../api";
import { Pill } from "./Panel";

export function TradeDrawer({ tradeId, onClose }: { tradeId: number | null; onClose: () => void }) {
  const [data, setData] = useState<Rationale | null>(null);
  const [teaser, setTeaser] = useState<DemoTeaser | null>(null);

  useEffect(() => {
    if (tradeId == null) {
      setData(null);
      setTeaser(null);
      return;
    }
    // The full rationale is x402-paywalled in production; fall back to the
    // free truncated teaser when the gated route returns 402.
    api
      .rationale(tradeId)
      .then((d) => {
        setData(d);
        setTeaser(null);
      })
      .catch(() => {
        setData(null);
        api.demoRationale(tradeId).then(setTeaser).catch(() => setTeaser(null));
      });
  }, [tradeId]);

  if (tradeId == null) return null;

  return (
    <div
      className="fixed inset-0 bg-black/60 z-40 flex justify-end"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl h-full bg-panel border-l border-edge overflow-y-auto p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="text-xs text-muted uppercase">Trade rationale</div>
            <div className="text-lg">#{tradeId}</div>
          </div>
          <button
            onClick={onClose}
            className="text-muted hover:text-white text-sm border border-edge rounded px-3 py-1"
          >
            Close
          </button>
        </div>

        {!data && !teaser && <div className="text-muted text-sm">Loading…</div>}

        {!data && teaser && (
          <div className="space-y-4">
            <div className="flex gap-2">
              <Pill tone="warn">DEMO teaser</Pill>
              <Pill>x402 paywalled</Pill>
            </div>
            <section className="bg-edge/40 rounded-lg p-3">
              <div className="text-xs text-muted uppercase mb-1">Preview</div>
              <div className="text-sm">{teaser.trade?.market_question}</div>
              <div className="text-xs text-muted mt-2 flex flex-wrap gap-2">
                {teaser.signal_preview?.sentiment && <Pill>{teaser.signal_preview.sentiment}</Pill>}
                {teaser.signal_preview?.topic && <Pill>{teaser.signal_preview.topic}</Pill>}
              </div>
              <div className="text-xs text-muted mt-2">{teaser.signal_preview?.rationale_preview}</div>
              <div className="text-xs text-muted mt-3">
                {teaser.note ?? "Full rationale requires an x402 payment on the gated endpoint."}
              </div>
            </section>
          </div>
        )}

        {data && (
          <div className="space-y-4">
            {data.demo && (
              <div className="flex gap-2">
                <Pill tone="warn">DEMO trade — illustrative data, not real PnL</Pill>
              </div>
            )}
            <section className="bg-edge/40 rounded-lg p-3">
              <div className="text-xs text-muted uppercase mb-1">Decision</div>
              <div className="text-sm">{data.trade.market_question}</div>
              <div className="text-xs text-muted mt-2 flex flex-wrap gap-2">
                <Pill>{data.trade.outcome}</Pill>
                <Pill tone={data.trade.edge > 0 ? "positive" : "negative"}>
                  edge {data.trade.edge.toFixed(3)}
                </Pill>
                <Pill>model p {data.trade.model_probability.toFixed(2)}</Pill>
                <Pill>price {data.trade.price.toFixed(2)}</Pill>
                <Pill>{data.trade.size_usdc.toFixed(2)} USDC</Pill>
              </div>
            </section>

            {data.signal && (
              <section className="bg-edge/40 rounded-lg p-3">
                <div className="text-xs text-muted uppercase mb-1">Signal (Quant)</div>
                <div className="text-sm flex flex-wrap gap-2 mb-2">
                  <Pill
                    tone={
                      data.signal.sentiment === "bullish"
                        ? "positive"
                        : data.signal.sentiment === "bearish"
                        ? "negative"
                        : "neutral"
                    }
                  >
                    {data.signal.sentiment}
                  </Pill>
                  <Pill>{data.signal.topic}</Pill>
                  <Pill>conf {data.signal.confidence.toFixed(2)}</Pill>
                  <Pill>via {data.signal.llm_provider}</Pill>
                </div>
                <div className="text-xs text-muted">{data.signal.rationale}</div>
                <div className="text-[11px] text-muted mt-2 grid grid-cols-3 gap-2">
                  <div>prior {data.signal.prior.toFixed(2)}</div>
                  <div>LR {data.signal.likelihood_ratio.toFixed(2)}</div>
                  <div>posterior {data.signal.posterior.toFixed(2)}</div>
                </div>
              </section>
            )}

            {data.news && (
              <section className="bg-edge/40 rounded-lg p-3">
                <div className="text-xs text-muted uppercase mb-1">News (Scout)</div>
                <a
                  href={data.news.url}
                  target="_blank"
                  rel="noreferrer"
                  className="text-sm text-accent hover:underline"
                >
                  {data.news.title}
                </a>
                <div className="text-xs text-muted mt-1">{data.news.source}</div>
                <div className="text-xs text-muted mt-2 whitespace-pre-wrap line-clamp-6">
                  {data.news.summary}
                </div>
              </section>
            )}

            {data.snapshot && (
              <section className="bg-edge/40 rounded-lg p-3">
                <div className="text-xs text-muted uppercase mb-1">Market snapshot (Oracle)</div>
                <div className="text-xs text-muted grid grid-cols-2 gap-2">
                  <div>cond: {data.snapshot.condition_id.slice(0, 10)}…</div>
                  <div>price: {data.snapshot.price.toFixed(3)}</div>
                  <div>bid: {data.snapshot.best_bid.toFixed(3)}</div>
                  <div>ask: {data.snapshot.best_ask.toFixed(3)}</div>
                  <div>liq: ${data.snapshot.liquidity.toFixed(0)}</div>
                  <div>24h vol: ${data.snapshot.volume_24h.toFixed(0)}</div>
                </div>
              </section>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
