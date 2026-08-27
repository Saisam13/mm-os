// Thin fetch wrapper. Auth is a bearer token, held in localStorage until the real MM OS
// handoff (embed.js + /_mmos/accept#token=...) lands — see DevSignIn.jsx, the stand-in for
// "click a tile in MM OS and arrive signed in." Mirrors servicedesk/frontend/src/api.js.
const TOKEN_KEY = "ic_token";

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
};
