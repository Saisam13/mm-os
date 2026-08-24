import { useState } from "react";
import AdminDepartments from "./AdminDepartments.jsx";
import AdminUsersRoles from "./AdminUsersRoles.jsx";
import AdminSlaConfig from "./AdminSlaConfig.jsx";
import AdminApprovalRouting from "./AdminApprovalRouting.jsx";

const TABS = [
  { key: "departments", label: "Departments", Component: AdminDepartments },
  { key: "roles", label: "Users & Roles", Component: AdminUsersRoles },
  { key: "sla", label: "SLA Config", Component: AdminSlaConfig },
  { key: "routing", label: "Approval Routing", Component: AdminApprovalRouting },
];

export default function Administration() {
  const [tab, setTab] = useState("departments");
  const active = TABS.find((t) => t.key === tab);
  const Active = active.Component;

  return (
    <main>
      <div className="page-head"><h1>Administration</h1></div>
      <nav className="subnav">
        {TABS.map((t) => (
          <button key={t.key} className={tab === t.key ? "active" : ""} onClick={() => setTab(t.key)}>
            {t.label}
          </button>
        ))}
      </nav>
      <Active />
    </main>
  );
}
