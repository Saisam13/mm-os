import { useEffect, useState } from "react";
import { api } from "../api.js";

const PRIORITIES = ["low", "normal", "high", "urgent"];

// The explicit department/category/priority approval matrix — overrides the manager-chain
// walk (app/org_chart.py) where a rule matches, falls back to the chain where none does, and
// falls back to the default approver below where the chain itself has nobody to escalate to
// (today's actual failure mode: only 11 of 73 managers resolve). See app/routing.py.
export default function AdminApprovalRouting() {
  const [rules, setRules] = useState(null);
  const [people, setPeople] = useState([]);
  const [defaultApprover, setDefaultApprover] = useState(null);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(null); // null | "new" | rule object
  const [preview, setPreview] = useState(null);
  const [previewForm, setPreviewForm] = useState({ department: "", category: "", priority: "normal", requester_sub: "" });

  function load() {
    Promise.all([api.listApprovalRules(), api.listPeople(), api.getApprovalDefault().catch(() => null)])
      .then(([r, p, d]) => { setRules(r); setPeople(p); setDefaultApprover(d); })
      .catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function remove(id) {
    await api.deleteApprovalRule(id);
    load();
  }

  async function toggleActive(rule) {
    await api.updateApprovalRule(rule.id, { ...ruleToBody(rule), is_active: !rule.is_active });
    load();
  }

  async function runPreview(e) {
    e.preventDefault();
    try {
      const result = await api.previewRouting({
        department: previewForm.department,
        category: previewForm.category || null,
        priority: previewForm.priority,
        requester_sub: previewForm.requester_sub || null,
      });
      setPreview(result);
    } catch (e) {
      setError(e.detail?.error || e.message);
    }
  }

  return (
    <div>
      <div className="panel-header" style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
        <p className="section-title" style={{ margin: 0 }}>Approval routing</p>
        <button className="btn primary" onClick={() => setModal("new")}>Add rule</button>
      </div>
      <p className="field-hint" style={{ margin: "0 0 14px" }}>
        Governs automation requests only. Software and hardware issues need no approval and
        never consult this table.
      </p>
      {error && <p className="error-text">{error}</p>}

      <div className="card">
        <table>
          <thead>
            <tr><th>Rule</th><th>Department</th><th>Category</th><th>Priority</th><th>Approvers</th><th>Mode</th><th>Status</th><th></th></tr>
          </thead>
          <tbody>
            {rules?.length === 0 && <tr><td colSpan={8} className="empty">No rules yet — every automation request falls back to the manager chain.</td></tr>}
            {rules?.map((r) => (
              <tr key={r.id} className="rule-row">
                <td>{r.name}</td>
                <td>{r.department || <span className="wildcard">any</span>}</td>
                <td>{r.category || <span className="wildcard">any</span>}</td>
                <td>{r.priority || <span className="wildcard">any</span>}</td>
                <td>
                  <div className="chip-list">
                    {r.approvers.map((a, i) => <span className="chip" key={i}>{a.employee_code}</span>)}
                  </div>
                </td>
                <td className="cond">{r.mode === "sequence" ? "in sequence" : "any one of"}</td>
                <td>
                  <span className="pill" style={{ background: r.is_active ? "#E4F5EC" : "var(--surface-2)", color: r.is_active ? "var(--ok)" : "var(--text-3)" }}>
                    {r.is_active ? "active" : "inactive"}
                  </span>
                </td>
                <td style={{ display: "flex", gap: 8 }}>
                  <button className="btn" onClick={() => setModal(r)}>Edit</button>
                  <button className="btn" onClick={() => toggleActive(r)}>{r.is_active ? "Disable" : "Enable"}</button>
                  <button className="btn danger" onClick={() => remove(r.id)}>Delete</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="section-title">Default fallback approver</p>
      <p className="field-hint" style={{ margin: "0 0 8px" }}>
        Used only when no rule matches and the requester's manager chain has nobody left to
        escalate to — the one guarantee that a request never ends up with no approver at all.
      </p>
      <DefaultApproverPicker people={people} current={defaultApprover} onSaved={load} />

      <p className="section-title">Preview a request</p>
      <form className="card" style={{ padding: 14 }} onSubmit={runPreview}>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          <div style={{ flex: "1 1 160px" }}>
            <label>Department</label>
            <input required value={previewForm.department} onChange={(e) => setPreviewForm({ ...previewForm, department: e.target.value })} />
          </div>
          <div style={{ flex: "1 1 160px" }}>
            <label>Category (service slug)</label>
            <input value={previewForm.category} onChange={(e) => setPreviewForm({ ...previewForm, category: e.target.value })} placeholder="optional" />
          </div>
          <div style={{ flex: "1 1 140px" }}>
            <label>Priority</label>
            <select value={previewForm.priority} onChange={(e) => setPreviewForm({ ...previewForm, priority: e.target.value })}>
              {PRIORITIES.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </div>
          <div style={{ flex: "1 1 200px" }}>
            <label>Requester (optional)</label>
            <select value={previewForm.requester_sub} onChange={(e) => setPreviewForm({ ...previewForm, requester_sub: e.target.value })}>
              <option value="">Not specified</option>
              {people.map((p) => <option key={p.sub} value={p.sub}>{p.full_name} ({p.employee_code})</option>)}
            </select>
          </div>
        </div>
        <button type="submit" className="btn primary" style={{ marginTop: 12 }}>Preview routing</button>
      </form>
      {preview && <div className="preview-box">{preview.text}</div>}

      {modal && (
        <RuleModal
          rule={modal === "new" ? null : modal}
          people={people}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); load(); }}
        />
      )}
    </div>
  );
}

function ruleToBody(rule) {
  return {
    name: rule.name, department: rule.department, category: rule.category, priority: rule.priority,
    approvers: rule.approvers, mode: rule.mode, is_active: rule.is_active,
  };
}

function DefaultApproverPicker({ people, current, onSaved }) {
  const [sub, setSub] = useState(current?.sub || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => setSub(current?.sub || ""), [current]);

  async function save() {
    const picked = people.find((p) => p.sub === sub);
    if (!picked) return;
    setBusy(true);
    setError(null);
    try {
      await api.setApprovalDefault({ sub: picked.sub, employee_code: picked.employee_code });
      onSaved();
    } catch (e) {
      setError(e.detail?.error || e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card" style={{ padding: 14, display: "flex", gap: 10, alignItems: "center" }}>
      <select value={sub} onChange={(e) => setSub(e.target.value)} style={{ maxWidth: 320 }}>
        <option value="">Not configured</option>
        {people.map((p) => <option key={p.sub} value={p.sub}>{p.full_name} — {p.employee_code}</option>)}
      </select>
      <button className="btn action" disabled={busy || !sub} onClick={save}>Set default</button>
      {current && <span className="cond" style={{ color: "var(--text-3)" }}>current: {current.employee_code}</span>}
      {error && <span className="error-text">{error}</span>}
    </div>
  );
}

function RuleModal({ rule, people, onClose, onSaved }) {
  const [name, setName] = useState(rule?.name || "");
  const [department, setDepartment] = useState(rule?.department || "");
  const [category, setCategory] = useState(rule?.category || "");
  const [priority, setPriority] = useState(rule?.priority || "");
  const [mode, setMode] = useState(rule?.mode || "any_of");
  const [approverSubs, setApproverSubs] = useState((rule?.approvers || []).map((a) => a.sub));
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  function toggleApprover(sub) {
    setApproverSubs((cur) => (cur.includes(sub) ? cur.filter((s) => s !== sub) : [...cur, sub]));
  }

  async function submit(e) {
    e.preventDefault();
    const approvers = approverSubs
      .map((sub) => people.find((p) => p.sub === sub))
      .filter(Boolean)
      .map((p) => ({ sub: p.sub, employee_code: p.employee_code }));
    if (approvers.length === 0) {
      setError("Pick at least one approver.");
      return;
    }
    const body = {
      name, department: department || null, category: category || null, priority: priority || null,
      approvers, mode, is_active: rule?.is_active ?? true,
    };
    setBusy(true);
    setError(null);
    try {
      if (rule) await api.updateApprovalRule(rule.id, body);
      else await api.createApprovalRule(body);
      onSaved();
    } catch (e) {
      setError(e.detail?.error || e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <form className="modal" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h2>{rule ? "Edit rule" : "Add rule"}</h2>
        <label>Name</label>
        <input required value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Finance automation over high priority" />

        <label>Department (blank = any)</label>
        <input value={department} onChange={(e) => setDepartment(e.target.value)} />

        <label>Category / service slug (blank = any)</label>
        <input value={category} onChange={(e) => setCategory(e.target.value)} />

        <label>Priority (blank = any)</label>
        <select value={priority} onChange={(e) => setPriority(e.target.value)}>
          <option value="">any</option>
          {PRIORITIES.map((p) => <option key={p} value={p}>{p}</option>)}
        </select>

        <label>Mode</label>
        <select value={mode} onChange={(e) => setMode(e.target.value)}>
          <option value="any_of">Any one of the approvers</option>
          <option value="sequence">In sequence</option>
        </select>

        <label>Approvers</label>
        <div className="card" style={{ padding: 10, maxHeight: 160, overflowY: "auto" }}>
          {people.map((p) => (
            <label key={p.sub} className="flag" style={{ display: "flex", marginBottom: 4 }}>
              <input type="checkbox" checked={approverSubs.includes(p.sub)} onChange={() => toggleApprover(p.sub)} />
              {p.full_name} — {p.employee_code} ({p.department})
            </label>
          ))}
        </div>

        {error && <p className="error-text">{error}</p>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn primary" disabled={busy}>Save</button>
        </div>
      </form>
    </div>
  );
}
