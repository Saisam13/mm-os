// Thin fetch wrapper — same shape as servicedesk/frontend/src/api.js. Auth is a bearer
// token, held in localStorage until the real MM OS handoff exists. No secret storage lives
// in this file or anywhere else in this service yet — see SECURITY.md.
const TOKEN_KEY = "pwmgr_token";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token);
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

async function request(path) {
  const token = getToken();
  const res = await fetch(path, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  const isJson = res.headers.get("content-type")?.includes("application/json");
  const data = isJson ? await res.json() : null;
  if (!res.ok) {
    const err = new Error(data?.detail?.error || `request_failed_${res.status}`);
    err.status = res.status;
    throw err;
  }
  return data;
}

export const api = {
  me: () => request("/api/me"),
  devToken: (roles) =>
    fetch("/_dev/token", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ roles: roles || ["employee"] }),
    }).then((r) => r.json()),
};
