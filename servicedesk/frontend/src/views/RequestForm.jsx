import { useState } from "react";
import { api } from "../api.js";

// Three request types, not a department picker (scope decision, 25 Aug 2026) — the requester
// picks *what kind of request this is*, never a team. Department is stamped on the ticket
// server-side from the requester's own token claim (routers/tickets.py: `requester_dept =
// user.department`), never asked here. "Software" and "hardware" are both `kind: "support"`
// tickets distinguished by `service_slug` — no approval step, straight to the IT queue.
// "Automation" is the only type that needs an approver (app/routing.py).
const TYPES = [
  {
    value: "automation", kind: "automation", service_slug: null,
    label: "Automation request — I want something built or automated",
    hint: "Requires approval. IT scopes it, then an approver decides before any build starts.",
  },
  {
    value: "software", kind: "support", service_slug: "software",
    label: "Software issue — an application is broken or misbehaving",
    hint: "No approval needed. Goes straight to the IT queue.",
  },
  {
    value: "hardware", kind: "support", service_slug: "hardware",
    label: "Hardware issue — a device, machine or physical asset problem",
    hint: "No approval needed. Goes straight to the IT queue.",
  },
];

export default function RequestForm({ onCreated, onCancel }) {
  const [type, setType] = useState("software");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [priority, setPriority] = useState("normal");
  const [isPrivate, setIsPrivate] = useState(false);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const selected = TYPES.find((t) => t.value === type);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const ticket = await api.createTicket({
        kind: selected.kind, service_slug: selected.service_slug,
        title, body, priority, is_private: isPrivate,
      });
      onCreated(ticket.id);
    } catch (e) {
      setError(e.detail?.error || e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <main style={{ maxWidth: 640 }}>
      <div className="page-head"><h1>New request</h1></div>
      <form className="card" style={{ padding: 20 }} onSubmit={submit}>
        <label>Type</label>
        <select value={type} onChange={(e) => setType(e.target.value)}>
          {TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
        </select>
        <p className="field-hint">{selected.hint}</p>

        <label>Title</label>
        <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} required />

        <label>{type === "automation" ? "What should this do, and why" : "Describe the problem"}</label>
        <textarea value={body} onChange={(e) => setBody(e.target.value)} required />

        <label>Priority</label>
        <select value={priority} onChange={(e) => setPriority(e.target.value)}>
          <option value="low">Low</option>
          <option value="normal">Normal</option>
          <option value="high">High</option>
          <option value="urgent">Urgent</option>
        </select>

        <label style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 16 }}>
          <input type="checkbox" style={{ width: "auto" }} checked={isPrivate} onChange={(e) => setIsPrivate(e.target.checked)} />
          Private — visible only to me, the assignee and my approver
        </label>

        {error && <p className="error-text">{error}</p>}
        <div style={{ display: "flex", gap: 8, marginTop: 18 }}>
          <button type="submit" className="btn primary" disabled={busy}>Submit</button>
          <button type="button" className="btn" onClick={onCancel}>Cancel</button>
        </div>
      </form>
    </main>
  );
}
