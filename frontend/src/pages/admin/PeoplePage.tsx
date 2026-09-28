import React, { useEffect, useState } from 'react'
import { mmosApi } from '../../api'
import type { AdminEmployee } from '../../api/types'
import { Panel } from '../../components/Panel'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { EmptyState } from '../../components/EmptyState'
import { formatDate } from '../../lib/format'
import { rowActivation } from '../../lib/a11y'

const DEPARTMENTS = ['CXO Office', 'P-Spoke', 'Project', 'Purchase', 'QA/QC', 'Projects']
const STATUSES = ['active', 'suspended', 'exited']

export function PeoplePage() {
  const [rows, setRows] = useState<AdminEmployee[] | null>(null)
  const [q, setQ] = useState('')
  const [dept, setDept] = useState('')
  const [status, setStatus] = useState('')
  const [selected, setSelected] = useState<AdminEmployee | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    mmosApi.admin
      .listEmployees({ q: q || undefined, dept: dept || undefined, status: status || undefined })
      .then((r) => { if (!cancelled) setRows(r) })
      .catch(() => { if (!cancelled) setLoadError('Could not load employees.') })
    return () => { cancelled = true }
  }, [q, dept, status])

  return (
    <>
      <div className="head"><h1>People</h1></div>

      <div className="filters">
        <div className="field">
          <label htmlFor="p-q">Search</label>
          <input id="p-q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name or employee code" />
        </div>
        <div className="field">
          <label htmlFor="p-dept">Department</label>
          <select id="p-dept" value={dept} onChange={(e) => setDept(e.target.value)}>
            <option value="">All</option>
            {DEPARTMENTS.map((d) => <option key={d} value={d}>{d}</option>)}
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

      {selected ? (
        <PersonDrawer
          employee={selected}
          onClose={() => setSelected(null)}
          onSaved={(updated) => {
            setRows((r) => r?.map((x) => (x.id === updated.id ? updated : x)) ?? r)
            setSelected(updated)
          }}
        />
      ) : null}
    </>
  )
}

function PersonDrawer({
  employee,
  onClose,
  onSaved,
}: {
  employee: AdminEmployee
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
        hr_department: form.hr_department,
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
        <input id="e-dept" value={form.hr_department} onChange={(e) => setForm({ ...form, hr_department: e.target.value })} />
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

      <div className="eyebrow" style={{ margin: '22px 0 8px' }}>Access</div>
      {employee.is_active === false ? (
        <span className="chip">Already deactivated</span>
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
