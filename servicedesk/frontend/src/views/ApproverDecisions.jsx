import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Ref, PrivatePill } from "../components.jsx";

// docs/07: "requests awaiting their decision, with proposal, resources and cost in view, and
// approve / reject / request-changes in place." Everything a decision needs is on this page —
// no detour to the detail page required.
export default function ApproverDecisions() {
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);
  const [comment, setComment] = useState({});
  const [busyId, setBusyId] = useState(null);

  async function load() {
    const tickets = await api.listApprovals();
    const withProposals = await Promise.all(
      tickets.map(async (t) => {
        const proposals = await api.listProposals(t.id);
        return { ticket: t, proposal: proposals[proposals.length - 1] || null };
      })
    );
    setItems(withProposals);
  }
  useEffect(() => { load().catch((e) => setError(e.message)); }, []);

  async function decide(ticketId, decision) {
    setBusyId(ticketId);
    try {
      await api.decide(ticketId, decision, comment[ticketId] || null);
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusyId(null);
    }
  }

  return (
    <main>
      <div className="page-head"><h1>Approvals</h1></div>
      {error && <p className="error-text">{error}</p>}
      {items?.length === 0 && <p className="empty">Nothing awaiting your decision.</p>}
      {items?.map(({ ticket, proposal }) => (
        <div key={ticket.id} className="card" style={{ padding: 18, marginBottom: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <h2 style={{ fontSize: 16 }}><Ref>{ticket.ref}</Ref> — {ticket.title} {ticket.is_private && <PrivatePill />}</h2>
            <span className="cond" style={{ color: "var(--text-3)" }}>{ticket.requester_code}</span>
          </div>

          {!proposal && <p className="error-text">No proposal on file — this ticket should not be here.</p>}
          {proposal && (
            <>
              <p className="section-title">Scope</p>
              <p>{proposal.scope_summary}</p>
              <p className="section-title">Effort / resources</p>
              <p>{proposal.effort_days ?? "—"} days · <code>{JSON.stringify(proposal.resources)}</code></p>
              <p className="section-title">Alternatives considered</p>
              <p>{proposal.alternatives}</p>
              {proposal.risks && (<><p className="section-title">Risks</p><p>{proposal.risks}</p></>)}
            </>
          )}

          <label>Comment (optional)</label>
          <textarea
            value={comment[ticket.id] || ""}
            onChange={(e) => setComment({ ...comment, [ticket.id]: e.target.value })}
          />
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button className="btn action" disabled={busyId === ticket.id} onClick={() => decide(ticket.id, "approved")}>Approve</button>
            <button className="btn" disabled={busyId === ticket.id} onClick={() => decide(ticket.id, "changes_requested")}>Request changes</button>
            <button className="btn danger" disabled={busyId === ticket.id} onClick={() => decide(ticket.id, "rejected")}>Reject</button>
          </div>
        </div>
      ))}
    </main>
  );
}
