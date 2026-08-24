import { useEffect, useState } from "react";
import { decodeClaims, getToken, clearToken } from "./api.js";
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
  const [token, setTokenState] = useState(getToken());
  const [view, setView] = useState("mine");
  const [detailId, setDetailId] = useState(null);

  useEffect(() => {
    // /_mmos/accept handshake would normally arrive here already signed in — nothing to do
    // once a token is in localStorage (see DevSignIn.jsx and `## Assumptions`).
  }, []);

  if (!token) {
    return <DevSignIn onSignedIn={() => setTokenState(getToken())} />;
  }

  const me = decodeClaims(token) || {};
  const roles = me.roles || [];
  const isAgent = roles.includes("agent") || roles.includes("admin") || me.platform_admin;
  const isAdmin = roles.includes("admin");
  const initials = (me.emp || me.name || "?").slice(0, 2).toUpperCase();

  function openTicket(id) {
    setDetailId(id);
    setView("detail");
  }
  function signOut() {
    clearToken();
    setTokenState(null);
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
