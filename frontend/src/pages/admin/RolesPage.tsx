import React, { useEffect, useState } from 'react'
import { mmosApi } from '../../api'
import type { AdminEmployee, CapabilityAssignment } from '../../api/types'

export function RolesPage() {
  const [available, setAvailable] = useState<string[]>([]); const [assignments, setAssignments] = useState<CapabilityAssignment[]>([]); const [people, setPeople] = useState<AdminEmployee[]>([])
  const [user, setUser] = useState(''); const [cap, setCap] = useState('')
  const load = () => Promise.all([mmosApi.admin.listCapabilities(), mmosApi.admin.listEmployees({})]).then(([c, p]) => { setAvailable(c.available); setAssignments(c.assignments); setPeople(p); setCap((x) => x || c.available[0] || '') })
  useEffect(() => { void load() }, [])
  async function grant(e: React.FormEvent) { e.preventDefault(); await mmosApi.admin.grantCapability(user, cap); load() }
  return <><div className="head"><div><h1>Roles & capabilities</h1><div className="muted">Delegated administration is explicit and enforced by the API.</div></div></div><div className="card"><div className="card-h"><h2>Delegate capability</h2></div><div className="card-b"><form onSubmit={grant}><div className="field"><label>Person</label><select value={user} onChange={(e) => setUser(e.target.value)} required><option value="">Choose…</option>{people.filter((p) => p.user_id && !p.is_platform_admin).map((p) => <option key={p.id} value={p.user_id!}>{p.full_name}</option>)}</select></div><div className="field"><label>Capability</label><select value={cap} onChange={(e) => setCap(e.target.value)}>{available.map((c) => <option key={c}>{c}</option>)}</select></div><button className="btn-act">Grant capability</button></form></div></div><div className="card"><div className="card-b flush"><table><thead><tr><th>Person</th><th>Capability</th><th>Scope</th><th></th></tr></thead><tbody>{assignments.map((a) => <tr key={a.id}><td>{people.find((p) => p.user_id === a.user_id)?.full_name || a.user_id}</td><td className="cond">{a.capability}</td><td>{a.scope_department_id || 'All departments'}</td><td><button className="btn-q btn-danger" onClick={async () => { await mmosApi.admin.revokeCapability(a.id); load() }}>Revoke</button></td></tr>)}</tbody></table></div></div></>
}
