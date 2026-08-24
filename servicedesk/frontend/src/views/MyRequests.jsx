import { useEffect, useState } from "react";
import { api } from "../api.js";
import { StatusPill, PrivatePill, Ref, age, requestTypeLabel } from "../components.jsx";

export default function MyRequests({ onOpen, onNew }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.listMine().then(setRows).catch((e) => setError(e.message));
  }, []);

  return (
    <main>
      <div className="page-head">
        <h1>My requests</h1>
        <button className="btn primary" onClick={onNew}>New request</button>
      </div>
      {error && <p className="error-text">{error}</p>}
      <div className="card">
        <table>
          <thead>
            <tr><th>Ref</th><th>Title</th><th>Type</th><th>Status</th><th>Age</th></tr>
          </thead>
          <tbody>
            {rows?.length === 0 && (
              <tr><td colSpan={5} className="empty">Nothing raised yet.</td></tr>
            )}
            {rows?.map((t) => (
              <tr key={t.id} onClick={() => onOpen(t.id)} style={{ cursor: "pointer" }}>
                <td><Ref>{t.ref}</Ref></td>
                <td>{t.title} {t.is_private && <PrivatePill />}</td>
                <td className="cond">{t.kind}</td>
                <td><StatusPill status={t.status} /></td>
                <td className="num">{age(t.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
