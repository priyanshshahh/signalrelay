import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

type Slide = {
  kicker: string;
  title: string;
  body: React.ReactNode;
};

const slides: Slide[] = [
  {
    kicker: "SignalRelay",
    title: "Machines hiring machines for alpha",
    body: (
      <ul className="space-y-2 text-muted">
        <li>An autonomous Polymarket sentiment oracle that <span className="text-white">earns</span> USDC.</li>
        <li>A Privy-authorized consumer agent that <span className="text-white">spends</span> USDC to hire it.</li>
        <li>Settled over <span className="text-accent">x402 on Base</span> — no humans in the payment loop.</li>
      </ul>
    ),
  },
  {
    kicker: "Problem",
    title: "Autonomous agents can't pay for data",
    body: (
      <ul className="space-y-2 text-muted">
        <li>Today: API keys, monthly subscriptions, a human with a credit card.</li>
        <li>That breaks the moment the agent is truly autonomous.</li>
        <li>Trading agents need probabilistic <span className="text-white">edge</span>, priced per signal — not per month.</li>
      </ul>
    ),
  },
  {
    kicker: "Solution",
    title: "A 402-gated Bayesian sentiment oracle",
    body: (
      <ul className="space-y-2 text-muted">
        <li><span className="text-white">Scout</span> — live Polymarket markets + crypto news.</li>
        <li><span className="text-white">Quant</span> — LLM extracts sentiment; Python computes a Bayesian posterior.</li>
        <li><span className="text-white">Edge</span> = posterior − market-implied prior. That's the product.</li>
        <li>Paywalled with <span className="text-accent">x402</span>: $0.01 USDC per signal.</li>
      </ul>
    ),
  },
  {
    kicker: "Privy + Base",
    title: "The required pieces, used well",
    body: (
      <ul className="space-y-2 text-muted">
        <li><span className="text-white">Privy Agent Authorization</span> — one human approval, then autonomous payments.</li>
        <li>Private key never leaves Privy's <span className="text-white">TEE</span>; agent holds only a P-256 session key.</li>
        <li><span className="text-white">Base Sepolia</span> USDC settlement; facilitator sponsors gas.</li>
        <li>Spend caps + instant revocation from the Privy dashboard.</li>
      </ul>
    ),
  },
  {
    kicker: "Demo",
    title: "402 → sign → settle → 200 OK",
    body: (
      <ul className="space-y-2 text-muted">
        <li>Consumer requests the rationale → gets a real <span className="text-accent">402 Payment Required</span>.</li>
        <li>Privy TEE signs a $0.01 USDC authorization on Base.</li>
        <li>Facilitator settles; request auto-retries with the X-PAYMENT receipt.</li>
        <li>Provider returns the Bayesian edge. USDC moved. No human touched it.</li>
      </ul>
    ),
  },
  {
    kicker: "Why it wins",
    title: "Novelty · PMF · depth",
    body: (
      <ul className="space-y-2 text-muted">
        <li><span className="text-white">Bounty dead-on:</span> x402 moves USDC on Base; a service that earns + an agent that spends.</li>
        <li><span className="text-white">PMF:</span> every autonomous trading agent needs calibrated probability.</li>
        <li><span className="text-white">Depth:</span> Bayesian quant + ASGI x402 middleware + Privy TEE signing.</li>
        <li>Pre-existing: the Polymarket engine. Built today: Privy consumer + live x402 payment.</li>
      </ul>
    ),
  },
];

export default function PitchDeck() {
  const [i, setI] = useState(0);
  const navigate = useNavigate();

  const go = useCallback((d: number) => setI((p) => Math.min(slides.length - 1, Math.max(0, p + d))), []);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "ArrowRight" || e.key === " ") go(1);
      if (e.key === "ArrowLeft") go(-1);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [go]);

  const s = slides[i];
  const last = i === slides.length - 1;

  return (
    <main className="max-w-[1100px] mx-auto px-6 py-10">
      <div className="rounded-2xl border border-edge bg-gradient-to-br from-panel to-ink min-h-[460px] p-10 flex flex-col">
        <div className="text-accent text-xs uppercase tracking-[0.2em]">{s.kicker}</div>
        <h1 className="text-3xl font-semibold mt-3 mb-6">{s.title}</h1>
        <div className="text-sm leading-relaxed flex-1">{s.body}</div>

        <div className="flex items-center justify-between mt-8">
          <div className="flex gap-1.5">
            {slides.map((_, idx) => (
              <button
                key={idx}
                onClick={() => setI(idx)}
                className={`h-1.5 rounded-full transition-all ${
                  idx === i ? "w-8 bg-accent" : "w-3 bg-edge hover:bg-muted"
                }`}
              />
            ))}
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => go(-1)}
              disabled={i === 0}
              className="text-xs border border-edge rounded px-3 py-1.5 hover:bg-edge disabled:opacity-40"
            >
              ← Prev
            </button>
            {last ? (
              <button
                onClick={() => navigate("/x402-lab")}
                className="text-xs border border-accent/40 text-accent bg-accent/10 rounded px-3 py-1.5 hover:bg-accent/20"
              >
                Run the live demo →
              </button>
            ) : (
              <button
                onClick={() => go(1)}
                className="text-xs border border-accent/40 text-accent bg-accent/10 rounded px-3 py-1.5 hover:bg-accent/20"
              >
                Next →
              </button>
            )}
          </div>
        </div>
      </div>
      <div className="text-center text-muted text-[10px] mt-4">
        Use ← / → arrow keys · slide {i + 1} of {slides.length}
      </div>
    </main>
  );
}
