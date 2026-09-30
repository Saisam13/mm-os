import React, { useEffect, useState } from 'react'
import { mmosApi } from '../../api'
import type { AdminDepartment, AdminEmployee, AdminService, PersonAccess, PersonEmails } from '../../api/types'
import { Panel } from '../../components/Panel'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { EmptyState } from '../../components/EmptyState'
import { formatDate } from '../../lib/format'
import { rowActivation } from '../../lib/a11y'
import { PeopleUploadDialog } from './PeopleUpload'
import { useAuth } from '../../auth/AuthContext'
import { ContractBadge } from './contractStatus'
const STATUSES = ['active', 'suspended', 'exited']

export function PeoplePage() {
  const { me } = useAuth()
  const canGrant = Boolean(me?.user.is_platform_admin || me?.user.capabilities?.includes('grants.add'))
  const [rows, setRows] = useState<AdminEmployee[] | null>(null)
  const [q, setQ] = useState('')
  const [dept, setDept] = useState('')
  const [status, setStatus] = useState('')
  const [selected, setSelected] = useState<AdminEmployee | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const [reloadKey, setReloadKey] = useState(0)
  const [departments, setDepartments] = useState<AdminDepartment[]>([])
  const [services, setServices] = useState<AdminService[]>([])
  const [adding, setAdding] = useState(false)

  function reload() {
    mmosApi.admin.listEmployees({ q: q || undefined, dept: dept || undefined, status: status || undefined })
      .then(setRows).catch(() => setLoadError('Could not load employees.'))
  }

  useEffect(() => {
    let cancelled = false
    mmosApi.admin
      .listEmployees({ q: q || undefined, dept: dept || undefined, status: status || undefined })
      .then((r) => { if (!cancelled) setRows(r) })
      .catch(() => { if (!cancelled) setLoadError('Could not load employees.') })
    return () => { cancelled = true }
  }, [q, dept, status, reloadKey])
  useEffect(() => { Promise.all([mmosApi.admin.listDepartments(), mmosApi.admin.listServices()]).then(([d, s]) => { setDepartments(d); setServices(s) }).catch(() => setLoadError('Could not load administration data.')) }, [])

  return (
    <>
      <div className="head"><div><h1>People</h1><div className="muted">Employees and human access only. Machine identities are managed under Agents.</div></div><div className="row-actions"><button className="btn-q" onClick={() => setUploading(true)}>Bulk upload</button><button className="btn-act" onClick={() => setAdding(true)}>Add person</button></div></div>

      <div className="filters">
        <div className="field">
          <label htmlFor="p-q">Search</label>
          <input id="p-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name or employee code" />
        </div>
        <div className="field">
          <label htmlFor="p-dept">Department</label>
          <select id="p-dept" value={dept} onChange={(e) => setDept(e.target.value)}>
            <option value="">All</option>
            {departments.filter((d) => d.is_active).map((d) => <option key={d.id} value={d.name}>{d.name}</option>)}
          </select>
        </div>
        <div className="field">
          <label htmlFor="p-status">Status</label>
          <select id="p-status" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All</option>
            {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
      </div>

      <div className="card">
        <div className="card-b flush">
          {loadError ? (
            <EmptyState title={loadError} />
          ) : rows === null ? null : rows.length === 0 ? (
            <EmptyState title="No employees match" />
          ) : (
            <div className="tw">
              <table>
                <thead>
                  <tr><th>Name</th><th>Department</th><th>Band</th><th>Sign-in</th><th>Status</th><th>Last seen</th></tr>
                </thead>
                <tbody>
                  {rows.map((e) => (
                    <tr key={e.id} className="clickable" onClick={() => setSelected(e)} {...rowActivation(() => setSelected(e))}>
                      <td><strong>{e.full_name}</strong> <span className="muted cond">{e.employee_code}</span></td>
                      <td className="tight">{e.hr_department}</td>
                      <td className="tight cond">{e.band}</td>
                      <td className="tight">{e.auth_type === 'google' ? 'Google' : 'PIN'}</td>
                      <td className="tight">
                        <span className={`chip${e.status === 'active' ? ' pet' : e.status === 'suspended' ? ' wn' : ''}`}>{e.status}</span>
                        {e.is_active === false ? <span className="chip" style={{ marginLeft: 6 }}>deactivated</span> : null}
                      </td>
                      <td className="tight num muted">{formatDate(e.last_login_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {uploading ? (
        <PeopleUploadDialog
          onCancel={() => setUploading(false)}
          onDone={() => { setUploading(false); setReloadKey((k) => k + 1) }}
        />
      ) : null}

      {selected ? (
        <PersonDrawer
          employee={selected}
          isAdmin={Boolean(me?.user.is_platform_admin)}
          departments={departments}
          onClose={() => setSelected(null)}
          onSaved={(updated) => {
            setRows((r) => r?.map((x) => (x.id === updated.id ? updated : x)) ?? r)
            setSelected(updated)
          }}
        />
      ) : null}
      {adding ? <AddPersonFlow departments={departments} services={canGrant ? services : []} onCancel={() => setAdding(false)} onCreated={() => { setAdding(false); reload() }} /> : null}
    </>
  )
}

function PersonDrawer({
  employee,
  isAdmin,
  departments,
  onClose,
  onSaved,
}: {
  employee: AdminEmployee
  isAdmin: boolean
  departments: AdminDepartment[]
  onClose: () => void
  onSaved: (e: AdminEmployee) => void
}) {
  const [form, setForm] = useState(employee)
  const [saving, setSaving] = useState(false)
  const [pin, setPin] = useState('')
  const [pinBusy, setPinBusy] = useState(false)
  const [pinMsg, setPinMsg] = useState<string | null>(null)
  const [confirmDeactivate, setConfirmDeactivate] = useState<{ grantCount: number } | null>(null)
  const [deactivating, setDeactivating] = useState(false)

  useEffect(() => setForm(employee), [employee])

  async function save() {
    setSaving(true)
    try {
      const updated = await mmosApi.admin.updateEmployee(employee.id, {
        department_id: form.department_id,
        division: form.division,
        job_title: form.job_title,
        band: form.band,
        approval_level: form.approval_level,
        notes: form.notes,
      })
      onSaved({ ...employee, ...updated })
    } finally {
      setSaving(false)
    }
  }

  async function openDeactivateConfirm() {
    if (!employee.user_id) return
    const grants = await mmosApi.admin.listGrants({ user: employee.user_id })
    setConfirmDeactivate({ grantCount: grants.length })
  }

  async function doDeactivate() {
    if (!employee.user_id) return
    setDeactivating(true)
    try {
      await mmosApi.admin.setUserActive(employee.user_id, false)
      onSaved({ ...employee, is_active: false })
      setConfirmDeactivate(null)
    } finally {
      setDeactivating(false)
    }
  }

  async function doReactivate() {
    if (!employee.user_id) return
    setDeactivating(true)
    try {
      await mmosApi.admin.setUserActive(employee.user_id, true)
      onSaved({ ...employee, is_active: true })
    } finally {
      setDeactivating(false)
    }
  }

  async function setNewPin() {
    if (!employee.user_id || !pin.trim()) return
    setPinBusy(true)
    setPinMsg(null)
    try {
      await mmosApi.admin.setPin(employee.user_id, pin.trim())
      setPinMsg('PIN set.')
      setPin('')
    } finally {
      setPinBusy(false)
    }
  }

  async function clearPin() {
    if (!employee.user_id) return
    setPinBusy(true)
    setPinMsg(null)
    try {
      await mmosApi.admin.setPin(employee.user_id, null)
      setPinMsg('PIN cleared.')
    } finally {
      setPinBusy(false)
    }
  }

  return (
    <Panel open onClose={onClose} eyebrow={employee.employee_code} title={employee.full_name}>
      <div className="field">
        <label htmlFor="e-dept">Department</label>
        <select id="e-dept" value={form.department_id ?? ''} onChange={(e) => { const d = departments.find((x) => x.id === e.target.value); setForm({ ...form, department_id: e.target.value, hr_department: d?.name ?? form.hr_department }) }}>
          {departments.filter((d) => d.is_active).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
        </select>
      </div>
      <div className="field">
        <label htmlFor="e-div">Division</label>
        <input id="e-div" value={form.division} onChange={(e) => setForm({ ...form, division: e.target.value })} />
      </div>
      <div className="field">
        <label htmlFor="e-title">Job title</label>
        <input id="e-title" value={form.job_title} onChange={(e) => setForm({ ...form, job_title: e.target.value })} />
      </div>
      <div className="field">
        <label htmlFor="e-band">Band</label>
        <input id="e-band" value={form.band} onChange={(e) => setForm({ ...form, band: e.target.value })} />
      </div>
      <div className="field">
        <label htmlFor="e-appr">Approval level</label>
        <input id="e-appr" value={form.approval_level ?? ''} onChange={(e) => setForm({ ...form, approval_level: e.target.value })} />
      </div>
      <div className="field">
        <label htmlFor="e-notes">Notes</label>
        <textarea id="e-notes" rows={3} value={form.notes ?? ''} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
      </div>
      <button className="btn-act" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>

      {employee.auth_type === 'local_pin' ? (
        <>
          <div className="eyebrow" style={{ margin: '22px 0 8px' }}>PIN</div>
          {pinMsg ? <div className="chip pet" style={{ marginBottom: 8 }}>{pinMsg}</div> : null}
          <div className="field">
            <label htmlFor="e-pin">New PIN</label>
            <input id="e-pin" value={pin} onChange={(e) => setPin(e.target.value)} inputMode="numeric" />
          </div>
          <div className="row-actions">
            <button className="btn-q" onClick={setNewPin} disabled={pinBusy || !pin.trim()}>Issue / reset PIN</button>
            <button className="btn-q" onClick={clearPin} disabled={pinBusy}>Clear PIN</button>
          </div>
        </>
      ) : null}

      <EmailsSection employeeId={employee.id} onOfficialSaved={(email) => onSaved({ ...employee, work_email: email || null })} />

      {isAdmin && employee.user_id ? <ViewAs userId={employee.user_id} /> : null}

      <div className="eyebrow" style={{ margin: '22px 0 8px' }}>Access</div>
      {employee.is_platform_admin ? (
        <span className="chip pet">Protected IT Admin · no normal deactivate action</span>
      ) : employee.is_active === false ? (
        <>
          <span className="chip" style={{ marginRight: 8 }}>Deactivated</span>
          <button className="btn-q" onClick={doReactivate} disabled={deactivating}>{deactivating ? 'Reactivating…' : 'Reactivate person'}</button>
        </>
      ) : (
        <button className="btn-q btn-danger" onClick={openDeactivateConfirm}>Deactivate person</button>
      )}

      {confirmDeactivate ? (
        <ConfirmDialog
          title={`Deactivate ${employee.full_name}?`}
          body={`Ends every session and removes access to ${confirmDeactivate.grantCount} service${confirmDeactivate.grantCount === 1 ? '' : 's'} within 60 seconds.`}
          confirmLabel="Deactivate"
          busy={deactivating}
          onConfirm={doDeactivate}
          onCancel={() => setConfirmDeactivate(null)}
        />
      ) : null}
    </Panel>
  )
}

// Sign-in emails: the company address (Google sign-in) and an optional personal Gmail that
// still needs the person to type their employee code the first time.
function EmailsSection({ employeeId, onOfficialSaved }: { employeeId: string; onOfficialSaved: (email: string) => void }) {
  const [saved, setSaved] = useState<PersonEmails | null>(null)
  const [official, setOfficial] = useState('')
  const [personal, setPersonal] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  useEffect(() => {
    setSaved(null); setMsg(null)
    mmosApi.admin.getPersonEmails(employeeId).then((e) => { setSaved(e); setOfficial(e.official ?? ''); setPersonal(e.personal ?? '') })
      .catch(() => setMsg({ ok: false, text: 'Could not load their emails.' }))
  }, [employeeId])

  async function saveEmails() {
    if (!saved) return
    const patch: { official?: string; personal?: string } = {}
    if (official.trim().toLowerCase() !== (saved.official ?? '')) patch.official = official.trim()
    if (personal.trim().toLowerCase() !== (saved.personal ?? '')) patch.personal = personal.trim()
    if (patch.official === undefined && patch.personal === undefined) { setMsg({ ok: true, text: 'Nothing to change.' }); return }
    if (patch.official !== undefined && saved.official && patch.official !== '' && !window.confirm(`Change the Google sign-in from ${saved.official} to ${patch.official}? They are signed out everywhere.`)) return
    if (patch.official === '' && !window.confirm('Remove the Google sign-in? They are signed out everywhere and can only use their PIN.')) return
    setBusy(true); setMsg(null)
    try {
      const next = await mmosApi.admin.setPersonEmails(employeeId, patch)
      setSaved(next); setOfficial(next.official ?? ''); setPersonal(next.personal ?? '')
      if (patch.official !== undefined) onOfficialSaved(next.official ?? '')
      setMsg({ ok: true, text: 'Emails saved.' })
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : 'Could not save emails.' })
    } finally { setBusy(false) }
  }

  return (
    <>
      <div className="eyebrow" style={{ margin: '22px 0 8px' }}>Sign-in emails</div>
      {msg ? <div className={`chip${msg.ok ? ' pet' : ' wn'}`} style={{ marginBottom: 8 }} role="status">{msg.text}</div> : null}
      <div className="field">
        <label htmlFor="e-official">Official email (Google sign-in)</label>
        <input id="e-official" type="email" value={official} onChange={(e) => setOfficial(e.target.value)} placeholder="name@m-mines.com" disabled={saved === null} />
      </div>
      <div className="field">
        <label htmlFor="e-personal">Personal email (optional)</label>
        <input id="e-personal" type="email" value={personal} onChange={(e) => setPersonal(e.target.value)} placeholder="name@gmail.com" disabled={saved === null} />
        <div className="muted">
          {saved?.personal ? (saved.personal_verified ? 'Confirmed by the person.' : 'Works after the person types their employee code once.') : 'Leave empty for none.'}
        </div>
      </div>
      <div className="row-actions">
        <button className="btn-q" onClick={saveEmails} disabled={busy || saved === null}>{busy ? 'Saving…' : 'Save emails'}</button>
        <button className="btn-q btn-danger" onClick={() => setOfficial('')} disabled={busy || !official}>Remove official</button>
        <button className="btn-q btn-danger" onClick={() => setPersonal('')} disabled={busy || !personal}>Remove personal</button>
      </div>
      <div className="muted" style={{ marginTop: 6 }}>Remove only empties the field; press Save emails to apply it.</div>
    </>
  )
}

// "View as": what each service receives for this person when they open it from MM OS,
// computed by the same code as the token handoff (GET /api/admin/people/{id}/access).
function ViewAs({ userId }: { userId: string }) {
  const [data, setData] = useState<PersonAccess | null>(null)
  const [err, setErr] = useState(false)
  useEffect(() => {
    setData(null); setErr(false)
    mmosApi.admin.personAccess(userId).then(setData).catch(() => setErr(true))
  }, [userId])

  return (
    <>
      <div className="eyebrow" style={{ margin: '22px 0 8px' }}>What they can do</div>
      {err ? <p className="muted" style={{ margin: 0 }}>Could not load their access.</p>
        : data === null ? <p className="muted" style={{ margin: 0 }}>Loading…</p>
        : data.services.length === 0 ? <p className="muted" style={{ margin: 0 }}>No access to any service.</p>
        : (
          <>
            {!data.can_sign_in ? <p className="muted" style={{ margin: '0 0 6px' }}>They cannot sign in at the moment, so none of this reaches a service.</p> : null}
            <div className="tw">
              <table style={{ fontSize: 12.5 }}>
                <thead><tr><th>Service</th><th>Role</th><th>Can do</th></tr></thead>
                <tbody>
                  {data.services.map((s) => (
                    <tr key={s.slug}>
                      <td style={{ whiteSpace: 'normal' }}>
                        <strong>{s.name}</strong>{!s.is_active ? <span className="muted"> (switched off)</span> : null}
                        <div style={{ marginTop: 4 }}>
                          {s.contract ? <ContractBadge status={s.contract.status} /> : <span className="muted" title="Check it on Services">rules not checked</span>}
                        </div>
                      </td>
                      <td className="cond" style={{ whiteSpace: 'normal' }}>{s.roles.join(', ')}</td>
                      <td style={{ whiteSpace: 'normal' }}>
                        {s.permissions.length ? <span className="cond">{s.permissions.join(', ')}</span>
                          : <span className="muted">Nothing listed; the service goes by the role name</span>}
                        <div className="muted cond" style={{ fontSize: 11 }} title="Permission version carried in the token">pv {s.pv}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
    </>
  )
}

function AddPersonFlow({ departments, services, onCancel, onCreated }: { departments: AdminDepartment[]; services: AdminService[]; onCancel: () => void; onCreated: () => void }) {
  const [step, setStep] = useState(1)
  const [form, setForm] = useState({ employee_code: '', full_name: '', work_email: '', onboarding_ref: '', department_id: departments.find((d) => d.is_active)?.id ?? '', division: '', job_title: '', band: '' })
  const [selected, setSelected] = useState<Record<string, string[]>>({})
  const [search, setSearch] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const serviceList = services.filter((s) => s.is_active && s.name.toLowerCase().includes(search.toLowerCase()))
  function toggleService(slug: string) { setSelected((x) => x[slug] ? Object.fromEntries(Object.entries(x).filter(([k]) => k !== slug)) : { ...x, [slug]: [] }) }
  function toggleRole(slug: string, role: string) { setSelected((x) => ({ ...x, [slug]: x[slug]?.includes(role) ? x[slug].filter((r) => r !== role) : [...(x[slug] || []), role] })) }
  async function create() {
    setBusy(true); setError(null)
    try {
      await mmosApi.admin.createPerson({ employee: { ...form, work_email: form.work_email || null, onboarding_ref: form.onboarding_ref || null }, auth_type: form.work_email ? 'google' : 'local_pin', grants: Object.entries(selected).map(([service_slug, roles]) => ({ service_slug, roles, reason: 'Assigned during person creation' })) })
      onCreated()
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not create person.') } finally { setBusy(false) }
  }
  const validInfo = form.employee_code && form.full_name && form.division && form.job_title && form.band
  const validRoles = Object.values(selected).every((r) => r.length > 0)
  return <div className="confirm-scrim" onClick={onCancel}><div className="confirm-box" onClick={(e) => e.stopPropagation()} style={{ width: 680, maxWidth: '94vw' }}>
    <div className="eyebrow">Step {step} of 5</div><h2>Add person</h2>
    {error ? <div className="form-err" role="alert">{error}</div> : null}
    {step === 1 ? <><div className="field"><label>Employee code</label><input value={form.employee_code} onChange={(e) => setForm({ ...form, employee_code: e.target.value })} /></div><div className="field"><label>Full name</label><input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></div><div className="field"><label>Work email</label><input type="email" value={form.work_email} onChange={(e) => setForm({ ...form, work_email: e.target.value })} /></div><div className="field"><label>HR onboarding reference (optional)</label><input value={form.onboarding_ref} onChange={(e) => setForm({ ...form, onboarding_ref: e.target.value })} /></div><div className="field"><label>Division</label><input value={form.division} onChange={(e) => setForm({ ...form, division: e.target.value })} /></div><div className="field"><label>Job title</label><input value={form.job_title} onChange={(e) => setForm({ ...form, job_title: e.target.value })} /></div><div className="field"><label>Band</label><input value={form.band} onChange={(e) => setForm({ ...form, band: e.target.value })} /></div></> : null}
    {step === 2 ? <div className="field"><label htmlFor="new-dept">Existing department</label><select id="new-dept" value={form.department_id} onChange={(e) => setForm({ ...form, department_id: e.target.value })}>{departments.filter((d) => d.is_active).map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}</select><div className="muted">Department names are controlled to prevent duplicate spellings.</div></div> : null}
    {step === 3 ? <><div className="field"><label htmlFor="service-search">Search services</label><input id="service-search" value={search} onChange={(e) => setSearch(e.target.value)} /></div>{serviceList.map((s) => <label className="grant-row" key={s.slug}><input type="checkbox" checked={Boolean(selected[s.slug])} onChange={() => toggleService(s.slug)} /><span className="g"><span className="nm">{s.name}</span><span className="mt">{s.tagline}</span></span></label>)}</> : null}
    {step === 4 ? Object.keys(selected).length === 0 ? <EmptyState title="No services selected" hint="Continue to create the person without service access." /> : services.filter((s) => selected[s.slug]).map((s) => <div key={s.slug} style={{ marginBottom: 18 }}><strong>{s.name}</strong>{s.roles.map((r) => <label className="grant-row" key={r.key}><input type="checkbox" checked={selected[s.slug]?.includes(r.key)} onChange={() => toggleRole(s.slug, r.key)} /><span className="g"><span className="nm">{r.name}</span><span className="mt">{r.description}</span></span></label>)}</div>) : null}
    {step === 5 ? <div><p><strong>{form.full_name}</strong> · {form.employee_code}</p><p>{departments.find((d) => d.id === form.department_id)?.name} · {form.job_title}</p><p>{Object.entries(selected).map(([slug, roles]) => `${services.find((s) => s.slug === slug)?.name}: ${roles.join(', ')}`).join(' · ') || 'No service grants'}</p><p className="muted">Creation and all grants are committed together. Any validation error leaves no partial person or grants.</p></div> : null}
    <div className="row-actions"><button className="btn-q" onClick={step === 1 ? onCancel : () => setStep(step - 1)}>{step === 1 ? 'Cancel' : 'Back'}</button>{step < 5 ? <button className="btn-act" onClick={() => setStep(step + 1)} disabled={(step === 1 && !validInfo) || (step === 2 && !form.department_id) || (step === 4 && !validRoles)}>Continue</button> : <button className="btn-act" onClick={create} disabled={busy}>{busy ? 'Creating…' : 'Create person'}</button>}</div>
  </div></div>
}
