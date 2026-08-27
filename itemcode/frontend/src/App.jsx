import { useEffect, useState } from "react";
import { api, clearToken, getToken } from "./api.js";
import DevSignIn from "./DevSignIn.jsx";

// The whole product, for now: prove a signed-in identity round-trips through the MM OS
// auth seam and show a placeholder. Item Code Studio's real screens land later.
export default function App() {
  const [me, setMe] = useState(null);
  const [error, setError] = useState(null);
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      setChecked(true);
      return;
    }
    api
      .me()
      .then(setMe)
      .catch((e) => {
        clearToken();
        setError(e.message);
      })
      .finally(() => setChecked(true));
  }, []);

  if (!checked) return null;

  if (!me) {
    return <DevSignIn onSignedIn={() => window.location.reload()} />;
  }

  return (
    <main style={{ maxWidth: 640, margin: "48px auto", padding: "0 16px" }}>
      <div className="page-head"><h1>Item Code Studio</h1></div>
      <div className="card" style={{ padding: 24 }}>
        <p style={{ fontSize: 18 }}>
          Item Code Studio — coming soon, signed in as <strong>{me.name || me.sub}</strong>.
        </p>
        <p style={{ color: "var(--text-2)" }}>
          {me.department ? `${me.department} · ` : ""}
          {(me.roles || []).join(", ") || "no roles yet"}
        </p>
        {error && <p style={{ color: "#B3261E" }}>{error}</p>}
        <button
          style={{
            marginTop: 12, padding: "8px 14px", background: "transparent",
            color: "var(--petrol)", border: "1px solid var(--petrol)",
            borderRadius: "var(--r)", cursor: "pointer", font: "inherit",
          }}
          onClick={() => { clearToken(); window.location.reload(); }}
        >
          Sign out
        </button>
      </div>
    </main>
  );
}
