// Shapes mirror docs/03-api-contract.md, cross-checked against the frozen
// backend/app/models.py (read-only reference) for field names the contract
// doc itself left as endpoint signatures without example bodies. Where a
// field is inferred rather than documented, it is noted inline — see
// handoff/a3-shell.md under "Assumptions" for the consolidated list.

export interface ApiError {
  error: string
  message: string
  request_id: string
}

export class ApiRequestError extends Error {
  error: string
  request_id: string
  status: number
  constructor(status: number, body: ApiError) {
    super(body.message)
    this.error = body.error
    this.request_id = body.request_id
    this.status = status
  }
}

// ── public, pre-login ────────────────────────────────────────────────────
export interface PublicService {
  slug: string
  name: string
  launch_url: string
  session_owner: 'mmos' | 'service'
}

// ── /api/me ───────────────────────────────────────────────────────────────
export interface MeUser {
  id: string
  name: string
  employee_code: string
  email: string | null
  auth_type: 'google' | 'local_pin'
  department: string
  division: string
  band: string
  approval_level: string | null
  is_platform_admin: boolean
}

export type LaunchMode = 'handoff' | 'embed' | 'external'

export interface MeService {
  slug: string
  name: string
  category: string
  role: string
  launch_mode: LaunchMode
  base_url: string
  icon: string | null
  health: 'up' | 'down' | 'build' | 'unknown'
}

export interface MeBadges {
  servicedesk_open: number
  approvals_waiting: number
}

export interface Me {
  user: MeUser
  services: MeService[]
  badges: MeBadges
}

// ── token handoff ────────────────────────────────────────────────────────
export interface ServiceToken {
  access_token: string
  token_type: 'Bearer'
  expires_in: number
  launch_url: string
}

// ── admin: employees / users (fields per backend/app/models.py Employee+User;
//    docs/03-api-contract.md gives no example body for these list endpoints) ──
export interface AdminEmployee {
  id: string
  employee_code: string
  full_name: string
  work_email: string | null
  hr_department: string
  division: string
  job_title: string
  band: string
  approval_level: string | null
  is_approver: boolean
  notes: string | null
  status: 'active' | 'suspended' | 'exited'
  // joined from users (one-to-one) for the People table
  user_id: string | null
  auth_type: 'google' | 'local_pin' | null
  is_active: boolean | null
  is_platform_admin: boolean | null
  last_login_at: string | null
}

// ── admin: services / roles ─────────────────────────────────────────────
export interface AdminRole {
  id: string
  key: string
  name: string
  description: string | null
  is_default: boolean
}

export interface AdminService {
  id: string
  slug: string
  name: string
  tagline: string | null
  category: string
  base_url: string
  icon: string | null
  launch_mode: LaunchMode
  has_public_surface: boolean
  public_url: string | null
  is_active: boolean
  sort_order: number
  roles: AdminRole[]
}

// ── admin: grants (enriched — docs/03-api-contract.md gives request/response
//    shape for mutation, not the enriched list read; nested objects assumed
//    from Grant's relationships in models.py) ───────────────────────────
export interface AdminGrant {
  id: string
  user: { id: string; name: string; employee_code: string }
  service: { slug: string; name: string }
  role: { key: string; name: string }
  granted_by: { id: string; name: string } | null
  reason: string | null
  expires_at: string | null
  created_at: string
}

// ── admin: LLM control plane ─────────────────────────────────────────────
export interface AdminLlmUsagePoint {
  day: string
  requests: number
  input_tokens: number
  output_tokens: number
}

export interface AdminLlmRow {
  slug: string
  name: string
  provider: string | null
  model: string | null
  key_present: boolean
  enabled: boolean
  last_seen_at: string | null
  usage_30d: AdminLlmUsagePoint[]
}

// ── admin: audit ─────────────────────────────────────────────────────────
export interface AuditEntry {
  id: string
  actor: { id: string; name: string } | null
  action: string
  target_type: string | null
  target_id: string | null
  service: { slug: string; name: string } | null
  ip: string | null
  metadata: Record<string, unknown>
  created_at: string
}

export interface Paginated<T> {
  items: T[]
  next_cursor: string | null
}
