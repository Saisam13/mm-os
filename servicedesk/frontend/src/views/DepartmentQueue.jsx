import { useEffect, useState } from "react";
import { api } from "../api.js";
import { StatusPill, PrivatePill, Ref, age } from "../components.jsx";

// docs/07 "Who can see what": everyone in the department sees every request it raised,
// including assignee and how long it has waited. A private request still appears here as a
// hidden row so the count stays honest — this component never sees a title/body for one
// (app/privacy.py filters them out server-side), so there is nothing here for it to hide.
export default function DepartmentQueue({ onOpen }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    api.listDepartment().then(setRows).catch((e) => setError(e.message));
  }, []);

  return (
    <main>
      <div className="page-head"><h1>Department queue</h1></div>
      {error && <p className="error-text">{error}</p>}
      <div className="card">
        <table>
          <thead>
            <tr><th>Ref</th><th>Title</th><th>Status</th><th>Assignee</th><th>Age</th></tr>
          </thead>
          <tbody>
            {rows?.length === 0 && (
              <tr><td colSpan={5} className="empty">Nothing raised by this department yet.</td></tr>
            )}
            {rows?.map((t) => (
              <tr
                key={t.id}
                className={t.hidden ? "hidden-row" : ""}
                onClick={() => onOpen(t.id)}
                style={{ cursor: "pointer" }}
              >
                <td><Ref>{t.ref}</Ref></td>
                <td>{t.hidden ? <><PrivatePill /> private request</> : <>{t.title} {t.is_private && <PrivatePill />}</>}</td>
                <td><StatusPill status={t.status} /></td>
                <td className="cond">{t.assignee_sub || "unassigned"}</td>
                <td className="num">{age(t.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  );
}
