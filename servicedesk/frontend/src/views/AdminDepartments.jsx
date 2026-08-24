import { useEffect, useState } from "react";
import { api } from "../api.js";

export default function AdminDepartments() {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(null); // null | "new" | department object being renamed

  function load() {
    api.listDepartments().then(setRows).catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function toggleActive(dept) {
    try {
      await api.updateDepartment(dept.id, { is_active: !dept.is_active });
      load();
    } catch (e) {
      setError(e.detail?.error || e.message);
    }
  }

  return (
    <div>
      <div className="panel-header" style={{ display: "flex", justifyContent: "space-between", marginBottom: 14 }}>
        <p className="section-title" style={{ margin: 0 }}>Departments</p>
        <button className="btn primary" onClick={() => setModal("new")}>Add department</button>
      </div>
      {error && <p className="error-text">{error}</p>}
      <div className="card">
        <table>
          <thead><tr><th>Name</th><th>Code</th><th>Status</th><th></th></tr></thead>
          <tbody>
            {rows?.length === 0 && <tr><td colSpan={4} className="empty">No departments yet.</td></tr>}
            {rows?.map((d) => (
              <tr key={d.id} className={!d.is_active ? "hidden-row" : ""}>
                <td>{d.name}</td>
                <td className="cond">{d.code || "—"}</td>
                <td><span className="pill" style={{ background: d.is_active ? "#E4F5EC" : "var(--surface-2)", color: d.is_active ? "var(--ok)" : "var(--text-3)" }}>
                  {d.is_active ? "active" : "inactive"}
                </span></td>
                <td style={{ display: "flex", gap: 8 }}>
                  <button className="btn" onClick={() => setModal(d)}>Rename</button>
                  <button className="btn" onClick={() => toggleActive(d)}>
                    {d.is_active ? "Deactivate" : "Reactivate"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {modal && (
        <DepartmentModal
          department={modal === "new" ? null : modal}
          onClose={() => setModal(null)}
          onSaved={() => { setModal(null); load(); }}
        />
      )}
    </div>
  );
}

function DepartmentModal({ department, onClose, onSaved }) {
  const [name, setName] = useState(department?.name || "");
  const [code, setCode] = useState(department?.code || "");
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  async function submit(e) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      if (department) await api.updateDepartment(department.id, { name, code: code || null });
      else await api.createDepartment({ name, code: code || null });
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
        <h2>{department ? "Rename department" : "Add department"}</h2>
        <label>Name</label>
        <input required value={name} onChange={(e) => setName(e.target.value)} />
        <label>Code</label>
        <input value={code} onChange={(e) => setCode(e.target.value)} placeholder="e.g. PSP" />
        {error && <p className="error-text">{error}</p>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn primary" disabled={busy}>Save</button>
        </div>
      </form>
    </div>
  );
}
