import { useEffect, useState } from "react";
import { setToken } from "./api.js";

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
  const [info, setInfo] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/_mmos/info")
      .then((r) => r.ok ? r.json() : null)
      .then((data) => { setInfo(data); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

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

  if (loading) {
    return (
      <main style={{ maxWidth: 460, textAlign: "center", paddingTop: 80 }}>
        <p style={{ color: "var(--text-2)" }}>Loading…</p>
      </main>
    );
  }

  if (info && info.auth_mode === "http") {
    const osUrl = info.os_url || "https://m-mines.in";
    const launchUrl = `${osUrl}/dashboard?app=${info.slug || "servicedesk"}`;
    return (
      <main style={{ maxWidth: 460 }}>
        <div className="page-head"><h1>Service Desk</h1></div>
        <div className="card" style={{ padding: 24, textAlign: "center" }}>
          <p style={{ color: "var(--text-2)", marginBottom: 16 }}>
            Sign in through MM OS to access Service Desk.
          </p>
          <a href={launchUrl} className="btn" style={{ display: "inline-block", textDecoration: "none" }}>
            Sign in via MM OS
          </a>
        </div>
      </main>
    );
  }

  return (
    <main style={{ maxWidth: 460 }}>
      <div className="page-head"><h1>Service Desk</h1></div>
      <p style={{ color: "var(--text-2)" }}>
        Dev mode — pick a seeded person to continue.
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
