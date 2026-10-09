import { useEffect, useState } from "react";
import { api, decodeClaims, getToken, clearToken } from "./api.js";
import DevSignIn from "./DevSignIn.jsx";
import MyRequests from "./views/MyRequests.jsx";
import DepartmentQueue from "./views/DepartmentQueue.jsx";
import AgentConsole from "./views/AgentConsole.jsx";
import ApproverDecisions from "./views/ApproverDecisions.jsx";
import RequestForm from "./views/RequestForm.jsx";
import TicketDetail from "./views/TicketDetail.jsx";
import Administration from "./views/Administration.jsx";

const NAV = [
  { key: "mine", label: "My requests" },
  { key: "dept", label: "Department queue" },
  { key: "queue", label: "IT console", agentOnly: true },
  { key: "approvals", label: "Approvals" },
  { key: "admin", label: "Administration", adminOnly: true },
];

export default function App() {
  const [me, setMe] = useState(null);
  const [loading, setLoading] = useState(true);
  const [view, setView] = useState("mine");
  const [detailId, setDetailId] = useState(null);

  useEffect(() => {
    // Metadata is returned after server verification of the HttpOnly cookie.
    // Remove legacy URL credentials without reading them into JS or storage.
    const url = new URL(window.location.href);
    url.searchParams.delete("mmos_token");
    history.replaceState(null, "", url.pathname + url.search);
    let active = true;
    api.session().then(user => { if (active) setMe(user); })
      .catch(() => { if (active) setMe(null); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, []);

  if (loading) return <main><p>Loading your session…</p></main>;
  if (!me) return <DevSignIn onSignedIn={() => setMe(decodeClaims(getToken()))} />;

  const roles = me.roles || [];
  const permissions = me.permissions;
  const isAgent = permissions ? permissions.includes("queue.read") : roles.includes("agent") || roles.includes("admin");
  const isAdmin = permissions ? permissions.includes("service.admin") : roles.includes("admin");
  const initials = (me.emp || me.name || "?").slice(0, 2).toUpperCase();

  function openTicket(id) {
    setDetailId(id);
    setView("detail");
  }
  async function signOut() {
    try { await api.logout(); } finally { clearToken(); setMe(null); }
  }

  return (
    <>
      <header className="topbar">
        <span className="brand cond">SERVICE DESK</span>
        <nav>
          {NAV.filter((n) => (!n.agentOnly || isAgent) && (!n.adminOnly || isAdmin)).map((n) => (
            <button key={n.key} className={view === n.key ? "active" : ""} onClick={() => setView(n.key)}>
              {n.label}
            </button>
          ))}
        </nav>
        <button className="btn" onClick={signOut} title={me.name}>Sign out</button>
        <span className="avatar" title={`${me.name} — ${me.dept}`}>{initials}</span>
      </header>

      {view === "mine" && <MyRequests onOpen={openTicket} onNew={() => setView("new")} />}
      {view === "dept" && <DepartmentQueue onOpen={openTicket} />}
      {view === "queue" && isAgent && <AgentConsole onOpen={openTicket} />}
      {view === "approvals" && <ApproverDecisions onOpen={openTicket} />}
      {view === "admin" && isAdmin && <Administration />}
      {view === "new" && <RequestForm onCreated={openTicket} onCancel={() => setView("mine")} />}
      {view === "detail" && (
        <TicketDetail ticketId={detailId} me={me} onBack={() => setView("mine")} />
      )}
    </>
  );
}
