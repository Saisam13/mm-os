import { useEffect, useState } from "react";
import { api } from "../api.js";
import { StatusPill, PrivatePill, Ref, age } from "../components.jsx";

// Triage and assign happen here; proposing, revising and resolving happen on the ticket
// detail page once claimed (TicketDetail.jsx) — the same workspace either way, per docs/07.
export default function AgentConsole({ onOpen }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);

  function load() {
    api.listQueue().then(setRows).catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function claim(id) {
    setBusyId(id);
    try {
      await api.assign(id, null); // null = claim for the calling agent
      load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <main>
      <div className="page-head"><h1>IT console</h1></div>
      {error && <p className="error-text">{error}</p>}
      <div className="card">
        <table>
          <thead>
            <tr><th>Ref</th><th>Title</th><th>Kind</th><th>Status</th><th>Assignee</th><th>Age</th><th></th></tr>
          </thead>
          <tbody>
            {rows?.length === 0 && (
              <tr><td colSpan={7} className="empty">Queue is empty.</td></tr>
            )}
            {rows?.map((t) => (
              <tr key={t.id}>
                <td onClick={() => onOpen(t.id)} style={{ cursor: "pointer" }}><Ref>{t.ref}</Ref></td>
                <td onClick={() => onOpen(t.id)} style={{ cursor: "pointer" }}>{t.title} {t.is_private && <PrivatePill />}</td>
                <td className="cond">{t.kind}</td>
                <td><StatusPill status={t.status} /></td>
                <td className="cond">{t.assignee_sub || "—"}</td>
                <td className="num">{age(t.created_at)}</td>
                <td>
                  {!t.assignee_sub && (
                    <button className="btn" disabled={busyId === t.id} onClick={() => claim(t.id)}>
                      Assign to me
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
