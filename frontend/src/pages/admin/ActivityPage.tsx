import { useEffect, useState } from 'react'
import { listActivity } from '../../api/client'

export function ActivityPage() {
  const [filters, setFilters] = useState({ service: '', actor: '', action: '', target: '', after: '', before: '' })
  const [query, setQuery] = useState<Record<string, string | number | undefined>>({})
  const [events, setEvents] = useState<any[]>([])
  const [offset, setOffset] = useState(0)
  const [next, setNext] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  useEffect(() => {
    let active = true
    setLoading(true); setError('')
    listActivity({ ...query, offset, limit: 50 }).then(result => {
      if (active) { setEvents(result.events); setNext(result.next_offset) }
    }).catch(err => {
      if (active) { setEvents([]); setNext(null); setError(err.message || 'Could not load activity.') }
    }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [query, offset])
  return <>
    <div className="head"><div><h1>Service activity</h1><div className="muted">People and actions reported by connected services. Only activity within your permitted scope appears.</div></div></div>
    <form className="card" onSubmit={event => {
      event.preventDefault(); setOffset(0)
      setQuery({ ...filters, after: filters.after ? new Date(filters.after).toISOString() : undefined,
        before: filters.before ? new Date(filters.before).toISOString() : undefined })
    }}><div className="card-b">
      {(['service', 'actor', 'action', 'target'] as const).map(key => <div className="field" key={key}>
        <label>{key === 'actor' ? 'Person — employee code or permanent user ID' : key === 'target' ? 'Record ID' : key[0].toUpperCase() + key.slice(1)}</label>
        <input value={filters[key]} onChange={event => setFilters({ ...filters, [key]: event.target.value })} />
      </div>)}
      {(['after', 'before'] as const).map(key => <div className="field" key={key}><label>{key === 'after' ? 'From' : 'Until'}</label>
        <input type="datetime-local" value={filters[key]} onChange={event => setFilters({ ...filters, [key]: event.target.value })} /></div>)}
      <button className="btn-act" disabled={loading}>Search activity</button>
    </div></form>
    {error && <p role="alert">{error}</p>}
    <div className="card"><div className="card-b flush"><table><thead><tr><th>When</th><th>Person</th><th>Service / action</th><th>Record</th><th>Outcome</th><th>Change</th></tr></thead><tbody>
      {events.map(event => <tr key={`${event.service}:${event.event_id}`}>
        <td>{new Date(event.occurred_at).toLocaleString()}</td>
        <td>{event.actor.name || event.actor.employee_code || event.actor.subject}<div className="muted">{event.actor.employee_code || event.actor.type}</div></td>
        <td>{event.service}<div>{event.action}</div></td><td>{event.target.type}<div>{event.target.id}</div></td>
        <td>{event.outcome}{event.restricted ? <div className="muted">Restricted</div> : null}</td>
        <td>{Object.entries(event.changes || {}).map(([field, value]: [string, any]) => <div key={field}>{field}: {String(value.before ?? '—')} → {String(value.after ?? '—')}</div>)}
          {!Object.keys(event.changes || {}).length && (event.changed_fields || []).join(', ')}</td>
      </tr>)}
      {!loading && !error && events.length === 0 && <tr><td colSpan={6}>No accessible activity matches these filters.</td></tr>}
    </tbody></table></div></div>
    <div className="row-actions"><button className="btn-q" disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</button>
      <button className="btn-q" disabled={next === null || loading} onClick={() => next !== null && setOffset(next)}>Next</button></div>
  </>
}
