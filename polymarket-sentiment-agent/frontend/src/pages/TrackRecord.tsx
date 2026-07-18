import { useEffect, useState } from "react";
import {
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Scatter,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api, type TrackRecord as TR } from "../api";
import { Panel, Pill, Stat } from "../components/Panel";

function fmt(n: number | null | undefined, d = 3): string {
  return n === null || n === undefined ? "—" : n.toFixed(d);
}

function CalibrationChart({ tr }: { tr: TR }) {
  const bins = (tr.calibration ?? []).filter((b) => b.count > 0);
  const points = bins.map((b) => ({
    predicted: b.mean_predicted,
    observed: b.observed_frequency,
    count: b.count,
  }));
  // Perfect-calibration diagonal.
  const diag = [
    { predicted: 0, ideal: 0 },
    { predicted: 1, ideal: 1 },
  ];
  return (
    <div className="w-full h-72">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart margin={{ left: 4, right: 12, top: 8, bottom: 16 }}>
          <CartesianGrid stroke="#1c222d" strokeDasharray="3 3" />
          <XAxis
            type="number"
            dataKey="predicted"
            domain={[0, 1]}
            stroke="#8693a8"
            tick={{ fontSize: 10 }}
            label={{ value: "Predicted probability", position: "bottom", fill: "#8693a8", fontSize: 11 }}
          />
          <YAxis
            type="number"
            dataKey="observed"
            domain={[0, 1]}
            stroke="#8693a8"
            tick={{ fontSize: 10 }}
            width={44}
            label={{ value: "Observed", angle: -90, position: "insideLeft", fill: "#8693a8", fontSize: 11 }}
          />
          <Tooltip
            contentStyle={{ background: "#11151c", border: "1px solid #1c222d", fontSize: 12 }}
            formatter={(v: number) => v?.toFixed?.(3) ?? v}
          />
          <Line
            data={diag}
            dataKey="ideal"
            stroke="#8693a8"
            strokeDasharray="4 4"
            dot={false}
            strokeWidth={1}
            isAnimationActive={false}
            name="perfect calibration"
          />
          <Scatter data={points} dataKey="observed" fill="#7cf6c4" name="observed" isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

export default function TrackRecord() {
  const [tr, setTr] = useState<TR | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api
      .trackRecord()
      .then((d) => {
        setTr(d);
        setErr(null);
      })
      .catch((e) => setErr((e as Error).message));
  }, []);

  const insufficient = tr?.status === "insufficient_data";

  return (
    <main className="max-w-[1400px] mx-auto px-6 py-6 space-y-4">
      <div className="flex items-end justify-between flex-wrap gap-2">
        <div>
          <h1 className="text-lg font-semibold">Track Record</h1>
          <p className="text-xs text-muted mt-1 max-w-2xl">
            Every probability the agent emits on a Polymarket outcome is logged and, once the
            market resolves, scored against the real outcome. This is an out-of-sample record —
            no claimed win-rates, no backtested numbers dressed up as live.
          </p>
        </div>
        {tr && (
          <div className="flex items-center gap-2">
            <Pill tone={insufficient ? "warn" : "positive"}>
              {insufficient ? "insufficient data" : "live"}
            </Pill>
            <span className="text-[10px] text-muted">
              since {tr.start_date ? new Date(tr.start_date).toLocaleDateString() : "—"}
            </span>
          </div>
        )}
      </div>

      {err && (
        <Panel>
          <div className="text-danger text-sm" role="alert">
            Failed to load track record: {err}
          </div>
        </Panel>
      )}

      {tr && (
        <>
          <Panel>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              <Stat label="Predictions logged" value={tr.total_predictions} />
              <Stat label="Resolved" value={tr.resolved_predictions} tone="positive" />
              <Stat label="Pending resolution" value={tr.pending_predictions} tone="warn" />
              <Stat
                label="Start date"
                value={tr.start_date ? new Date(tr.start_date).toLocaleDateString() : "—"}
              />
            </div>
          </Panel>

          {insufficient ? (
            <Panel title="Metrics">
              <div className="text-sm text-muted">
                Only <span className="text-white">{tr.resolved_predictions}</span> markets have
                resolved so far — below the{" "}
                <span className="text-white">{tr.min_resolved_for_metrics}</span>-row threshold
                for reporting Brier / log-loss / calibration. We show{" "}
                <span className="text-warn">insufficient data</span> rather than a curve fit to a
                handful of points. The raw log below is still populated as predictions accrue.
              </div>
            </Panel>
          ) : (
            tr.metrics && (
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <Panel title="Scores (resolved predictions)">
                  <div className="grid grid-cols-2 gap-4">
                    <Stat label="Accuracy" value={fmt(tr.metrics.accuracy, 3)} tone="positive" />
                    <Stat
                      label="Brier score"
                      value={fmt(tr.metrics.brier_score, 4)}
                      sub={`market baseline ${fmt(tr.metrics.market_baseline_brier, 4)}`}
                      tone={
                        tr.metrics.brier_score < tr.metrics.market_baseline_brier
                          ? "positive"
                          : "warn"
                      }
                    />
                    <Stat label="Log loss" value={fmt(tr.metrics.log_loss, 4)} />
                    <Stat label="Base rate (YES)" value={fmt(tr.metrics.base_rate, 3)} />
                  </div>
                  <p className="text-[10px] text-muted mt-3">
                    Brier and log-loss are lower-is-better. The market baseline is the same score
                    computed on the market-implied price at emit time — beating it is the bar.
                  </p>
                </Panel>
                <Panel title="Calibration">
                  <CalibrationChart tr={tr} />
                </Panel>
              </div>
            )
          )}

          <Panel title={`Prediction log (${tr.log.length})`}>
            {tr.log.length === 0 ? (
              <div className="text-sm text-muted">
                No predictions logged yet. The record starts the first time the agent evaluates a
                market.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-muted uppercase tracking-wider text-[10px]">
                    <tr className="text-left">
                      <th className="py-2 pr-3">When</th>
                      <th className="py-2 pr-3">Market</th>
                      <th className="py-2 pr-3">Outcome</th>
                      <th className="py-2 pr-3 text-right">Model p</th>
                      <th className="py-2 pr-3 text-right">Market p</th>
                      <th className="py-2 pr-3">Resolved</th>
                      <th className="py-2 pr-3">Result</th>
                      <th className="py-2 pr-3">Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tr.log
                      .slice()
                      .reverse()
                      .map((r) => (
                        <tr key={r.id} className="border-t border-edge">
                          <td className="py-1.5 pr-3 text-muted whitespace-nowrap">
                            {r.created_at ? new Date(r.created_at).toLocaleDateString() : "—"}
                          </td>
                          <td className="py-1.5 pr-3 max-w-[280px] truncate" title={r.market_question}>
                            {r.market_question || r.condition_id}
                          </td>
                          <td className="py-1.5 pr-3">{r.outcome}</td>
                          <td className="py-1.5 pr-3 text-right tabular-nums">
                            {r.model_probability.toFixed(3)}
                          </td>
                          <td className="py-1.5 pr-3 text-right tabular-nums text-muted">
                            {r.market_probability.toFixed(3)}
                          </td>
                          <td className="py-1.5 pr-3">{r.resolved_outcome}</td>
                          <td className="py-1.5 pr-3">
                            <Pill tone={r.actual ? "positive" : "negative"}>
                              {r.actual ? "correct" : "wrong"}
                            </Pill>
                          </td>
                          <td className="py-1.5 pr-3 text-muted">
                            {r.backfilled ? "backfill" : r.llm_provider || "—"}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          <Panel title="Methodology & limitations">
            <p className="text-xs text-muted leading-relaxed">{tr.methodology}</p>
            <ul className="text-xs text-muted mt-3 space-y-1 list-disc pl-5">
              <li>
                <span className="text-white">Out-of-sample only.</span> Rows are scored strictly
                against outcomes that resolved <em>after</em> the prediction timestamp.
              </li>
              <li>
                <span className="text-white">Small sample.</span> This is a young, live record;
                treat early metrics as directional, not definitive.
              </li>
              <li>
                <span className="text-white">Known biases.</span> Favorite-longshot bias and
                LLM-sentiment lookahead risk (news can post-date the market move) both apply.
              </li>
              <li>
                <span className="text-white">Ground truth.</span> Outcomes come from Polymarket's
                public Gamma API (closed markets); the settlement is on-chain via UMA.
              </li>
            </ul>
          </Panel>
        </>
      )}

      {!tr && !err && (
        <div className="text-muted text-sm" role="status" aria-live="polite">
          Loading…
        </div>
      )}
    </main>
  );
}
