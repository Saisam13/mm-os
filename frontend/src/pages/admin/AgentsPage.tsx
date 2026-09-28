import React, { useEffect, useState } from 'react'
import { mmosApi } from '../../api'
import type { AdminAgent } from '../../api/types'
import { EmptyState } from '../../components/EmptyState'

export function AgentsPage() {
  const [rows, setRows] = useState<AdminAgent[] | null>(null)
  const [name, setName] = useState(''); const [slug, setSlug] = useState('')
  const load = () => mmosApi.admin.listAgents().then(setRows)
  useEffect(() => { void load() }, [])
  async function add(e: React.FormEvent) { e.preventDefault(); await mmosApi.admin.createAgent({ name, slug, kind: 'agent' }); setName(''); setSlug(''); load() }
  return <><div className="head"><div><h1>Agents</h1><div className="muted">AI agents, automations, integrations, and machine identities. Credentials never appear here.</div></div></div>
    <div className="card"><div className="card-h"><h2>Add machine identity</h2></div><div className="card-b"><form onSubmit={add}><div className="field"><label htmlFor="agent-name">Name</label><input id="agent-name" value={name} onChange={(e) => setName(e.target.value)} required /></div><div className="field"><label htmlFor="agent-slug">Slug</label><input id="agent-slug" value={slug} onChange={(e) => setSlug(e.target.value)} required /></div><button className="btn-act">Add agent</button></form></div></div>
    <div className="card"><div className="card-b flush">{rows?.length ? <table><thead><tr><th>Name</th><th>Type</th><th>Status</th></tr></thead><tbody>{rows.map((a) => <tr key={a.id}><td><strong>{a.name}</strong> <span className="muted cond">{a.slug}</span></td><td>{a.kind}</td><td><span className={`chip${a.is_active ? ' pet' : ''}`}>{a.is_active ? 'active' : 'inactive'}</span></td></tr>)}</tbody></table> : rows ? <EmptyState title="No agents" /> : null}</div></div></>
}
