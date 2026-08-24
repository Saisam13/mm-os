import { useEffect, useState } from "react";
import { api } from "../api.js";
import { StatusPill, PrivatePill, Ref } from "../components.jsx";

const SUPPORT_NEXT = {
  open: ["in_progress", "rejected"],
  in_progress: ["waiting_on_requester"],
  waiting_on_requester: ["resolved"],
  resolved: ["closed"],
  closed: ["resolved"],
};
const AUTOMATION_NEXT = {
  submitted: ["it_review"],
  it_review: ["rejected"],
  proposal_ready: ["manager_review"],
  approved: ["in_build"],
  in_build: ["deployed"],
  deployed: ["closed"],
  changes_requested: ["it_review"],
};

export default function TicketDetail({ ticketId, me, onBack }) {
  const [ticket, setTicket] = useState(null);
  const [comments, setComments] = useState([]);
  const [proposals, setProposals] = useState([]);
  const [events, setEvents] = useState([]);
  const [error, setError] = useState(null);
  const [commentBody, setCommentBody] = useState("");
  const [commentInternal, setCommentInternal] = useState(false);
  const [proposalDraft, setProposalDraft] = useState({ scope_summary: "", effort_days: "", alternatives: "", risks: "" });
  const [busy, setBusy] = useState(false);

  const isAgent = (me.roles || []).includes("agent") || (me.roles || []).includes("admin") || me.platform_admin;

  async function load() {
    const t = await api.getTicket(ticketId);
    setTicket(t);
    if (t.hidden) return; // no title/body/comments to fetch — app/privacy.py already withheld them
    const [c, ev] = await Promise.all([api.listComments(ticketId), api.listEvents(ticketId)]);
    setComments(c);
    setEvents(ev);
    if (t.kind === "automation") setProposals(await api.listProposals(ticketId));
  }
  useEffect(() => { load().catch((e) => setError(e.message)); }, [ticketId]);

  async function doTransition(to_status) {
    setBusy(true);
    try {
      await api.transition(ticketId, to_status);
      await load();
    } catch (e) {
      setError(e.detail?.error || e.message);
    } finally {
      setBusy(false);
    }
  }

  async function submitComment(e) {
    e.preventDefault();
    if (!commentBody.trim()) return;
    await api.createComment(ticketId, commentBody, commentInternal);
    setCommentBody("");
    setCommentInternal(false);
    load();
  }

  async function submitProposal(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await api.createProposal(ticketId, {
        scope_summary: proposalDraft.scope_summary,
        effort_days: proposalDraft.effort_days ? Number(proposalDraft.effort_days) : null,
        resources: {},
        risks: proposalDraft.risks || null,
        alternatives: proposalDraft.alternatives,
      });
      setProposalDraft({ scope_summary: "", effort_days: "", alternatives: "", risks: "" });
      await load();
    } catch (e) {
      setError(e.detail?.error || e.message);
    } finally {
      setBusy(false);
    }
  }

  if (!ticket) return <main>{error && <p className="error-text">{error}</p>}</main>;

  if (ticket.hidden) {
    return (
      <main>
        <button className="btn" onClick={onBack}>Back</button>
        <div className="page-head"><h1><Ref>{ticket.ref}</Ref> · Private request</h1></div>
        <p className="empty">
          Visible only to the requester, the assignee and the approver. Age and assignee are
          shown in the department queue; nothing else.
        </p>
      </main>
    );
  }

  const nextStates = ticket.kind === "support" ? SUPPORT_NEXT : AUTOMATION_NEXT;
  const canPropose = isAgent && ticket.kind === "automation" && ["it_review", "changes_requested"].includes(ticket.status);
  const canSendToManager = isAgent && ticket.status === "proposal_ready";

  return (
    <main>
      <button className="btn" onClick={onBack}>Back</button>
      <div className="page-head">
        <h1><Ref>{ticket.ref}</Ref> · {ticket.title} {ticket.is_private && <PrivatePill />}</h1>
        <StatusPill status={ticket.status} />
      </div>
      {error && <p className="error-text">{error}</p>}

      <div className="card" style={{ padding: 18 }}>
        <p>{ticket.body}</p>
        <p className="cond" style={{ color: "var(--text-3)", marginTop: 10 }}>
          {ticket.kind} · {ticket.requester_code} · {ticket.requester_dept} · priority {ticket.priority}
        </p>
      </div>

      {ticket.sla && (
        <div className="card" style={{ padding: 14, marginTop: 12, display: "flex", gap: 22 }}>
          <div>
            <p className="section-title" style={{ margin: "0 0 4px" }}>Response</p>
            <p className="num">
              {ticket.sla.response_elapsed_minutes}m of {ticket.sla.response_target_minutes}m target
              {ticket.sla.response_pending && " (pending)"}
            </p>
          </div>
          <div>
            <p className="section-title" style={{ margin: "0 0 4px" }}>Resolution</p>
            <p className="num">
              {ticket.sla.resolution_elapsed_minutes}m of {ticket.sla.resolution_target_minutes}m target
              {ticket.sla.resolution_pending && " (pending)"}
            </p>
          </div>
          {ticket.sla.breached && <span className="pill" style={{ background: "var(--orange-100)", color: "var(--orange)" }}>SLA breached</span>}
        </div>
      )}

      <p className="section-title">Actions</p>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {(nextStates[ticket.status] || []).map((to) => (
          <button key={to} className={to === "approved" ? "btn action" : "btn"} disabled={busy}
                  onClick={() => doTransition(to)}>
            {to.replaceAll("_", " ")}
          </button>
        ))}
        {canSendToManager && (
          <button className="btn action" disabled={busy} onClick={() => doTransition("manager_review")}>
            Send to manager
          </button>
        )}
      </div>

      {ticket.kind === "automation" && (
        <>
          <p className="section-title">Proposal{proposals.length > 1 ? ` (v${proposals.length})` : ""}</p>
          {proposals.map((p) => (
            <div key={p.id} className="card" style={{ padding: 14, marginBottom: 10 }}>
              <p className="cond" style={{ color: "var(--text-3)" }}>version {p.version}</p>
              <p>{p.scope_summary}</p>
              <p>{p.effort_days ?? "—"} days · <code>{JSON.stringify(p.resources)}</code></p>
              <p><strong>Alternatives:</strong> {p.alternatives}</p>
              {p.risks && <p><strong>Risks:</strong> {p.risks}</p>}
            </div>
          ))}
          {proposals.length === 0 && <p className="empty">No proposal yet.</p>}

          {canPropose && (
            <form className="card" style={{ padding: 14 }} onSubmit={submitProposal}>
              <label>Scope summary</label>
              <textarea required value={proposalDraft.scope_summary}
                        onChange={(e) => setProposalDraft({ ...proposalDraft, scope_summary: e.target.value })} />
              <label>Effort (days)</label>
              <input type="number" step="0.5" value={proposalDraft.effort_days}
                     onChange={(e) => setProposalDraft({ ...proposalDraft, effort_days: e.target.value })} />
              <label>Alternatives (required)</label>
              <textarea required value={proposalDraft.alternatives}
                        onChange={(e) => setProposalDraft({ ...proposalDraft, alternatives: e.target.value })} />
              <label>Risks</label>
              <textarea value={proposalDraft.risks}
                        onChange={(e) => setProposalDraft({ ...proposalDraft, risks: e.target.value })} />
              <button type="submit" className="btn primary" disabled={busy} style={{ marginTop: 12 }}>
                Save proposal
              </button>
            </form>
          )}
        </>
      )}

      <p className="section-title">Comments</p>
      {comments.map((c) => (
        <div key={c.id} className={`comment${c.is_internal ? " internal" : ""}`}>
          <p className="meta cond">{c.author_sub}{c.is_internal ? " · internal" : ""}</p>
          <p>{c.body}</p>
        </div>
      ))}
      <form onSubmit={submitComment} style={{ marginTop: 10 }}>
        <textarea value={commentBody} onChange={(e) => setCommentBody(e.target.value)} placeholder="Add a comment" />
        {isAgent && (
          <label style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" style={{ width: "auto" }} checked={commentInternal}
                   onChange={(e) => setCommentInternal(e.target.checked)} />
            Internal note (IT only)
          </label>
        )}
        <button type="submit" className="btn" style={{ marginTop: 8 }}>Comment</button>
      </form>

      <p className="section-title">History</p>
      {events.map((e) => (
        <div key={e.id} className="event-row">
          <time>{new Date(e.created_at).toLocaleString()}</time>
          <span>{e.from_status ? `${e.from_status} -> ${e.to_status}` : `created (${e.to_status})`}</span>
        </div>
      ))}
    </main>
  );
}
