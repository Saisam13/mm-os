import { useEffect, useState } from "react";
import { api } from "../api.js";

// Identity (name, department, employee code) is read-only here, sourced from the org-chart
// directory MM OS owns — this page only edits the three Service-Desk-local flags. `is_agent`
// is informational (the real `agent` grant that gates the API comes from MM OS's own Access
// page); `is_department_manager` and `is_approver` are Service-Desk-local and feed the
// Approval Routing tab's approver picker.
export default function AdminUsersRoles() {
  const [roles, setRoles] = useState(null);
  const [people, setPeople] = useState([]);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(false);

  function load() {
    Promise.all([api.listRoles(), api.listPeople()])
      .then(([r, p]) => { setRoles(r); setPeople(p); })
      .catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function toggle(row, field) {
    try {
      await api.upsertRole(row.sub, {
        employee_code: row.employee_code, full_name: row.full_name, department: row.department,
        is_agent: row.is_agent, is_department_manager: row.is_department_manager, is_approver: row.is_approver,
        [field]: !row[field],
      });
      load();
    } catch (e) {
      setError(e.detail?.error || e.message);
    }
  }

  async function revoke(sub) {
    await api.deleteRole(sub);
    load();
  }

  return (
    <div>
      <div className="panel-header" style={{ display: "flex", justifyContent: "space-between", marginBottom: 14 }}>
        <p className="section-title" style={{ margin: 0 }}>Users &amp; roles</p>
        <button className="btn primary" onClick={() => setModal(true)}>Grant a role</button>
      </div>
      {error && <p className="error-text">{error}</p>}
      <div className="card">
        <table>
          <thead>
            <tr><th>Name</th><th>Code</th><th>Department</th><th>IT agent</th><th>Dept. manager</th><th>Approver</th><th></th></tr>
          </thead>
          <tbody>
            {roles?.length === 0 && <tr><td colSpan={7} className="empty">No local roles granted yet.</td></tr>}
            {roles?.map((r) => (
              <tr key={r.sub}>
                <td>{r.full_name || "—"}</td>
                <td className="cond">{r.employee_code}</td>
                <td>{r.department || "—"}</td>
                <td><input type="checkbox" style={{ width: "auto" }} checked={r.is_agent} onChange={() => toggle(r, "is_agent")} /></td>
                <td><input type="checkbox" style={{ width: "auto" }} checked={r.is_department_manager} onChange={() => toggle(r, "is_department_manager")} /></td>
                <td><input type="checkbox" style={{ width: "auto" }} checked={r.is_approver} onChange={() => toggle(r, "is_approver")} /></td>
                <td><button className="btn" onClick={() => revoke(r.sub)}>Revoke</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {modal && (
        <GrantModal
          people={people}
          existing={roles || []}
          onClose={() => setModal(false)}
          onSaved={() => { setModal(false); load(); }}
        />
      )}
    </div>
  );
}

function GrantModal({ people, existing, onClose, onSaved }) {
  const grantedSubs = new Set(existing.map((r) => r.sub));
  const [sub, setSub] = useState("");
  const [flags, setFlags] = useState({ is_agent: false, is_department_manager: false, is_approver: false });
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const picked = people.find((p) => p.sub === sub);

  async function submit(e) {
    e.preventDefault();
    if (!picked) return;
    setBusy(true);
    setError(null);
    try {
      await api.upsertRole(picked.sub, {
        employee_code: picked.employee_code, full_name: picked.full_name, department: picked.department,
        ...flags,
      });
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
        <h2>Grant a role</h2>
        <label>Person</label>
        <select required value={sub} onChange={(e) => setSub(e.target.value)}>
          <option value="">Select…</option>
          {people.map((p) => (
            <option key={p.sub} value={p.sub}>
              {p.full_name} — {p.employee_code} ({p.department}){grantedSubs.has(p.sub) ? " · already has roles" : ""}
            </option>
          ))}
        </select>
        <div style={{ marginTop: 14 }}>
          <label className="flag" style={{ display: "inline-flex" }}>
            <input type="checkbox" checked={flags.is_agent} onChange={(e) => setFlags({ ...flags, is_agent: e.target.checked })} />
            IT agent
          </label>
          <label className="flag" style={{ display: "inline-flex" }}>
            <input type="checkbox" checked={flags.is_department_manager} onChange={(e) => setFlags({ ...flags, is_department_manager: e.target.checked })} />
            Department manager
          </label>
          <label className="flag" style={{ display: "inline-flex" }}>
            <input type="checkbox" checked={flags.is_approver} onChange={(e) => setFlags({ ...flags, is_approver: e.target.checked })} />
            Approver
          </label>
        </div>
        {error && <p className="error-text">{error}</p>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn primary" disabled={busy || !picked}>Save</button>
        </div>
      </form>
    </div>
  );
}
