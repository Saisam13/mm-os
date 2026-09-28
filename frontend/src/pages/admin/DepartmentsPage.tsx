import React, { useEffect, useState } from 'react'
import { mmosApi } from '../../api'
import type { AdminDepartment } from '../../api/types'
import { EmptyState } from '../../components/EmptyState'

export function DepartmentsPage() {
  const [rows, setRows] = useState<AdminDepartment[] | null>(null)
  const [name, setName] = useState(''); const load = () => mmosApi.admin.listDepartments().then(setRows)
  useEffect(() => { void load() }, [])
  async function add(e: React.FormEvent) { e.preventDefault(); await mmosApi.admin.createDepartment({ name, key: name.toLowerCase().replace(/[^a-z0-9]+/g, '-') }); setName(''); load() }
  return <><div className="head"><div><h1>Departments</h1><div className="muted">Controlled organization values used for every employee assignment.</div></div></div><div className="card"><div className="card-h"><h2>Add department</h2></div><div className="card-b"><form onSubmit={add}><div className="field"><label>Name</label><input value={name} onChange={(e) => setName(e.target.value)} required /></div><button className="btn-act">Add department</button></form></div></div><div className="card"><div className="card-b flush">{rows?.length ? <table><thead><tr><th>Department</th><th>Key</th><th>Status</th><th></th></tr></thead><tbody>{rows.map((d) => <tr key={d.id}><td><strong>{d.name}</strong></td><td className="cond">{d.key}</td><td><span className={`chip${d.is_active ? ' pet' : ''}`}>{d.is_active ? 'active' : 'inactive'}</span></td><td><button className="btn-q" onClick={async () => { await mmosApi.admin.updateDepartment(d.id, { is_active: !d.is_active }); load() }}>{d.is_active ? 'Deactivate' : 'Activate'}</button></td></tr>)}</tbody></table> : rows ? <EmptyState title="No departments configured" /> : null}</div></div></>
}
