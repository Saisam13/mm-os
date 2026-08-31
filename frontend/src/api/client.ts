// Real client — talks to the documented API (docs/03-api-contract.md).
// Session auth is the mmos_session HttpOnly cookie; every call sends
// credentials so the browser attaches it. Never reachable unless
// VITE_USE_MOCK is unset/false — see index.ts.
import type { MmosApi } from './contract'
import { ApiRequestError } from './types'

const BASE = import.meta.env.VITE_API_BASE || ''

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    credentials: 'include',
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  })
  if (!res.ok) {
    let body
    try {
      body = await res.json()
    } catch {
      body = { error: 'unknown', message: res.statusText, request_id: '' }
    }
    // docs/03-api-contract.md documents a flat {error, message, request_id}
    // error body, but backend/app/deps.py (frozen, not ours to edit) raises
    // HTTPException(detail={...}), which FastAPI wraps as {"detail": {...}}.
    // Unwrap it here so this client works whether or not B1 has added the
    // app-wide flattening handler yet — see handoff/a3-shell.md "Contract
    // objections".
    if (body && typeof body === 'object' && 'detail' in body) {
      body = typeof body.detail === 'object' && body.detail !== null
        ? body.detail
        : { error: 'unknown', message: String(body.detail ?? res.statusText), request_id: '' }
    }
    if (!body || typeof body.message !== 'string') {
      body = { error: body?.error ?? 'unknown', message: res.statusText, request_id: body?.request_id ?? '' }
    }
    throw new ApiRequestError(res.status, body)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

function qs(params: object): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '') p.set(k, String(v))
  }
  const s = p.toString()
  return s ? `?${s}` : ''
}

// The real admin routers (backend/app/routers/{people,platform}.py) wrap their list
// responses ({"employees":[...]}, {"services":[...]}, {"grants":[...]}, etc.) and keep
// employees/users as two separate collections — reasonable on the backend (a User doesn't
// exist without an Employee, but not vice versa) but not the shape this client's callers
// were built against (see handoff/a3-shell.md "Contract objections" #3). B1 reconciles
// that here, in the one place that already knows both shapes, rather than touching every
// page component. See handoff/b1-assembly.md "Seams fixed".
const PAGE_ALL = 200 // matches docs/03's own pagination max; the whole company is ~74 people

export const client: MmosApi = {
  getPublicServices: () => req('/api/public/services').then((r: any) => r.services),
  googleStartUrl: (next) => `${BASE}/api/auth/google/start?next=${encodeURIComponent(next)}`,
  signInWithPin: (employee_code, pin) =>
    req('/api/auth/pin', { method: 'POST', body: JSON.stringify({ employee_code, pin }) }),
  logout: () => req('/api/auth/logout', { method: 'POST' }),
  getMe: () => req('/api/me'),
  mintServiceToken: (slug) =>
    req('/api/token/service', { method: 'POST', body: JSON.stringify({ slug }) }),

  admin: {
    listEmployees: async (f) => {
      const [emp, users] = await Promise.all([
        req<{ employees: any[]; next_cursor: string | null }>(
          `/api/admin/employees${qs({ ...f, limit: PAGE_ALL })}`,
        ),
        req<{ users: any[] }>(`/api/admin/users${qs({ limit: PAGE_ALL })}`),
      ])
      const userByEmployeeId = new Map(users.users.map((u) => [u.employee_id, u]))
      return emp.employees.map((e) => {
        const u = userByEmployeeId.get(e.id)
        return {
          ...e,
          user_id: u?.id ?? null,
          auth_type: u?.auth_type ?? null,
          is_active: u?.is_active ?? null,
          is_platform_admin: u?.is_platform_admin ?? null,
          last_login_at: u?.last_login_at ?? null,
        }
      })
    },
    updateEmployee: (id, patch) =>
      req(`/api/admin/employees/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
    setUserActive: (userId, isActive) =>
      req(`/api/admin/users/${userId}`, { method: 'PATCH', body: JSON.stringify({ is_active: isActive }) }),
    setPin: (userId, pin) =>
      req(`/api/admin/users/${userId}/pin`, {
        method: 'POST',
        body: JSON.stringify(pin === null ? { clear: true } : { pin }),
      }),

    listAccounts: (dept) =>
      req<{ accounts: any[] }>(`/api/admin/accounts${qs({ dept })}`).then((r) => r.accounts),
    createAccount: (payload) =>
      req('/api/admin/accounts', { method: 'POST', body: JSON.stringify(payload) }),
    bulkAccounts: (rows, dryRun, active) =>
      req('/api/admin/accounts/bulk', { method: 'POST', body: JSON.stringify({ rows, dry_run: dryRun, ...(active !== undefined ? { active } : {}) }) }),
    resetAccountPin: (id) =>
      req<{ pin: string }>(`/api/admin/accounts/${id}/reset-pin`, { method: 'POST' }).then((r) => r.pin),
    updateAccount: (id, patch) =>
      req(`/api/admin/accounts/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),

    listServices: () => req<{ services: any[] }>('/api/admin/services').then((r) => r.services),
    createService: (payload) => req('/api/admin/services', { method: 'POST', body: JSON.stringify(payload) }),
    updateService: (slug, patch) =>
      req(`/api/admin/services/${slug}`, { method: 'PATCH', body: JSON.stringify(patch) }),
    addServiceRole: (slug, role) =>
      req(`/api/admin/services/${slug}/roles`, { method: 'POST', body: JSON.stringify(role) }),
    rotateServiceKey: (slug) =>
      req(`/api/admin/services/${slug}/rotate-key`, { method: 'POST' }).then((r: any) => r.service_key),

    listGrants: (f) => req<{ grants: any[] }>(`/api/admin/grants${qs(f)}`).then((r) => r.grants),
    createGrant: (payload) => req('/api/admin/grants', { method: 'POST', body: JSON.stringify(payload) }),
    deleteGrant: (id) => req(`/api/admin/grants/${id}`, { method: 'DELETE' }),
    bulkGrant: (payload) =>
      req<{ created: number; skipped: number }>('/api/admin/grants/bulk', {
        method: 'POST',
        body: JSON.stringify(payload),
      }).then((r) => ({ count: r.created })),

    listLlm: () => req<{ registrations: any[] }>('/api/admin/llm').then((r) => r.registrations),
    toggleLlm: (slug, enabled, reason) =>
      req(`/api/admin/llm/${slug}/toggle`, { method: 'POST', body: JSON.stringify({ enabled, reason }) }),

    listAudit: (f) =>
      req<{ entries: any[]; next_cursor: string | null }>(`/api/admin/audit${qs(f)}`).then((r) => r.entries),
  },
}
