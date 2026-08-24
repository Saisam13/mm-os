// Stand-in for MM OS's real handoff (docs/04-auth-flow.md: click a tile, arrive signed in
// via /_mmos/accept#token=...). That depends on packages/mmos-client-py (agent A4) and
// embed.js, neither of which exist yet — see `## Assumptions` in the handoff. This screen
// exercises the same POST /_mmos/accept endpoint against a dev-minted token so the four
// views are actually clickable before that integration lands.
import { useState } from "react";
import { setToken } from "./api.js";

// Real MiniMines employees (backend/app/demo_seed.py), keyed by employee code so the same
// person resolves the same way in MM OS — see app/org_chart.py's SEED_PERSONAS.
const PERSONAS = [
  { key: "MM88", label: "MM88 · MAMATESH UDAY NAIK · Projects · requester", roles: ["requester"] },
  { key: "MM81", label: "MM81 · Chandrashekhar Keshav Kalvit · Projects · approver", roles: ["requester"] },
  { key: "MM05", label: "MM05 · Mandaleshvar Sharma · P-Spoke · IT agent", roles: ["agent"] },
  { key: "MM33", label: "MM33 · Hardhik Pendurthi · StratOps · requester", roles: ["requester"] },
  { key: "MM-ITADMIN", label: "MM-ITADMIN · IT Administrator · Service Desk admin", roles: ["admin"] },
];

export default function DevSignIn({ onSignedIn }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function signInAs(persona) {
    setBusy(true);
    setError(null);
    try {
      const minted = await fetch("/_dev/token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ persona: persona.key, roles: persona.roles }),
      }).then((r) => {
        if (!r.ok) throw new Error("dev_token_unavailable");
        return r.json();
      });
      setToken(minted.token);
      onSignedIn();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main style={{ maxWidth: 460 }}>
      <div className="page-head"><h1>Service Desk</h1></div>
      <p style={{ color: "var(--text-2)" }}>
        Sign-in normally arrives from MM OS. Until that integration is wired in, pick a
        seeded person to continue.
      </p>
      <div className="card" style={{ padding: 16 }}>
        {PERSONAS.map((p) => (
          <button key={p.key} className="btn" style={{ display: "block", width: "100%", marginBottom: 8 }}
                  disabled={busy} onClick={() => signInAs(p)}>
            {p.label}
          </button>
        ))}
      </div>
      {error && <p className="error-text">{error}</p>}
    </main>
  );
}
