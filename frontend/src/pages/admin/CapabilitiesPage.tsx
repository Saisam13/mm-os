import React, { useEffect, useState } from 'react'
import { mmosApi } from '../../api'
import type { AdminEmployee, CapabilityAssignment } from '../../api/types'

export function CapabilitiesPage() {
  const [available, setAvailable] = useState<string[]>([])
  const [assignments, setAssignments] = useState<CapabilityAssignment[]>([])
  const [people, setPeople] = useState<AdminEmployee[]>([])
  const [user, setUser] = useState('')
  const [capability, setCapability] = useState('')
  const load = () => Promise.all([mmosApi.admin.listCapabilities(), mmosApi.admin.listEmployees({})])
    .then(([caps, employees]) => {
      setAvailable(caps.available)
      setAssignments(caps.assignments)
      setPeople(employees)
      setCapability((current) => current || caps.available[0] || '')
    })
  useEffect(() => { void load() }, [])
  async function grant(event: React.FormEvent) {
    event.preventDefault()
    await mmosApi.admin.grantCapability(user, capability)
    await load()
  }
  return <>
    <div className="head"><div><h1>Administrative capabilities</h1><div className="muted">Delegated authority is explicit and enforced by the API.</div></div></div>
    <div className="card"><div className="card-h"><h2>Delegate capability</h2></div><div className="card-b"><form onSubmit={grant}>
      <div className="field"><label>Person</label><select value={user} onChange={(e) => setUser(e.target.value)} required><option value="">Choose…</option>{people.filter((person) => person.user_id && !person.is_platform_admin).map((person) => <option key={person.id} value={person.user_id!}>{person.full_name}</option>)}</select></div>
      <div className="field"><label>Capability</label><select value={capability} onChange={(e) => setCapability(e.target.value)}>{available.map((item) => <option key={item}>{item}</option>)}</select></div>
      <button className="btn-act">Grant capability</button>
    </form></div></div>
    <div className="card"><div className="card-b flush"><table><thead><tr><th>Person</th><th>Capability</th><th>Scope</th><th></th></tr></thead><tbody>{assignments.map((assignment) => <tr key={assignment.id}><td>{people.find((person) => person.user_id === assignment.user_id)?.full_name || assignment.user_id}</td><td className="cond">{assignment.capability}</td><td>{assignment.scope_department_id || 'All departments'}</td><td><button className="btn-q btn-danger" onClick={async () => { await mmosApi.admin.revokeCapability(assignment.id); await load() }}>Revoke</button></td></tr>)}</tbody></table></div></div>
  </>
}
