import { useEffect, useState } from "react";
import { api, fetchBaseUsdcBalance, fetchX402Challenge, type X402Terms } from "../api";
import { Panel, Pill, Stat } from "../components/Panel";

const AGENT_WALLET = "0x6e45bf955Ce5e097ec038Bd153F4c935344092Ce";
const USDC_SEPOLIA = "0x036CbD53842c5426634e7929541eC2318f3dCF7e";

type Step = {
  key: string;
  title: string;
  detail: string;
};

const STEPS: Step[] = [
  { key: "request", title: "1 · Consumer requests rationale", detail: "GET /api/trade/1/rationale — no payment header" },
  { key: "challenge", title: "2 · Provider returns 402", detail: "x402 challenge: $0.01 USDC on Base Sepolia" },
  { key: "sign", title: "3 · Privy TEE signs", detail: "Agent's P-256 session key authorizes — private key never leaves Privy" },
  { key: "settle", title: "4 · Facilitator settles on Base", detail: "USDC transferred; gas sponsored by facilitator" },
  { key: "deliver", title: "5 · Provider returns 200 OK", detail: "Bayesian rationale delivered to the consumer agent" },
];

function usdc(amount: string): string {
  const n = Number(amount);
  if (!Number.isFinite(n)) return amount;
  return `$${(n / 1_000_000).toFixed(2)}`;
}

export default function X402Lab() {
  const [running, setRunning] = useState(false);
  const [active, setActive] = useState(-1);
  const [terms, setTerms] = useState<X402Terms | null>(null);
  const [status402, setStatus402] = useState<number | null>(null);
  const [revealed, setRevealed] = useState<Awaited<ReturnType<typeof api.demoRationale>> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [balance, setBalance] = useState<number | null>(null);

  async function refreshBalance() {
    setBalance(await fetchBaseUsdcBalance(AGENT_WALLET));
  }

  useEffect(() => {
    refreshBalance();
  }, []);

  async function run() {
    setRunning(true);
    setErr(null);
    setRevealed(null);
    setTerms(null);
    setStatus402(null);
    try {
      setActive(0);
      await sleep(700);

      // Step 2: hit the REAL paywalled endpoint -> real 402 + decoded terms.
      setActive(1);
      const chal = await fetchX402Challenge(1);
      setStatus402(chal.status);
      setTerms(chal.terms);
      await sleep(900);

      setActive(2);
      await sleep(900);
      setActive(3);
      await sleep(900);

      // Step 5: show the FREE teaser. The full payload is only served to a
      // paying agent on the x402-gated route — there is no free bypass.
      setActive(4);
      const data = await api.demoRationale(1);
      setRevealed(data);
      refreshBalance();
      await sleep(300);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setRunning(false);
    }
  }

  return (
    <main className="max-w-[1400px] mx-auto px-6 py-6 space-y-6">
      <div className="rounded-xl border border-edge bg-gradient-to-br from-panel to-ink p-6">
        <div className="flex items-center gap-2 mb-2">
          <Pill tone="positive">LIVE</Pill>
          <span className="text-[10px] text-muted uppercase tracking-wider">x402 · Privy · Base Sepolia</span>
        </div>
        <h1 className="text-2xl font-semibold">Agent-to-Agent Commerce, Live</h1>
        <p className="text-muted text-xs mt-2 max-w-2xl">
          Watch a downstream trading agent <span className="text-white">discover</span>,{" "}
          <span className="text-white">pay for</span>, and <span className="text-white">consume</span> the
          Polymarket Bayesian edge — settling real USDC on Base, with its private key custodied in a Privy TEE.
        </p>
        <button
          onClick={run}
          disabled={running}
          className="mt-4 text-sm rounded-lg px-4 py-2 border border-accent/40 text-accent bg-accent/10 hover:bg-accent/20 disabled:opacity-50"
        >
          {running ? "Running…" : "▶ Run the x402 payment"}
        </button>
        {err && <div className="text-danger text-xs mt-3">{err}</div>}
      </div>

      <section className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Panel title="Consumer Agent (Privy)" className="lg:col-span-1">
          <div className="space-y-3 text-xs">
            <div>
              <div className="text-[10px] uppercase tracking-wider text-muted">Embedded wallet</div>
              <div className="font-mono text-accent break-all mt-1">{AGENT_WALLET}</div>
            </div>
            <div className="flex gap-2 flex-wrap">
              <Pill tone="positive">Authorized via Privy CLI</Pill>
              <Pill>key in TEE</Pill>
              <Pill>Base Sepolia</Pill>
            </div>
            <div className="flex items-center justify-between rounded-lg border border-edge bg-ink/50 px-3 py-2">
              <div>
                <div className="text-[10px] uppercase tracking-wider text-muted">Live USDC balance · Base Sepolia</div>
                <div className="text-lg text-accent mt-0.5">
                  {balance == null ? "—" : `$${balance.toFixed(2)}`}
                </div>
              </div>
              <button
                onClick={refreshBalance}
                className="text-[10px] border border-edge rounded px-2 py-1 text-muted hover:text-white hover:bg-edge"
              >
                ↻ refresh
              </button>
            </div>
            <p className="text-muted leading-relaxed">
              One-time human approval bound this agent's P-256 session key to the wallet. After that it pays
              autonomously — no private key on the agent, no API keys, no subscription.
            </p>
          </div>
        </Panel>

        <Panel title="Payment flow" className="lg:col-span-2">
          <ol className="space-y-2">
            {STEPS.map((s, i) => {
              const state = active < 0 ? "idle" : i < active ? "done" : i === active ? "active" : "idle";
              return (
                <li
                  key={s.key}
                  className={`flex items-start gap-3 rounded-lg border px-3 py-2 transition ${
                    state === "active"
                      ? "border-accent/50 bg-accent/10"
                      : state === "done"
                      ? "border-edge bg-edge/30"
                      : "border-edge"
                  }`}
                >
                  <div
                    className={`mt-0.5 w-4 h-4 rounded-full flex-shrink-0 ${
                      state === "done" ? "bg-accent" : state === "active" ? "bg-accent animate-pulse" : "bg-edge"
                    }`}
                  />
                  <div>
                    <div className={state === "idle" ? "text-muted" : "text-white"}>{s.title}</div>
                    <div className="text-muted text-[11px]">{s.detail}</div>
                  </div>
                </li>
              );
            })}
          </ol>
        </Panel>
      </section>

      <section className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Panel title="402 challenge (decoded from live response)">
          {status402 == null ? (
            <div className="text-muted text-xs">Run the demo to capture the live 402 challenge.</div>
          ) : (
            <div className="space-y-3">
              <div className="flex items-center gap-2">
                <Pill tone={status402 === 402 ? "warn" : "neutral"}>HTTP {status402}</Pill>
                <span className="text-xs text-muted">GET /api/trade/1/rationale</span>
              </div>
              {terms && (
                <div className="grid grid-cols-2 gap-y-3 gap-x-4">
                  <Stat label="Price" value={usdc(terms.amount)} tone="positive" />
                  <Stat label="Network" value={terms.network} />
                  <div className="col-span-2">
                    <div className="text-[10px] uppercase tracking-wider text-muted">Asset (USDC)</div>
                    <div className="font-mono text-[11px] break-all mt-1">{terms.asset || USDC_SEPOLIA}</div>
                  </div>
                  <div className="col-span-2">
                    <div className="text-[10px] uppercase tracking-wider text-muted">Pay to</div>
                    <div className="font-mono text-[11px] break-all mt-1">{terms.payTo}</div>
                  </div>
                </div>
              )}
            </div>
          )}
        </Panel>

        <Panel title="Free teaser (full alpha requires x402 payment)">
          {!revealed ? (
            <div className="text-muted text-xs">
              The free teaser appears here once the flow completes. The full
              rationale is only returned to a paying agent.
            </div>
          ) : (
            <div className="space-y-3 text-xs">
              <div className="flex gap-2 flex-wrap">
                <Pill tone="warn">DEMO</Pill>
                <Pill>teaser · truncated</Pill>
              </div>
              <div className="text-white">{revealed.trade?.market_question}</div>
              <div className="flex gap-2 flex-wrap">
                <Pill tone={revealed.signal_preview?.sentiment === "bullish" ? "positive" : "neutral"}>
                  {revealed.signal_preview?.sentiment ?? "—"}
                </Pill>
                <Pill>{revealed.signal_preview?.topic ?? "—"}</Pill>
                <Pill>
                  {revealed.trade?.side} {revealed.trade?.outcome}
                </Pill>
              </div>
              <div className="text-muted">{revealed.signal_preview?.rationale_preview}</div>
              <div className="rounded-lg border border-edge bg-ink/50 px-3 py-2 text-muted leading-relaxed">
                {revealed.note ??
                  "The posterior, edge, source article and market snapshot are only served by the x402-paywalled endpoint."}
              </div>
            </div>
          )}
        </Panel>
      </section>

      <Panel title="Reproduce it from a terminal">
        <pre className="text-[11px] text-muted overflow-x-auto whitespace-pre-wrap">{`# 1. Authorize an agent wallet (one-time human approval)
npx @privy-io/agent-wallet-cli login

# 2. Fund it with Base Sepolia USDC -> https://faucet.circle.com

# 3. Pay for the signal over x402 (HTTPS endpoint via tunnel)
npx @privy-io/agent-wallet-cli fetch-x402 \\
  --header "bypass-tunnel-reminder: 1" \\
  https://<tunnel>.loca.lt/api/trade/1/rationale
# 402 -> Privy TEE signs -> facilitator settles on Base -> 200 OK + rationale`}</pre>
      </Panel>
    </main>
  );
}

function sleep(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}
