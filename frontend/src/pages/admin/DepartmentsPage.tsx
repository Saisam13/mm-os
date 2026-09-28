import React, { useEffect, useState } from 'react'
import { mmosApi } from '../../api'
import type { AdminDepartment } from '../../api/types'
import { EmptyState } from '../../components/EmptyState'

export function DepartmentsPage() {
  const [rows, setRows] = useState<AdminDepartment[] | null>(null)
  const [name, setName] = useState('')
  const [erpDepartment, setErpDepartment] = useState('')
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState<string | null>(null)
  const load = () => mmosApi.admin.listDepartments().then((departments) => {
    setRows(departments)
    setDrafts(Object.fromEntries(departments.map((department) => [department.id, department.erp_department ?? ''])))
  })
  useEffect(() => { void load() }, [])
  async function add(e: React.FormEvent) {
    e.preventDefault()
    await mmosApi.admin.createDepartment({ name, key: name.toLowerCase().replace(/[^a-z0-9]+/g, '-'), erp_department: erpDepartment.trim() || name })
    setName(''); setErpDepartment(''); await load()
  }
  async function saveErp(department: AdminDepartment) {
    setSaving(department.id)
    try { await mmosApi.admin.updateDepartment(department.id, { erp_department: drafts[department.id]?.trim() || null }); await load() }
    finally { setSaving(null) }
  }
  return <>
    <div className="head"><div><h1>Departments</h1><div className="muted">Match each MM OS department to its ERPNext department.</div></div></div>
    <div className="card"><div className="card-h"><h2>Add department</h2></div><div className="card-b"><form className="department-add-form" onSubmit={add}>
      <div className="field"><label htmlFor="department-name">MM OS department</label><input id="department-name" value={name} onChange={(e) => setName(e.target.value)} required /></div>
      <div className="field"><label htmlFor="erp-department-name">ERPNext department</label><input id="erp-department-name" value={erpDepartment} onChange={(e) => setErpDepartment(e.target.value)} placeholder={name || 'ERPNext department name'} /></div>
      <button className="btn-act">Add department</button>
    </form></div></div>
    <div className="card"><div className="card-b flush">{rows?.length ? <div className="matrix-wrap"><table><thead><tr><th>MM OS department</th><th>ERPNext department</th><th>Key</th><th>Status</th><th></th></tr></thead><tbody>{rows.map((department) => <tr key={department.id}>
      <td><strong>{department.name}</strong></td>
      <td><div className="erp-map-edit"><input aria-label={`ERPNext department for ${department.name}`} value={drafts[department.id] ?? ''} onChange={(e) => setDrafts({ ...drafts, [department.id]: e.target.value })} /><button className="btn-q" disabled={saving === department.id || (drafts[department.id] ?? '') === (department.erp_department ?? '')} onClick={() => saveErp(department)}>{saving === department.id ? 'Saving…' : 'Save'}</button></div></td>
      <td className="cond">{department.key}</td>
      <td><span className={`chip${department.is_active ? ' pet' : ''}`}>{department.is_active ? 'active' : 'inactive'}</span></td>
      <td><button className="btn-q" onClick={async () => { await mmosApi.admin.updateDepartment(department.id, { is_active: !department.is_active }); await load() }}>{department.is_active ? 'Deactivate' : 'Activate'}</button></td>
    </tr>)}</tbody></table></div> : rows ? <EmptyState title="No departments configured" /> : null}</div></div>
  </>
}
