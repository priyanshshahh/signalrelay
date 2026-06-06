import { NavLink, Outlet } from "react-router-dom";

const nav = [
  { to: "/", label: "Command Center", end: true },
  { to: "/x402-lab", label: "x402 Lab" },
  { to: "/pitch", label: "Pitch Deck" },
];

export default function Layout() {
  return (
    <div className="min-h-screen text-sm">
      <header className="border-b border-edge bg-panel/60 sticky top-0 backdrop-blur z-30">
        <div className="max-w-[1400px] mx-auto px-6 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-2.5 h-2.5 rounded-full bg-accent shadow-[0_0_10px_#7cf6c4]" />
            <div className="font-semibold tracking-wide">
              SIGNAL<span className="text-accent">RELAY</span>
            </div>
            <span className="text-[10px] text-muted hidden sm:inline">
              agent-to-agent alpha · Privy × Base × x402
            </span>
          </div>
          <nav className="flex items-center gap-1">
            {nav.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={({ isActive }) =>
                  `text-xs px-3 py-1.5 rounded-lg border transition ${
                    isActive
                      ? "border-accent/40 text-accent bg-accent/10"
                      : "border-transparent text-muted hover:text-white hover:bg-edge"
                  }`
                }
              >
                {n.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <Outlet />
      <footer className="text-center text-muted text-[10px] py-6">
        SignalRelay · paper trading by default · USDC on Base Sepolia · key custody by Privy TEE
      </footer>
    </div>
  );
}
