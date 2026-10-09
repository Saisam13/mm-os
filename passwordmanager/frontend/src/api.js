// Production handoff uses the HttpOnly cookie. Dev tokens stay in memory.
let devToken = null;

export function getToken() {
  return devToken;
}
export function setToken(token) {
  devToken = token;
}
export function clearToken() {
  devToken = null;
}

async function request(path) {
  const token = getToken();
  const res = await fetch(path, {
    credentials: "include",
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
