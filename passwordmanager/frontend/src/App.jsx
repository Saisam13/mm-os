import React, { useEffect, useState } from "react";
import { api, getToken, setToken } from "./api.js";

// Placeholder shell UI: sign in via a dev token (local dev only — see mmos.py's
// `/_dev/token`, which 404s outside AUTH_MODE=stub), then show the authenticated
// placeholder message. No credential form, no vault UI, no secret storage of any kind —
// this is intentionally a stub, see ../SECURITY.md.
export default function App() {
  const [me, setMe] = useState(null);
  const [error, setError] = useState(null);

  async function refresh() {
    try {
      setMe(await api.me());
      setError(null);
    } catch (e) {
      setMe(null);
      setError(e.status === 401 ? null : e.message);
    }
  }

  useEffect(() => {
    if (getToken()) refresh();
  }, []);

  async function signIn() {
    const { token } = await api.devToken(["employee"]);
    setToken(token);
    await refresh();
  }

  return (
    <main style={{ fontFamily: "Roboto, Arial, sans-serif", maxWidth: "40rem", margin: "4rem auto", padding: "0 1rem" }}>
      <h1 style={{ color: "#005D7F" }}>Password Manager</h1>
      {me ? (
        <p>
          Password Manager — signed in as {me.name}. Your vault will live here.
        </p>
      ) : (
        <>
          <p>Not signed in.</p>
          <button onClick={signIn}>Dev sign-in (local only)</button>
        </>
      )}
      {error && <p style={{ color: "crimson" }}>{error}</p>}
      <p style={{ color: "#666", fontSize: "0.9rem" }}>
        This is a build shell — no credential storage exists yet. See SECURITY.md.
      </p>
    </main>
  );
}
