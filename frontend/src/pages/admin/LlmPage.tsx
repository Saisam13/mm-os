import React, { useEffect, useState } from 'react'
import { mmosApi } from '../../api'
import type { AdminLlmRow } from '../../api/types'
import { EmptyState } from '../../components/EmptyState'
import { ReasonDialog } from '../../components/ReasonDialog'
import { Spark } from '../../components/Spark'
import { formatAge, formatCompact, formatNumber } from '../../lib/format'

// UI-DECISIONS.md § AI services page: "Approved as designed. Restyled to
// the brand, structure unchanged." A service that hasn't reported shows
// "unreported" in a muted style rather than blank cells.
export function LlmPage() {
  const [rows, setRows] = useState<AdminLlmRow[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [toggleTarget, setToggleTarget] = useState<AdminLlmRow | null>(null)
  const [busy, setBusy] = useState(false)

  function reload() {
    mmosApi.admin.listLlm().then(setRows).catch(() => setLoadError('Could not load LLM registrations.'))
  }
  useEffect(reload, [])

  async function confirmToggle(reason: string) {
    if (!toggleTarget) return
    setBusy(true)
    try {
      await mmosApi.admin.toggleLlm(toggleTarget.slug, !toggleTarget.enabled, reason)
      setToggleTarget(null)
      reload()
    } finally {
      setBusy(false)
    }
  }

  const unreportedCount = rows?.filter((r) => !r.provider).length ?? 0

  return (
    <div className="page">
      <div className="head">
        <h1>AI services</h1>
        {unreportedCount > 0 ? <span className="chip wn"><span className="dot w" /> {unreportedCount} unreported</span> : null}
      </div>
      <div className="card">
        <div className="card-h">
          <div><div className="eyebrow">Last 30 days · keys stay inside each service</div><h2>Usage and switches</h2></div>
        </div>
        <div className="card-b flush">
          {loadError ? (
            <EmptyState title={loadError} />
          ) : rows === null ? null : rows.length === 0 ? (
            <EmptyState title="No services report LLM usage" />
          ) : (
            <div className="tw">
              <table>
                <thead>
                  <tr><th>Service</th><th>Provider</th><th>Model</th><th>Key</th><th>Requests</th><th>Tokens</th><th>Trend</th><th>Seen</th><th>On</th></tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const totalReq = r.usage_30d.reduce((s, u) => s + u.requests, 0)
                    const totalTok = r.usage_30d.reduce((s, u) => s + u.input_tokens + u.output_tokens, 0)
                    const unreported = !r.provider
                    return (
                      <tr key={r.slug} className={unreported ? 'muted' : undefined}>
                        <td><strong>{r.name}</strong></td>
                        <td className="tight">{unreported ? 'unreported' : r.provider}</td>
                        <td className="tight cond">{unreported ? '—' : r.model?.toUpperCase()}</td>
                        <td className="tight"><span className={`chip${r.key_present ? ' pet' : ''}`}>{unreported ? 'unknown' : r.key_present ? 'present' : 'missing'}</span></td>
                        <td className="tight num">{unreported ? '—' : formatNumber(totalReq)}</td>
                        <td className="tight num">{unreported ? '—' : formatCompact(totalTok)}</td>
                        <td className="tight">{unreported ? '—' : <Spark points={r.usage_30d.map((u) => u.requests)} />}</td>
                        <td className="tight num muted">{formatAge(r.last_seen_at)}</td>
                        <td>
                          <button
                            className={r.enabled ? 'btn-q' : 'btn-act'}
                            onClick={() => setToggleTarget(r)}
                          >
                            {r.enabled ? 'On' : 'Off'}
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {toggleTarget ? (
        <ReasonDialog
          title={`${toggleTarget.enabled ? 'Disable' : 'Enable'} ${toggleTarget.name}`}
          label="Reason"
          confirmLabel={toggleTarget.enabled ? 'Disable' : 'Enable'}
          busy={busy}
          onConfirm={confirmToggle}
          onCancel={() => setToggleTarget(null)}
        />
      ) : null}
    </div>
  )
}
