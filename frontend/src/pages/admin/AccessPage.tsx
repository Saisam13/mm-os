import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { mmosApi } from '../../api'
import type { AdminEmployee, AdminGrant, AdminService, AuditEntry } from '../../api/types'
import { Panel } from '../../components/Panel'
import { EmptyState } from '../../components/EmptyState'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { formatDate, formatDateTime } from '../../lib/format'
import { rowActivation } from '../../lib/a11y'

// The core admin screen. UI-DECISIONS.md § "Access page — four capabilities"
// requires all four: the matrix, per-person drill-down, role meanings shown
// where a grant is made, and expiry/history. The fifth thing the brief
// (agents/A3-shell.md) asks for — "pending access requests decided in place,
// fed from Service Desk" — has no endpoint in docs/03-api-contract.md; that
// gap is stated in the empty card below and recorded under
// handoff/a3-shell.md "Contract objections" rather than invented here.
export function AccessPage() {
  const [employees, setEmployees] = useState<AdminEmployee[] | null>(null)
  const [services, setServices] = useState<AdminService[] | null>(null)
  const [grants, setGrants] = useState<AdminGrant[] | null>(null)
  const [selected, setSelected] = useState<AdminEmployee | null>(null)
  const [showAddGrant, setShowAddGrant] = useState(false)
  const [showBulk, setShowBulk] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [personFilter, setPersonFilter] = useState('')
  const [departmentFilter, setDepartmentFilter] = useState('')
  const [bandFilter, setBandFilter] = useState('')
  const [serviceFilter, setServiceFilter] = useState('')

  function reload() {
    Promise.all([
      mmosApi.admin.listEmployees({}),
      mmosApi.admin.listServices(),
      mmosApi.admin.listGrants({}),
    ])
      .then(([e, s, g]) => { setEmployees(e); setServices(s); setGrants(g) })
      .catch(() => setLoadError('Could not load access data.'))
  }
  useEffect(reload, [])

  const grantsByUser = useMemo(() => {
    const map = new Map<string, AdminGrant[]>()
    for (const g of grants ?? []) {
      const list = map.get(g.user.id) ?? []
      list.push(g)
      map.set(g.user.id, list)
    }
    return map
  }, [grants])

  const departments = useMemo(() => [...new Set((employees ?? []).map((employee) => employee.hr_department))].sort(), [employees])
  const bands = useMemo(() => [...new Set((employees ?? []).map((employee) => employee.band).filter(Boolean))].sort(), [employees])
  const filteredEmployees = useMemo(() => (employees ?? []).filter((employee) => {
    const term = personFilter.trim().toLowerCase()
    if (term && !`${employee.full_name} ${employee.employee_code}`.toLowerCase().includes(term)) return false
    if (departmentFilter && employee.hr_department !== departmentFilter) return false
    if (bandFilter && employee.band !== bandFilter) return false
    if (serviceFilter && !(employee.user_id && (grantsByUser.get(employee.user_id) ?? []).some((grant) => grant.service.slug === serviceFilter))) return false
    return true
  }), [employees, personFilter, departmentFilter, bandFilter, serviceFilter, grantsByUser])

  if (loadError) return <EmptyState title={loadError} />
  if (!employees || !services || !grants) return null

  return (
    <>
      <div className="head">
        <h1>Service grants</h1>
        <div className="row-actions">
          <button className="btn-q" onClick={() => setShowBulk(true)}>Bulk grant by band</button>
          <button className="btn-act" onClick={() => setShowAddGrant(true)}>Add grant</button>
        </div>
      </div>

      <div className="card">
        <div className="card-h">
          <div><div className="eyebrow">From Service Desk · decide here</div><h2>Pending access requests</h2></div>
        </div>
        <div className="card-b">
          <EmptyState
            title="Not available yet"
            hint="docs/03-api-contract.md has no endpoint for Service Desk access requests — see the Access page's Contract objection."
          />
        </div>
      </div>

      <div className="card">
        <div className="card-h">
          <div><div className="eyebrow">{filteredEmployees.length} of {employees.length} employees</div><h2>Grants</h2></div>
        </div>
        <div className="matrix-filters">
          <div className="field"><label htmlFor="grant-person-filter">Person</label><input id="grant-person-filter" value={personFilter} onChange={(e) => setPersonFilter(e.target.value)} placeholder="Name or employee code" /></div>
          <div className="field"><label htmlFor="grant-dept-filter">Department</label><select id="grant-dept-filter" value={departmentFilter} onChange={(e) => setDepartmentFilter(e.target.value)}><option value="">All departments</option>{departments.map((department) => <option key={department}>{department}</option>)}</select></div>
          <div className="field"><label htmlFor="grant-band-filter">Band</label><select id="grant-band-filter" value={bandFilter} onChange={(e) => setBandFilter(e.target.value)}><option value="">All bands</option>{bands.map((band) => <option key={band}>{band}</option>)}</select></div>
          <div className="field"><label htmlFor="grant-service-filter">Service access</label><select id="grant-service-filter" value={serviceFilter} onChange={(e) => setServiceFilter(e.target.value)}><option value="">All services</option>{services.filter((service) => service.is_active).map((service) => <option key={service.slug} value={service.slug}>{service.name}</option>)}</select></div>
          {(personFilter || departmentFilter || bandFilter || serviceFilter) ? <button className="btn-q" onClick={() => { setPersonFilter(''); setDepartmentFilter(''); setBandFilter(''); setServiceFilter('') }}>Clear</button> : null}
        </div>
        <div className="card-b flush">
          <div className="matrix-wrap">
            <table className="matrix">
              <thead>
                <tr>
                  <th>Person</th>
                  <th>Dept</th>
                  <th>Band</th>
                  {services.map((s) => <th key={s.slug} className="rot">{s.name}</th>)}
                  <th>Expiring</th>
                </tr>
              </thead>
              <tbody>
                {filteredEmployees.map((e) => {
                  const g = e.user_id ? (grantsByUser.get(e.user_id) ?? []) : []
                  const expiring = g.find((x) => x.expires_at)
                  return (
                    <tr key={e.id} className="clickable" onClick={() => setSelected(e)} {...rowActivation(() => setSelected(e))}>
                      <td><strong>{e.full_name}</strong> <span className="muted cond">{e.employee_code}</span></td>
                      <td className="tight">{e.hr_department}</td>
                      <td className="tight cond">{e.band}</td>
                      {services.map((s) => {
                        const serviceGrants = g.filter((x) => x.service.slug === s.slug)
                        return (
                          <td key={s.slug} className="cell">
                            {serviceGrants.length ? (
                              serviceGrants.map((grant) => <span key={grant.id} className={`chip${['admin', 'agent', 'manager'].includes(grant.role.key) ? ' pet' : ''}`}>{grant.role.key}</span>)
                            ) : (
                              <span className="matrix-empty">—</span>
                            )}
                          </td>
                        )
                      })}
                      <td className="tight">
                        {expiring ? <span className="chip wn">{formatDate(expiring.expires_at)}</span> : <span className="muted">—</span>}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {selected ? (
        <PersonAccessPanel
          employee={selected}
          services={services}
          grants={selected.user_id ? (grantsByUser.get(selected.user_id) ?? []) : []}
          onClose={() => setSelected(null)}
          onChanged={reload}
        />
      ) : null}

      {showAddGrant ? (
        <AddGrantDialog
          employees={employees}
          services={services}
          onCancel={() => setShowAddGrant(false)}
          onDone={() => { setShowAddGrant(false); reload() }}
        />
      ) : null}

      {showBulk ? (
        <BulkGrantDialog services={services} onCancel={() => setShowBulk(false)} onDone={() => { setShowBulk(false); reload() }} />
      ) : null}
    </>
  )
}

function PersonAccessPanel({
  employee,
  services,
  grants,
  onClose,
  onChanged,
}: {
  employee: AdminEmployee
  services: AdminService[]
  grants: AdminGrant[]
  onClose: () => void
  onChanged: () => void
}) {
  const [audit, setAudit] = useState<AuditEntry[] | null>(null)
  const [revokeTarget, setRevokeTarget] = useState<AdminGrant | null>(null)
  const [revoking, setRevoking] = useState(false)

  useEffect(() => {
    // docs/03-api-contract.md's audit filter params are action/actor/from/to/
    // limit — there is no target filter, so per-person history is narrowed
    // client-side against a fetched page. Noted under "Contract objections".
    mmosApi.admin.listAudit({ limit: 200 }).then((entries) => {
      setAudit(entries.filter((a) => a.target_id === employee.user_id || a.target_id === employee.id))
    })
  }, [employee])

  async function doRevoke() {
    if (!revokeTarget) return
    setRevoking(true)
    try {
      await mmosApi.admin.deleteGrant(revokeTarget.id)
      setRevokeTarget(null)
      onChanged()
    } finally {
      setRevoking(false)
    }
  }

  return (
    <Panel
      open
      onClose={onClose}
      eyebrow={`${employee.employee_code} · ${employee.hr_department.toUpperCase()} · ${employee.band}`}
      title={employee.full_name}
    >
      <div className="eyebrow" style={{ marginBottom: 8 }}>{grants.length} grant{grants.length === 1 ? '' : 's'}</div>
      {grants.length === 0 ? (
        <EmptyState title="No grants" />
      ) : (
        grants.map((g) => (
          <div className="grant-row" key={g.id}>
            <span className="g">
              <span className="nm">{g.service.name}</span>
              <span className="mt">
                Granted by {g.granted_by?.name ?? 'import'} · {formatDate(g.created_at)}
                {g.expires_at ? ` · expires ${formatDate(g.expires_at)}` : ''}
              </span>
            </span>
            <span className={`chip${['admin', 'agent', 'manager'].includes(g.role.key) ? ' pet' : ''}`}>{g.role.key}</span>
            <button className="btn-q" onClick={() => setRevokeTarget(g)}>Revoke</button>
          </div>
        ))
      )}

      {grants.length > 0 ? (
        <>
          <div className="eyebrow" style={{ margin: '22px 0 4px' }}>What these roles mean</div>
          {grants.map((g) => {
            const svc = services.find((s) => s.slug === g.service.slug)
            const role = svc?.roles.find((r) => r.key === g.role.key)
            return (
              <details className="role" key={g.id}>
                <summary>What {g.role.key} permits on {g.service.name}</summary>
                <p>{role?.description || 'Role description not declared by this service.'}</p>
              </details>
            )
          })}
        </>
      ) : null}

      <div className="eyebrow" style={{ margin: '22px 0 8px' }}>History</div>
      {audit === null ? null : audit.length === 0 ? (
        <div className="muted" style={{ fontSize: 12.5 }}>No audit entries for this person yet.</div>
      ) : (
        <div className="muted" style={{ fontSize: 12.5, lineHeight: 1.7 }}>
          {audit.map((a) => (
            <div key={a.id}>{formatDateTime(a.created_at)} · {a.action}{a.service ? ` · ${a.service.name}` : ''}</div>
          ))}
        </div>
      )}

      {revokeTarget ? (
        <ConfirmDialog
          title={`Revoke ${revokeTarget.service.name}?`}
          body={`${employee.full_name} loses ${revokeTarget.role.key} access to ${revokeTarget.service.name} within 60 seconds.`}
          confirmLabel="Revoke"
          busy={revoking}
          onConfirm={doRevoke}
          onCancel={() => setRevokeTarget(null)}
        />
      ) : null}
    </Panel>
  )
}

function AddGrantDialog({
  employees,
  services,
  onCancel,
  onDone,
}: {
  employees: AdminEmployee[]
  services: AdminService[]
  onCancel: () => void
  onDone: () => void
}) {
  const grantableServices = services.filter((service) => service.is_active && service.roles.length > 0)
  const firstService = grantableServices[0]
  const [userId, setUserId] = useState('')
  const [grantRows, setGrantRows] = useState(() => firstService ? [{
    id: 0,
    serviceSlug: firstService.slug,
    roleKey: (firstService.roles.find((role) => role.is_default) ?? firstService.roles[0]).key,
  }] : [])
  const nextRowId = useRef(1)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const enrolledPeople = employees
    .filter((employee) => employee.user_id)
    .sort((a, b) => a.full_name.localeCompare(b.full_name))
  const selectedPerson = enrolledPeople.find((employee) => employee.user_id === userId)

  function updateService(rowId: number, serviceSlug: string) {
    const service = grantableServices.find((item) => item.slug === serviceSlug)!
    const role = service.roles.find((item) => item.is_default) ?? service.roles[0]
    setGrantRows((current) => current.map((row) => row.id === rowId ? { ...row, serviceSlug, roleKey: role.key } : row))
  }

  function updateRole(rowId: number, roleKey: string) {
    setGrantRows((current) => current.map((row) => row.id === rowId ? { ...row, roleKey } : row))
  }

  function addService() {
    const used = new Set(grantRows.map((row) => row.serviceSlug))
    const service = grantableServices.find((item) => !used.has(item.slug))
    if (!service) return
    const role = service.roles.find((item) => item.is_default) ?? service.roles[0]
    setGrantRows((current) => [...current, { id: nextRowId.current++, serviceSlug: service.slug, roleKey: role.key }])
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!userId || !grantRows.length || grantRows.some((row) => !row.serviceSlug || !row.roleKey)) return
    setBusy(true)
    setErr(null)
    try {
      await mmosApi.admin.batchGrants({
        user_id: userId,
        services: grantRows.map((row) => ({ service_slug: row.serviceSlug, roles: [row.roleKey] })),
        reason: 'Access assigned by administrator',
      })
      onDone()
    } catch {
      setErr('Could not create the grant.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="confirm-scrim" onClick={onCancel}>
      <div className="confirm-box grant-dialog" role="dialog" aria-modal="true" aria-labelledby="add-grant-title" onClick={(e) => e.stopPropagation()}>
        <div className="grant-dialog__header">
          <h2 id="add-grant-title">Give service access</h2>
          <button type="button" className="x" aria-label="Close" onClick={onCancel}>×</button>
        </div>
        <form className="grant-dialog__form" onSubmit={submit}>
          {err ? <div className="form-err">{err}</div> : null}
          <div className="field">
            <label htmlFor="ag-person">Employee</label>
            <select id="ag-person" value={userId} onChange={(e) => setUserId(e.target.value)} required>
              <option value="">Select a person</option>
              {enrolledPeople.map((employee) => (
                <option key={employee.id} value={employee.user_id!}>{employee.full_name} — {employee.work_email || employee.employee_code}</option>
              ))}
            </select>
            {selectedPerson ? <div className="grant-person-summary"><strong>{selectedPerson.employee_code}</strong><span>{selectedPerson.work_email || 'No enrolled email'}</span></div> : <div className="field-help">Not listed? <Link to="/admin/people">Add the person first</Link>.</div>}
          </div>
          <div className="field grant-dialog__service-field">
            <label>Service access</label>
            <div className="grant-builder">
              {grantRows.map((row, index) => {
                const service = grantableServices.find((item) => item.slug === row.serviceSlug)
                const usedByOthers = new Set(grantRows.filter((item) => item.id !== row.id).map((item) => item.serviceSlug))
                return <div className="grant-builder-row" key={row.id}>
                  <span className="grant-builder-number">{index + 1}</span>
                  <div className="field"><label htmlFor={`grant-service-${row.id}`}>Service</label><select id={`grant-service-${row.id}`} value={row.serviceSlug} onChange={(e) => updateService(row.id, e.target.value)}>{grantableServices.filter((item) => item.slug === row.serviceSlug || !usedByOthers.has(item.slug)).map((item) => <option key={item.slug} value={item.slug}>{item.name}</option>)}</select></div>
                  <div className="field"><label htmlFor={`grant-role-${row.id}`}>Role</label><select id={`grant-role-${row.id}`} value={row.roleKey} onChange={(e) => updateRole(row.id, e.target.value)}>{service?.roles.map((role) => <option key={role.key} value={role.key}>{role.name}</option>)}</select></div>
                  <button type="button" className="x" aria-label={`Remove ${service?.name || 'service'}`} onClick={() => setGrantRows((current) => current.filter((item) => item.id !== row.id))}>×</button>
                </div>
              })}
              {grantableServices.length === 0 ? <div className="muted">No services with roles are available.</div> : null}
            </div>
            <button type="button" className="btn-q grant-dialog__add" onClick={addService} disabled={grantRows.length >= grantableServices.length}>+ Add another service</button>
          </div>
          <div className="row-actions grant-dialog__actions">
            <button type="button" className="btn-q" onClick={onCancel} disabled={busy}>Cancel</button>
            <button type="submit" className="btn-act" disabled={busy || !userId || grantRows.length === 0}>{busy ? 'Saving…' : `Give ${grantRows.length} access grant${grantRows.length === 1 ? '' : 's'}`}</button>
          </div>
        </form>
      </div>
    </div>
  )
}

function BulkGrantDialog({
  services,
  onCancel,
  onDone,
}: {
  services: AdminService[]
  onCancel: () => void
  onDone: () => void
}) {
  const [slug, setSlug] = useState(services[0]?.slug ?? '')
  const [role, setRole] = useState(services[0]?.roles[0]?.key ?? '')
  const [bands, setBands] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<number | null>(null)
  const [preview, setPreview] = useState<number | null>(null)
  const svc = services.find((s) => s.slug === slug)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    try {
      const band = bands.split(',').map((b) => b.trim()).filter(Boolean)
      const r = await mmosApi.admin.bulkGrant({ slug, role, band: band.length ? band : undefined, preview: preview === null })
      if (preview === null) setPreview(r.count); else setResult(r.count)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="confirm-scrim" onClick={onCancel}>
      <div className="confirm-box" onClick={(e) => e.stopPropagation()} style={{ width: 420 }}>
        <h2>Bulk grant by band</h2>
        {result !== null ? (
          <>
            <p>Granted to {result} employee{result === 1 ? '' : 's'}.</p>
            <div className="row-actions"><button className="btn-act" onClick={onDone}>Done</button></div>
          </>
        ) : preview !== null ? <><p>Validation passed. This will create {preview} grant{preview === 1 ? '' : 's'}; existing identical grants will be skipped.</p><div className="row-actions"><button className="btn-q" onClick={() => setPreview(null)}>Back</button><button className="btn-act" onClick={(e) => submit(e as any)}>Commit grants</button></div></> : (
          <form onSubmit={submit}>
            <div className="field">
              <label htmlFor="bg-service">Service</label>
              <select id="bg-service" value={slug} onChange={(e) => { setSlug(e.target.value); setRole(services.find((s) => s.slug === e.target.value)?.roles[0]?.key ?? '') }}>
                {services.map((s) => <option key={s.slug} value={s.slug}>{s.name}</option>)}
              </select>
            </div>
            <div className="field">
              <label htmlFor="bg-role">Role</label>
              <select id="bg-role" value={role} onChange={(e) => setRole(e.target.value)}>
                {svc?.roles.map((r) => <option key={r.key} value={r.key}>{r.name}</option>)}
              </select>
            </div>
            <div className="field">
              <label htmlFor="bg-bands">Bands (comma separated)</label>
              <input id="bg-bands" value={bands} onChange={(e) => setBands(e.target.value)} placeholder="L3, L4" />
            </div>
            <div className="row-actions">
              <button type="button" className="btn-q" onClick={onCancel} disabled={busy}>Cancel</button>
              <button type="submit" className="btn-act" disabled={busy}>{busy ? 'Granting…' : 'Grant'}</button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
