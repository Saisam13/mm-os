// Stand-in for MM OS's real handoff (click a tile, arrive signed in via
// /_mmos/accept#token=...). Exercises the same POST /_mmos/accept endpoint against a
// dev-minted token so the placeholder page is actually reachable before that integration
// lands. Mirrors servicedesk/frontend/src/DevSignIn.jsx, trimmed to one generic persona —
// this shell has no seeded employees (rule: no real employee data in this repo).
import { useState } from "react";
import { setToken } from "./api.js";

export default function DevSignIn({ onSignedIn }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function signIn() {
    setBusy(true);
    setError(null);
    try {
      const minted = await fetch("/_dev/token", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: "Dev User", roles: ["viewer"] }),
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
    <main style={{ maxWidth: 460, margin: "48px auto", padding: "0 16px" }}>
      <div className="page-head"><h1>Item Code Studio</h1></div>
      <p style={{ color: "var(--text-2)" }}>
        Sign-in normally arrives from MM OS. Until that integration is wired in, mint a
        local dev token to continue.
      </p>
      <div className="card" style={{ padding: 16 }}>
        <button
          style={{
            display: "block", width: "100%", padding: "10px 14px",
            background: "var(--petrol)", color: "#fff", border: "none",
            borderRadius: "var(--r)", cursor: "pointer", font: "inherit",
          }}
          disabled={busy} onClick={signIn}
        >
          {busy ? "Signing in…" : "Sign in (dev)"}
        </button>
      </div>
      {error && <p style={{ color: "#B3261E" }}>{error}</p>}
    </main>
  );
}
