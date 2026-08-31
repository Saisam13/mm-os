// The one interface both the real client (client.ts) and the dev fixture
// (mock.ts) implement, so every page codes against this and never against
// which one is active. See index.ts for the switch.
import type {
  AccountBulkResult, AccountCreateResult, AccountRosterRow,
  AdminEmployee, AdminGrant, AdminLlmRow, AdminService, AdminRole,
  AuditEntry, FunctionalAccount, Me, PublicService, ServiceToken,
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
    updateEmployee(id: string, patch: Partial<AdminEmployee>): Promise<AdminEmployee>
    setUserActive(userId: string, isActive: boolean): Promise<void>
    setPin(userId: string, pin: string | null): Promise<void>

    // functional-mailbox accounts ("add & customize")
    listAccounts(dept?: string): Promise<FunctionalAccount[]>
    createAccount(payload: {
      email: string; department: string; role?: string
      approval_level?: string | null; platform_admin?: boolean; employee_code?: string
      active?: boolean
    }): Promise<AccountCreateResult>
    bulkAccounts(rows: AccountRosterRow[], dryRun: boolean, active?: boolean): Promise<AccountBulkResult>
    resetAccountPin(id: string): Promise<string>
    updateAccount(id: string, patch: {
      approval_level?: string | null; platform_admin?: boolean; is_active?: boolean
      department?: string; label?: string
    }): Promise<FunctionalAccount>

    listServices(): Promise<AdminService[]>
    createService(payload: Partial<AdminService>): Promise<AdminService>
    updateService(slug: string, patch: Partial<AdminService>): Promise<AdminService>
    addServiceRole(slug: string, role: { key: string; name: string; description?: string }): Promise<AdminRole>
    rotateServiceKey(slug: string): Promise<string>

    listGrants(f: GrantFilter): Promise<AdminGrant[]>
    createGrant(payload: { user_id: string; slug: string; role: string; reason: string; expires_at?: string | null }): Promise<AdminGrant>
    deleteGrant(id: string): Promise<void>
    bulkGrant(payload: { slug: string; role: string; band?: string[]; department?: string[] }): Promise<{ count: number }>

    listLlm(): Promise<AdminLlmRow[]>
    toggleLlm(slug: string, enabled: boolean, reason: string): Promise<void>

    listAudit(f: AuditFilter): Promise<AuditEntry[]>
  }
}
