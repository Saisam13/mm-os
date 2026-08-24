import React, { useEffect, useState } from 'react'
import { mmosApi } from '../../api'
import type { AuditEntry } from '../../api/types'
import { EmptyState } from '../../components/EmptyState'
import { formatDateTime } from '../../lib/format'

export function AuditPage() {
  const [rows, setRows] = useState<AuditEntry[] | null>(null)
  const [action, setAction] = useState('')
  const [loadError, setLoadError] = useState<string | null>(null)

  useEffect(() => {
    mmosApi.admin.listAudit({ action: action || undefined, limit: 200 })
      .then(setRows)
      .catch(() => setLoadError('Could not load the audit log.'))
  }, [action])

  return (
    <>
      <div className="head"><h1>Audit</h1></div>

      <div className="filters">
        <div className="field">
          <label htmlFor="a-action">Action</label>
          <input id="a-action" value={action} onChange={(e) => setAction(e.target.value)} placeholder="grant.create" />
        </div>
      </div>

      <div className="card">
        <div className="card-b flush">
          {loadError ? (
            <EmptyState title={loadError} />
          ) : rows === null ? null : rows.length === 0 ? (
            <EmptyState title="No matching audit entries" />
          ) : (
            <div className="tw">
              <table>
                <thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Target</th><th>Service</th><th>IP</th></tr></thead>
                <tbody>
                  {rows.map((a) => (
                    <tr key={a.id}>
                      <td className="tight num">{formatDateTime(a.created_at)}</td>
                      <td className="tight">{a.actor?.name ?? <span className="muted">system</span>}</td>
                      <td className="tight cond">{a.action}</td>
                      <td className="tight muted cond">{a.target_type ?? '—'}</td>
                      <td className="tight">{a.service?.name ?? '—'}</td>
                      <td className="tight num muted">{a.ip ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
