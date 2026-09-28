// The one interface both the real client (client.ts) and the dev fixture
// (mock.ts) implement, so every page codes against this and never against
// which one is active. See index.ts for the switch.
import type {
  AdminEmployee, AdminGrant, AdminLlmRow, AdminService, AdminRole,
  AuditEntry, Me, PublicService, ServiceToken,
  AdminAgent, AdminDepartment, CapabilityAssignment,
} from './types'

export interface EmployeeFilter { q?: string; dept?: string; status?: string }
export interface GrantFilter { service?: string; user?: string }
export interface AuditFilter { action?: string; actor?: string; from?: string; to?: string; limit?: number }

export interface MmosApi {
  getPublicServices(): Promise<PublicService[]>
  googleStartUrl(next: string): string
  signInWithPin(employee_code: string, pin: string): Promise<void>
  logout(): Promise<void>
  getMe(): Promise<Me>
  mintServiceToken(slug: string): Promise<ServiceToken>

  admin: {
    listEmployees(f: EmployeeFilter): Promise<AdminEmployee[]>
    listDepartments(): Promise<AdminDepartment[]>
    createDepartment(payload: { name: string; key: string }): Promise<AdminDepartment>
    updateDepartment(id: string, patch: Partial<AdminDepartment>): Promise<AdminDepartment>
    createPerson(payload: Record<string, unknown>): Promise<{ employee: AdminEmployee; grants_created: number }>
    updateEmployee(id: string, patch: Partial<AdminEmployee>): Promise<AdminEmployee>
    setUserActive(userId: string, isActive: boolean): Promise<void>
    setPin(userId: string, pin: string | null): Promise<void>

    listServices(): Promise<AdminService[]>
    createService(payload: Partial<AdminService>): Promise<AdminService>
    updateService(slug: string, patch: Partial<AdminService>): Promise<AdminService>
    addServiceRole(slug: string, role: { key: string; name: string; description?: string }): Promise<AdminRole>
    rotateServiceKey(slug: string): Promise<string>

    listGrants(f: GrantFilter): Promise<AdminGrant[]>
    createGrant(payload: { user_id: string; slug: string; role: string; reason: string; expires_at?: string | null }): Promise<AdminGrant>
    deleteGrant(id: string): Promise<void>
    batchGrants(payload: { user_id: string; services: Array<{ service_slug: string; roles: string[]; replace?: boolean }>; reason?: string }): Promise<{ created: number; revoked: number; grants: AdminGrant[] }>
    bulkGrant(payload: { slug: string; role: string; band?: string[]; department?: string[]; preview?: boolean }): Promise<{ count: number; preview?: boolean }>

    listLlm(): Promise<AdminLlmRow[]>
    toggleLlm(slug: string, enabled: boolean, reason: string): Promise<void>

    listAudit(f: AuditFilter): Promise<AuditEntry[]>
    listAgents(): Promise<AdminAgent[]>
    createAgent(payload: { name: string; slug: string; kind: AdminAgent['kind']; service_id?: string | null }): Promise<AdminAgent>
    listCapabilities(): Promise<{ available: string[]; assignments: CapabilityAssignment[] }>
    grantCapability(userId: string, capability: string, scope_department_id?: string | null): Promise<void>
    revokeCapability(id: string): Promise<void>
  }
}
