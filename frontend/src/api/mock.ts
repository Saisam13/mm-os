// DEV-ONLY FIXTURE. Never imported when import.meta.env.PROD is true — see
// index.ts, which is the one place that decides. A1/A2 are building the real
// API in parallel; this returns exactly the shapes in docs/03-api-contract.md
// (cross-checked against backend/app/models.py) so pages can be built and
// demoed before a server exists.
//
// Three personas simulate the acceptance criteria without a backend:
//   ?as=prashanth  (default) — 2 grants, not admin. "sees exactly two tiles."
//   ?as=empty                — 0 grants, not admin. "sees the empty state."
//   ?as=admin                — platform admin, full admin console reachable.
// The choice persists in localStorage so it survives navigation and reloads.
import type { MmosApi } from './contract'
import type {
  AccountBulkResult, AccountCreateResult, AccountRosterRow,
  AdminEmployee, AdminGrant, AdminLlmRow, AdminService, FunctionalAccount, Me, PublicService,
} from './types'
import { ApiRequestError } from './types'

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms))

// ── persona selection ────────────────────────────────────────────────────
type Persona = 'prashanth' | 'empty' | 'admin'

function readPersona(): Persona {
  if (typeof window === 'undefined') return 'prashanth'
  const fromQuery = new URLSearchParams(window.location.search).get('as')
  if (fromQuery === 'prashanth' || fromQuery === 'empty' || fromQuery === 'admin') {
    window.localStorage.setItem('mmos_mock_persona', fromQuery)
    return fromQuery
  }
  const stored = window.localStorage.getItem('mmos_mock_persona')
  if (stored === 'prashanth' || stored === 'empty' || stored === 'admin') return stored
  return 'prashanth'
}

let signedOut = typeof window !== 'undefined' && window.localStorage.getItem('mmos_mock_signed_out') === '1'

// ── service registry (shared by public list, admin registry, /api/me) ────
const REGISTRY: AdminService[] = [
  {
    id: 'svc-erpnext', slug: 'erpnext', name: 'ERPNext', tagline: 'Purchase, stock, accounts',
    category: 'erp', base_url: 'https://minimines-uat.m.frappe.cloud', icon: 'database',
    launch_mode: 'external', has_public_surface: false, public_url: null,
    is_active: true, sort_order: 10,
    roles: [
      { id: 'r1', key: 'user', name: 'User', description: 'Create and submit documents in your own department. Cannot approve.', is_default: true },
      { id: 'r2', key: 'manager', name: 'Manager', description: 'Approve documents up to your band limit, and view every department.', is_default: false },
    ],
  },
  {
    id: 'svc-itemcode', slug: 'itemcode', name: 'Item Code Studio', tagline: 'Build and look up item codes',
    category: 'production', base_url: 'https://itemcode.m-mines.com', icon: 'hash',
    launch_mode: 'handoff', has_public_surface: true, public_url: 'https://itemcode.m-mines.com/lookup',
    is_active: true, sort_order: 20,
    roles: [
      { id: 'r3', key: 'viewer', name: 'Viewer', description: 'Look up any item code and read the naming standard. No changes.', is_default: true },
      { id: 'r4', key: 'admin', name: 'Administrator', description: 'Create and edit item codes. Changes are logged against your employee code.', is_default: false },
    ],
  },
  {
    id: 'svc-att', slug: 'att', name: 'ATT Platform', tagline: 'Battery portfolio scoring',
    category: 'production', base_url: 'https://att.m-mines.com', icon: 'activity',
    launch_mode: 'handoff', has_public_surface: false, public_url: null,
    is_active: true, sort_order: 30,
    roles: [
      { id: 'r5', key: 'viewer', name: 'Viewer', description: 'Read portfolios, scores and regulatory logs. Cannot start a run.', is_default: true },
      { id: 'r6', key: 'runner', name: 'Runner', description: 'Start scoring runs, upload portfolios and change matcher settings.', is_default: false },
    ],
  },
  {
    id: 'svc-desk', slug: 'desk', name: 'Service Desk', tagline: 'Support and automation requests',
    category: 'operations', base_url: 'https://desk.m-mines.com', icon: 'inbox',
    launch_mode: 'handoff', has_public_surface: false, public_url: null,
    is_active: true, sort_order: 40,
    roles: [
      { id: 'r7', key: 'requester', name: 'Requester', description: 'Raise requests, comment on your own, and track them.', is_default: true },
      { id: 'r8', key: 'agent', name: 'Agent', description: 'Triage anything, assign, write proposals, resolve.', is_default: false },
      { id: 'r9', key: 'admin', name: 'Administrator', description: 'Categories, reassignment, reopen closed requests.', is_default: false },
    ],
  },
  {
    id: 'svc-twenty', slug: 'twenty', name: 'Twenty CRM', tagline: 'Leads and opportunities',
    category: 'crm', base_url: 'https://crm.m-mines.com', icon: 'users',
    launch_mode: 'external', has_public_surface: false, public_url: null,
    is_active: true, sort_order: 50,
    roles: [{ id: 'r10', key: 'user', name: 'User', description: 'Read and edit leads and opportunities you own.', is_default: true }],
  },
  {
    id: 'svc-analytics', slug: 'analytics', name: 'Analytics Hub', tagline: 'Sales and project analytics',
    category: 'analytics', base_url: 'https://analytics.m-mines.com', icon: 'bar-chart',
    launch_mode: 'handoff', has_public_surface: false, public_url: null,
    is_active: true, sort_order: 60,
    roles: [{ id: 'r11', key: 'viewer', name: 'Viewer', description: 'Read dashboards. No export.', is_default: true }],
  },
]

const THIRD_PARTY = new Set(['erpnext', 'twenty'])

// ── employees / users ────────────────────────────────────────────────────
const EMPLOYEES: AdminEmployee[] = [
  { id: 'e-01', employee_code: 'MM01', full_name: 'Anupam Kumar', work_email: 'anupam@m-mines.com', hr_department: 'CXO Office', division: 'Corporate', job_title: 'CEO', band: 'L5', approval_level: 'L5 (Executive)', is_approver: true, notes: null, status: 'active', user_id: 'u-01', auth_type: 'google', is_active: true, is_platform_admin: false, last_login_at: '2026-08-23T09:10:00Z' },
  { id: 'e-05', employee_code: 'MM05', full_name: 'Mandaleshvar Sharma', work_email: 'mandaleshvar@m-mines.com', hr_department: 'P-Spoke', division: 'Operations', job_title: 'Plant Head', band: 'L4', approval_level: 'L4 (Head)', is_approver: true, notes: null, status: 'active', user_id: 'u-05', auth_type: 'google', is_active: true, is_platform_admin: false, last_login_at: '2026-08-22T14:02:00Z' },
  { id: 'e-23', employee_code: 'MM23', full_name: 'Vaibhav Kulkarni', work_email: 'vaibhav@m-mines.com', hr_department: 'Project', division: 'Operations', job_title: 'IT Lead', band: 'L3', approval_level: 'L3 (Lead)', is_approver: true, notes: null, status: 'active', user_id: 'u-23', auth_type: 'google', is_active: true, is_platform_admin: true, last_login_at: '2026-08-24T07:40:00Z' },
  { id: 'e-32', employee_code: 'MM32', full_name: 'Prashanth V', work_email: 'prashanth@m-mines.com', hr_department: 'Purchase', division: 'Finance', job_title: 'Purchase Associate', band: 'L1S', approval_level: 'L1 (Associate)', is_approver: false, notes: null, status: 'active', user_id: 'u-32', auth_type: 'google', is_active: true, is_platform_admin: false, last_login_at: '2026-08-24T08:15:00Z' },
  { id: 'e-09', employee_code: 'MM09', full_name: 'Rajesh Kumar', work_email: 'rajesh@m-mines.com', hr_department: 'QA/QC', division: 'Operations', job_title: 'QA Engineer', band: 'L2', approval_level: null, is_approver: false, notes: null, status: 'active', user_id: 'u-09', auth_type: 'google', is_active: true, is_platform_admin: false, last_login_at: '2026-08-21T11:00:00Z' },
  { id: 'e-19', employee_code: 'MM19', full_name: 'Deepak Dixit', work_email: null, hr_department: 'P-Spoke', division: 'Operations', job_title: 'Shift Supervisor', band: 'L1S', approval_level: null, is_approver: false, notes: null, status: 'active', user_id: 'u-19', auth_type: 'local_pin', is_active: true, is_platform_admin: false, last_login_at: '2026-08-20T06:30:00Z' },
  { id: 'e-30', employee_code: 'MM30', full_name: 'Ashwini Kulkarni', work_email: 'ashwini@m-mines.com', hr_department: 'Projects', division: 'Operations', job_title: 'Project Associate', band: 'L2', approval_level: null, is_approver: false, notes: null, status: 'active', user_id: 'u-30', auth_type: 'google', is_active: true, is_platform_admin: false, last_login_at: '2026-08-19T10:00:00Z' },
  { id: 'e-40', employee_code: 'MM40', full_name: 'Simbu Rabadia', work_email: null, hr_department: 'P-Spoke', division: 'Operations', job_title: 'Weighbridge Operator', band: 'L1', approval_level: null, is_approver: false, notes: 'Exited 15 Aug 2026', status: 'exited', user_id: 'u-40', auth_type: 'local_pin', is_active: false, is_platform_admin: false, last_login_at: '2026-08-10T08:00:00Z' },
]

// user_id -> { slug: role key }
const GRANTS_BY_USER: Record<string, Record<string, string>> = {
  'u-01': { erpnext: 'manager', itemcode: 'viewer', att: 'viewer', desk: 'admin', twenty: 'user' },
  'u-05': { erpnext: 'manager', itemcode: 'admin', att: 'viewer', desk: 'requester' },
  'u-23': { erpnext: 'user', itemcode: 'admin', att: 'runner', desk: 'agent', twenty: 'user' },
  'u-32': { erpnext: 'user', itemcode: 'viewer' },
  'u-09': { erpnext: 'user', itemcode: 'viewer', att: 'runner', desk: 'requester' },
  'u-19': { itemcode: 'viewer', desk: 'requester' },
  'u-30': { twenty: 'user' },
}

const EXPIRES: Record<string, string> = { 'u-32:itemcode': '2026-09-30T00:00:00Z' }

// ── functional-mailbox accounts (dev fixture) ────────────────────────────
// Seeded with two so the Accounts page isn't empty in the mock; mutated in
// place by createAccount / bulkAccounts / updateAccount so a demo can add and
// customize accounts without a backend.
let ACCOUNT_SEQ = 1
const FUNCTIONAL_ACCOUNTS: FunctionalAccount[] = [
  { id: 'fa-1', employee_id: 'fe-1', employee_code: 'PURCHASE.C2', email: 'purchase.c2@m-mines.com', label: 'Purchase C2', department: 'Purchase', approval_level: null, is_platform_admin: false, auth_type: 'google', is_active: true, pin_set: true, must_change_pin: false },
  { id: 'fa-2', employee_id: 'fe-2', employee_code: 'CENTRAL.STORES', email: 'central.stores@m-mines.com', label: 'Central Stores', department: 'Central Stores', approval_level: 'L3 (HOD)', is_platform_admin: true, auth_type: 'google', is_active: true, pin_set: true, must_change_pin: false },
]

function mockLabelFromEmail(email: string): string {
  const local = email.split('@')[0]
  const words = local.replace(/[._-]/g, ' ').split(' ').filter(Boolean)
  return words.map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ') || local
}

function mockPin(): string {
  return String(Math.floor(Math.random() * 1_000_000)).padStart(6, '0')
}

function upsertAccount(row: {
  email: string; department: string; role?: string; approval_level?: string | null
  platform_admin?: boolean; employee_code?: string; active?: boolean
}, commit: boolean): { account: FunctionalAccount; created: boolean; pin: string | null; employee_action: string; user_action: string } {
  const existing = FUNCTIONAL_ACCOUNTS.find((a) => a.email === row.email || (row.employee_code && a.employee_code === row.employee_code))
  if (existing) {
    const label = mockLabelFromEmail(row.email)
    const changed = existing.department !== row.department || existing.label !== label ||
      (!!row.approval_level && existing.approval_level !== row.approval_level)
    if (commit) {
      existing.department = row.department
      existing.label = label
      if (row.approval_level) existing.approval_level = row.approval_level
      if (row.platform_admin) { existing.is_platform_admin = true; existing.auth_type = 'google' }
      // `active` is a create-only setting -- an already-existing account's is_active is
      // never touched here, so re-importing the same row can never silently disable an
      // account the admin has since enabled (mirrors app/provision.py's contract).
    }
    return { account: existing, created: false, pin: null, employee_action: changed ? (commit ? 'updated' : 'would_update') : 'unchanged', user_action: 'pin_kept' }
  }
  const code = row.employee_code || row.email.split('@')[0].toUpperCase().slice(0, 16)
  const acct: FunctionalAccount = {
    id: `fa-${++ACCOUNT_SEQ}`, employee_id: `fe-${ACCOUNT_SEQ}`, employee_code: code,
    email: row.email, label: mockLabelFromEmail(row.email), department: row.department,
    approval_level: row.approval_level || null, is_platform_admin: !!row.platform_admin,
    auth_type: 'google', is_active: !!row.active, pin_set: true, must_change_pin: true,
  }
  const pin = commit ? mockPin() : null
  if (commit) FUNCTIONAL_ACCOUNTS.push(acct)
  return { account: acct, created: true, pin, employee_action: commit ? 'created' : 'would_create', user_action: commit ? 'created' : 'would_create' }
}

function grantsFor(userId: string): AdminGrant[] {
  const g = GRANTS_BY_USER[userId] || {}
  const emp = EMPLOYEES.find((e) => e.user_id === userId)!
  return Object.entries(g).map(([slug, role], i) => {
    const svc = REGISTRY.find((s) => s.slug === slug)!
    const roleObj = svc.roles.find((r) => r.key === role)!
    return {
      id: `grant-${userId}-${slug}`,
      user: { id: userId, name: emp.full_name, employee_code: emp.employee_code },
      service: { slug: svc.slug, name: svc.name },
      role: { key: roleObj.key, name: roleObj.name },
      granted_by: i === 0 ? null : { id: 'u-23', name: 'Vaibhav Kulkarni' },
      reason: i === 0 ? 'Imported from role sheet' : 'Requested via Service Desk',
      expires_at: EXPIRES[`${userId}:${slug}`] || null,
      created_at: '2026-07-14T09:00:00Z',
    }
  })
}

// ── LLM control plane ────────────────────────────────────────────────────
function spark(base: number, trend: number[]): AdminLlmRow['usage_30d'] {
  return trend.map((v, i) => ({
    day: `2026-08-${String(i + 1).padStart(2, '0')}`,
    requests: Math.round(base * v),
    input_tokens: Math.round(base * v * 900),
    output_tokens: Math.round(base * v * 140),
  }))
}

const LLM: AdminLlmRow[] = [
  { slug: 'att', name: 'ATT Platform', provider: 'anthropic', model: 'claude-opus-5', key_present: true, enabled: true, last_seen_at: '2026-08-24T08:20:00Z', usage_30d: spark(40, [0.7, 0.75, 0.8, 0.9, 1, 1.1, 1.2]) },
  { slug: 'itemcode', name: 'Item Code Studio', provider: 'anthropic', model: 'claude-sonnet-5', key_present: true, enabled: true, last_seen_at: '2026-08-24T08:16:00Z', usage_30d: spark(10, [1, 1, 0.9, 1, 0.95, 1, 1]) },
  { slug: 'analytics', name: 'Analytics Hub', provider: 'anthropic', model: 'claude-opus-5', key_present: true, enabled: false, last_seen_at: '2026-08-24T08:19:00Z', usage_30d: spark(150, [0.6, 0.7, 0.8, 1, 1.3, 1.7, 2.1]) },
  { slug: 'desk', name: 'Service Desk', provider: null, model: null, key_present: false, enabled: true, last_seen_at: '2026-08-24T08:00:00Z', usage_30d: [] },
]

// ── audit ────────────────────────────────────────────────────────────────
const AUDIT = [
  { id: 'a1', actor: { id: 'u-23', name: 'Vaibhav Kulkarni' }, action: 'grant.create', target_type: 'grant', target_id: 'grant-u-32-itemcode', service: { slug: 'itemcode', name: 'Item Code Studio' }, ip: '10.8.0.24', metadata: { role: 'viewer' }, created_at: '2026-07-14T09:00:00Z' },
  { id: 'a2', actor: { id: 'u-23', name: 'Vaibhav Kulkarni' }, action: 'llm.toggle', target_type: 'service', target_id: 'analytics', service: { slug: 'analytics', name: 'Analytics Hub' }, ip: '10.8.0.24', metadata: { enabled: false, reason: 'cost spike' }, created_at: '2026-08-23T16:40:00Z' },
  { id: 'a3', actor: null, action: 'auth.pin_fail', target_type: 'user', target_id: 'u-19', service: null, ip: '10.8.0.61', metadata: { attempt: 3 }, created_at: '2026-08-20T06:29:00Z' },
  { id: 'a4', actor: { id: 'u-23', name: 'Vaibhav Kulkarni' }, action: 'token.issue', target_type: 'user', target_id: 'u-32', service: { slug: 'erpnext', name: 'ERPNext' }, ip: '10.8.0.24', metadata: {}, created_at: '2026-08-24T08:15:03Z' },
]

// ── /api/me per persona ──────────────────────────────────────────────────
function meFor(persona: Persona): Me {
  const empByPersona: Record<Persona, AdminEmployee> = {
    prashanth: EMPLOYEES.find((e) => e.employee_code === 'MM32')!,
    admin: EMPLOYEES.find((e) => e.employee_code === 'MM23')!,
    empty: { id: 'e-99', employee_code: 'MM99', full_name: 'New Hire', work_email: 'newhire@m-mines.com', hr_department: 'QA/QC', division: 'Operations', job_title: 'Associate', band: 'L1', approval_level: null, is_approver: false, notes: null, status: 'active', user_id: 'u-99', auth_type: 'google', is_active: true, is_platform_admin: false, last_login_at: null },
  }
  const emp = empByPersona[persona]
  const grants = persona === 'empty' ? [] : grantsFor(emp.user_id!)
  return {
    user: {
      id: emp.user_id!,
      name: emp.full_name,
      employee_code: emp.employee_code,
      email: emp.work_email,
      auth_type: emp.auth_type!,
      department: emp.hr_department,
      division: emp.division,
      band: emp.band,
      approval_level: emp.approval_level,
      is_platform_admin: emp.is_platform_admin!,
    },
    services: grants.map((g) => {
      const svc = REGISTRY.find((s) => s.slug === g.service.slug)!
      return {
        slug: svc.slug,
        name: svc.name,
        category: svc.category,
        role: g.role.key,
        launch_mode: svc.launch_mode,
        base_url: svc.base_url,
        icon: svc.icon,
        health: 'up' as const,
      }
    }),
    badges: { servicedesk_open: persona === 'empty' ? 0 : 2, approvals_waiting: persona === 'admin' ? 1 : 0 },
  }
}

export const mock: MmosApi = {
  async getPublicServices(): Promise<PublicService[]> {
    await delay(150)
    return REGISTRY.filter((s) => s.is_active).map((s) => ({
      slug: s.slug,
      name: s.name,
      launch_url: s.base_url,
      session_owner: THIRD_PARTY.has(s.slug) ? 'service' : 'mmos',
    }))
  },

  googleStartUrl(next) {
    return `/api/auth/google/start?next=${encodeURIComponent(next)}`
  },

  async signInWithPin(employee_code, pin) {
    await delay(300)
    const emp = EMPLOYEES.find((e) => e.employee_code === employee_code.toUpperCase())
    if (!emp || emp.auth_type !== 'local_pin') {
      throw new ApiRequestError(401, { error: 'unknown_user', message: 'No PIN account matches that employee code.', request_id: 'mock' })
    }
    if (!emp.is_active || emp.status !== 'active') {
      throw new ApiRequestError(403, { error: 'account_locked', message: 'This account has been deactivated. Contact IT.', request_id: 'mock' })
    }
    if (pin !== '1234') {
      throw new ApiRequestError(401, { error: 'wrong_pin', message: 'That PIN is not correct.', request_id: 'mock' })
    }
    signedOut = false
    window.localStorage.removeItem('mmos_mock_signed_out')
    window.localStorage.setItem('mmos_mock_persona', 'prashanth') // Deepak's persona isn't separately modeled; reuse prashanth's grant shape
  },

  async logout() {
    await delay(150)
    signedOut = true
    window.localStorage.setItem('mmos_mock_signed_out', '1')
  },

  async getMe() {
    await delay(200)
    if (signedOut) {
      throw new ApiRequestError(401, { error: 'no_session', message: 'Sign in to continue.', request_id: 'mock' })
    }
    return meFor(readPersona())
  },

  async mintServiceToken(slug) {
    await delay(500)
    const persona = readPersona()
    const me = meFor(persona)
    const svc = me.services.find((s) => s.slug === slug)
    if (!svc) {
      throw new ApiRequestError(403, { error: 'grant_not_found', message: 'You have no access to this service.', request_id: 'mock' })
    }
    // Demonstrates the "grant removed after /api/me was fetched" race: the
    // admin persona's ATT grant is simulated as revoked between page load
    // and click, so the tile shows a real error, not a crash.
    if (persona === 'admin' && slug === 'att') {
      throw new ApiRequestError(403, { error: 'grant_not_found', message: 'Your access to ATT Platform was removed.', request_id: 'mock' })
    }
    return {
      access_token: 'mock.jwt.token',
      token_type: 'Bearer',
      expires_in: 900,
      launch_url: `${svc.base_url}/_mmos/accept#token=mock.jwt.token`,
    }
  },

  admin: {
    async listEmployees(f) {
      await delay(200)
      return EMPLOYEES.filter((e) => {
        if (f.dept && e.hr_department !== f.dept) return false
        if (f.status && e.status !== f.status) return false
        if (f.q && !`${e.full_name} ${e.employee_code}`.toLowerCase().includes(f.q.toLowerCase())) return false
        return true
      })
    },
    async updateEmployee(id, patch) {
      await delay(200)
      const e = EMPLOYEES.find((x) => x.id === id)
      if (!e) throw new ApiRequestError(404, { error: 'not_found', message: 'Employee not found.', request_id: 'mock' })
      Object.assign(e, patch)
      return e
    },
    async setUserActive(userId, isActive) {
      await delay(250)
      const e = EMPLOYEES.find((x) => x.user_id === userId)
      if (e) e.is_active = isActive
    },
    async setPin() {
      await delay(200)
    },

    async listAccounts(dept) {
      await delay(200)
      return FUNCTIONAL_ACCOUNTS.filter((a) => !dept || a.department === dept).map((a) => ({ ...a }))
    },
    async createAccount(payload): Promise<AccountCreateResult> {
      await delay(250)
      const { account, created, pin } = upsertAccount(payload, true)
      return { account: { ...account }, created, pin }
    },
    async bulkAccounts(rows: AccountRosterRow[], dryRun, active): Promise<AccountBulkResult> {
      await delay(300)
      const outRows: AccountBulkResult['rows'] = []
      const pins: NonNullable<AccountBulkResult['pins']> = []
      const counts = { created: 0, updated: 0, unchanged: 0 }
      const seen = new Set<string>()
      for (const row of rows) {
        if (!row.email || seen.has(row.email)) continue
        seen.add(row.email)
        const rowActive = row.active !== undefined ? row.active : !!active
        const r = upsertAccount({ email: row.email, department: row.department, role: row.role, approval_level: row.approval_level, platform_admin: row.platform_admin, employee_code: row.employee_code, active: rowActive }, !dryRun)
        if (r.employee_action.includes('creat')) counts.created++
        else if (r.employee_action.includes('updat')) counts.updated++
        else counts.unchanged++
        outRows.push({ employee_code: r.account.employee_code, email: row.email, employee_action: r.employee_action, user_action: r.user_action, platform_admin: r.account.is_platform_admin, approval_level: r.account.approval_level, active: rowActive })
        if (r.pin) pins.push({ employee_code: r.account.employee_code, email: row.email, pin: r.pin, platform_admin: r.account.is_platform_admin })
      }
      return dryRun
        ? { dry_run: true, would_create: counts.created, would_update: counts.updated, unchanged: counts.unchanged, rows: outRows }
        : { dry_run: false, created: counts.created, updated: counts.updated, unchanged: counts.unchanged, rows: outRows, pins }
    },
    async resetAccountPin(id) {
      await delay(200)
      const a = FUNCTIONAL_ACCOUNTS.find((x) => x.id === id)
      if (a) { a.pin_set = true; a.must_change_pin = true }
      return mockPin()
    },
    async updateAccount(id, patch): Promise<FunctionalAccount> {
      await delay(200)
      const a = FUNCTIONAL_ACCOUNTS.find((x) => x.id === id)
      if (!a) throw new ApiRequestError(404, { error: 'account_not_found', message: 'Account not found.', request_id: 'mock' })
      if ('approval_level' in patch) a.approval_level = patch.approval_level ? patch.approval_level : null
      if ('platform_admin' in patch) { a.is_platform_admin = !!patch.platform_admin; if (patch.platform_admin) a.auth_type = 'google' }
      if ('is_active' in patch) a.is_active = !!patch.is_active
      if (patch.department) a.department = patch.department
      if (patch.label) a.label = patch.label
      return { ...a }
    },

    async listServices() {
      await delay(150)
      return REGISTRY
    },
    async createService(payload) {
      await delay(200)
      const svc: AdminService = {
        id: `svc-${Date.now()}`, slug: String(payload.slug), name: String(payload.name),
        tagline: payload.tagline ?? null, category: payload.category ?? 'internal',
        base_url: String(payload.base_url), icon: payload.icon ?? null,
        launch_mode: payload.launch_mode ?? 'handoff', has_public_surface: false, public_url: null,
        is_active: true, sort_order: 100, roles: [],
      }
      REGISTRY.push(svc)
      return svc
    },
    async updateService(slug, patch) {
      await delay(200)
      const s = REGISTRY.find((x) => x.slug === slug)
      if (!s) throw new ApiRequestError(404, { error: 'not_found', message: 'Service not found.', request_id: 'mock' })
      Object.assign(s, patch)
      return s
    },
    async addServiceRole(slug, role) {
      await delay(200)
      const s = REGISTRY.find((x) => x.slug === slug)
      if (!s) throw new ApiRequestError(404, { error: 'not_found', message: 'Service not found.', request_id: 'mock' })
      const r = { id: `r-${Date.now()}`, key: role.key, name: role.name, description: role.description ?? null, is_default: false }
      s.roles.push(r)
      return r
    },
    async rotateServiceKey() {
      await delay(300)
      return `mmos_sk_${Math.random().toString(36).slice(2)}${Math.random().toString(36).slice(2)}`
    },

    async listGrants(f) {
      await delay(200)
      let all = EMPLOYEES.filter((e) => e.user_id).flatMap((e) => grantsFor(e.user_id!))
      if (f.user) all = all.filter((g) => g.user.id === f.user)
      if (f.service) all = all.filter((g) => g.service.slug === f.service)
      return all
    },
    async createGrant(payload) {
      await delay(250)
      const emp = EMPLOYEES.find((e) => e.user_id === payload.user_id)
      if (!emp) throw new ApiRequestError(404, { error: 'not_found', message: 'Person not found.', request_id: 'mock' })
      GRANTS_BY_USER[payload.user_id] = { ...(GRANTS_BY_USER[payload.user_id] || {}), [payload.slug]: payload.role }
      return grantsFor(payload.user_id).find((g) => g.service.slug === payload.slug)!
    },
    async deleteGrant(id) {
      await delay(200)
      for (const [uid, g] of Object.entries(GRANTS_BY_USER)) {
        for (const slug of Object.keys(g)) {
          if (`grant-${uid}-${slug}` === id) delete g[slug]
        }
      }
    },
    async bulkGrant(payload) {
      await delay(300)
      const targets = EMPLOYEES.filter((e) =>
        (!payload.band || payload.band.includes(e.band)) &&
        (!payload.department || payload.department.includes(e.hr_department)),
      )
      for (const e of targets) {
        if (!e.user_id) continue
        GRANTS_BY_USER[e.user_id] = { ...(GRANTS_BY_USER[e.user_id] || {}), [payload.slug]: payload.role }
      }
      return { count: targets.length }
    },

    async listLlm() {
      await delay(200)
      return LLM
    },
    async toggleLlm(slug, enabled) {
      await delay(250)
      const row = LLM.find((r) => r.slug === slug)
      if (row) row.enabled = enabled
    },

    async listAudit(f) {
      await delay(200)
      return AUDIT.filter((a) => {
        if (f.action && a.action !== f.action) return false
        if (f.actor && a.actor?.id !== f.actor) return false
        return true
      }).slice(0, f.limit || 100)
    },
  },
}
