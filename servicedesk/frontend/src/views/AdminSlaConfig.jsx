import { useEffect, useState } from "react";
import { api } from "../api.js";

const PRIORITIES = ["low", "normal", "high", "urgent"];

// sla_configs(department_id, priority, response_time_minutes, resolution_time_minutes),
// unique on (department, priority) — upsert on save, ported from MiniHelp's server/api/sla.php.
export default function AdminSlaConfig() {
  const [departments, setDepartments] = useState([]);
  const [configs, setConfigs] = useState([]);
  const [deptId, setDeptId] = useState("");
  const [draft, setDraft] = useState({});
  const [error, setError] = useState(null);
  const [savingKey, setSavingKey] = useState(null);

  function load() {
    Promise.all([api.listDepartments(), api.listSla()])
      .then(([d, c]) => {
        setDepartments(d.filter((x) => x.is_active));
        setConfigs(c);
        if (!deptId && d.length) setDeptId(d.find((x) => x.is_active)?.id || "");
      })
      .catch((e) => setError(e.message));
  }
  useEffect(load, []);

  function valueFor(priority, field) {
    const key = `${deptId}:${priority}`;
    if (draft[key]?.[field] != null) return draft[key][field];
    const existing = configs.find((c) => c.department_id === deptId && c.priority === priority);
    return existing ? existing[field] : "";
  }

  function setValue(priority, field, value) {
    const key = `${deptId}:${priority}`;
    setDraft({ ...draft, [key]: { ...draft[key], [field]: value } });
  }

  async function save(priority) {
    const key = `${deptId}:${priority}`;
    const response_time_minutes = Number(valueFor(priority, "response_time_minutes"));
    const resolution_time_minutes = Number(valueFor(priority, "resolution_time_minutes"));
    if (!response_time_minutes || !resolution_time_minutes) {
      setError("Both targets must be greater than zero.");
      return;
    }
    setSavingKey(key);
    setError(null);
    try {
      await api.upsertSla({ department_id: deptId, priority, response_time_minutes, resolution_time_minutes });
      load();
    } catch (e) {
      setError(e.detail?.error || e.message);
    } finally {
      setSavingKey(null);
    }
  }

  return (
    <div>
      <p className="section-title" style={{ margin: "0 0 14px" }}>SLA configuration</p>
      {error && <p className="error-text">{error}</p>}
      <label>Department</label>
      <select value={deptId} onChange={(e) => setDeptId(e.target.value)} style={{ maxWidth: 280 }}>
        {departments.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
      </select>

      <div className="card" style={{ marginTop: 16 }}>
        <table>
          <thead>
            <tr><th>Priority</th><th>Response target (min)</th><th>Resolution target (min)</th><th></th></tr>
          </thead>
          <tbody>
            {PRIORITIES.map((p) => (
              <tr key={p}>
                <td><span className={`pill priority-${p}`}>{p}</span></td>
                <td>
                  <input type="number" min="1" value={valueFor(p, "response_time_minutes")}
                         onChange={(e) => setValue(p, "response_time_minutes", e.target.value)} />
                </td>
                <td>
                  <input type="number" min="1" value={valueFor(p, "resolution_time_minutes")}
                         onChange={(e) => setValue(p, "resolution_time_minutes", e.target.value)} />
                </td>
                <td>
                  <button className="btn primary" disabled={savingKey === `${deptId}:${p}`} onClick={() => save(p)}>
                    Save
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
