// Thin fetch wrapper. Auth is a bearer token, held in localStorage until the real MM OS
// handoff (packages/mmos-client-py + embed.js) exists — see `## Assumptions` in the handoff
// and DevSignIn.jsx, which is the stand-in for "click a tile in MM OS and arrive signed in."
const TOKEN_KEY = "sd_token";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

// Peeks at the claims of either a real three-part RS256 JWT or this repo's two-part stub
// token (app/mmos_seam.py) — display only, never a substitute for server-side verification.
export function decodeClaims(token) {
  if (!token) return null;
  const parts = token.split(".");
  const body = parts.length >= 3 ? parts[1] : parts[0];
  try {
    return JSON.parse(atob(body.replace(/-/g, "+").replace(/_/g, "/")));
  } catch {
    return null;
  }
}

async function request(path, { method = "GET", body, params } = {}) {
  const url = new URL(path, window.location.origin);
  if (params) Object.entries(params).forEach(([k, v]) => v != null && url.searchParams.set(k, v));
  const token = getToken();
  const res = await fetch(url, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const isJson = res.headers.get("content-type")?.includes("application/json");
  const data = isJson ? await res.json() : null;
  if (!res.ok) {
    const err = new Error(data?.detail?.error || `request_failed_${res.status}`);
    err.status = res.status;
    err.detail = data?.detail;
    throw err;
  }
  return data;
}

export const api = {
  listMine: () => request("/api/tickets/mine"),
  listDepartment: () => request("/api/tickets/department"),
  listQueue: () => request("/api/tickets/queue"),
  listApprovals: () => request("/api/tickets/approvals"),
  getTicket: (id) => request(`/api/tickets/${id}`),
  createTicket: (body) => request("/api/tickets", { method: "POST", body }),
  transition: (id, to_status, detail) => request(`/api/tickets/${id}/transition`, { method: "POST", body: { to_status, detail } }),
  assign: (id, assignee_sub) => request(`/api/tickets/${id}/assign`, { method: "POST", body: { assignee_sub } }),
  listComments: (id) => request(`/api/tickets/${id}/comments`),
  createComment: (id, bodyText, is_internal) => request(`/api/tickets/${id}/comments`, { method: "POST", body: { body: bodyText, is_internal } }),
  listProposals: (id) => request(`/api/tickets/${id}/proposals`),
  createProposal: (id, body) => request(`/api/tickets/${id}/proposals`, { method: "POST", body }),
  listDecisions: (id) => request(`/api/tickets/${id}/decisions`),
  listEvents: (id) => request(`/api/tickets/${id}/events`),
  decide: (id, decision, comment) => request(`/api/tickets/${id}/decisions`, { method: "POST", body: { decision, comment } }),
  getBadge: (sub) => request("/api/badge", { params: { sub } }),

  // Administration page — every one of these needs Service Desk's own `admin` role.
  listDepartments: () => request("/api/admin/departments"),
  createDepartment: (body) => request("/api/admin/departments", { method: "POST", body }),
  updateDepartment: (id, body) => request(`/api/admin/departments/${id}`, { method: "PATCH", body }),

  listPeople: () => request("/api/admin/people"),
  listRoles: () => request("/api/admin/roles"),
  upsertRole: (sub, body) => request(`/api/admin/roles/${encodeURIComponent(sub)}`, { method: "PUT", body }),
  deleteRole: (sub) => request(`/api/admin/roles/${encodeURIComponent(sub)}`, { method: "DELETE" }),

  listSla: () => request("/api/admin/sla"),
  upsertSla: (body) => request("/api/admin/sla", { method: "PUT", body }),

  listApprovalRules: () => request("/api/admin/approval-rules"),
  createApprovalRule: (body) => request("/api/admin/approval-rules", { method: "POST", body }),
  updateApprovalRule: (id, body) => request(`/api/admin/approval-rules/${id}`, { method: "PATCH", body }),
  deleteApprovalRule: (id) => request(`/api/admin/approval-rules/${id}`, { method: "DELETE" }),
  getApprovalDefault: () => request("/api/admin/approval-default"),
  setApprovalDefault: (body) => request("/api/admin/approval-default", { method: "PUT", body }),
  previewRouting: (body) => request("/api/admin/approval-preview", { method: "POST", body }),
};
