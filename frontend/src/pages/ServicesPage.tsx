import React from 'react'
import { useAuth } from '../auth/AuthContext'
import { ServiceMark } from '../components/ServiceMark'
import { EmptyState } from '../components/EmptyState'
import { useLaunchService, canEmbed } from '../lib/useLaunchService'
import { kindFromLaunchMode } from '../lib/serviceKind'

// The same surface as the entry page, now with role and status filled in.
// Rows come straight from /api/me — never filtered client-side, the server
// already returned only what this person may open (agents/A3-shell.md).
export function ServicesPage() {
  const { me } = useAuth()
  const { launch, pending, error, clearError } = useLaunchService()
  if (!me) return null

  return (
    <div className="page">
      <div className="head">
        <h1>Services</h1>
      </div>
      <div className="card">
        <div className="card-b flush">
          {me.services.length === 0 ? (
            <EmptyState title="No services yet" hint="Raise a request and IT will set you up." />
          ) : (
            me.services.map((s) => {
              const isPending = pending === s.slug
              const rowError = error?.slug === s.slug ? error.message : null
              return (
                <div key={s.slug}>
                  <button className="svc" onClick={() => launch(s)} disabled={isPending}>
                    <ServiceMark slug={s.slug} name={s.name} kind={kindFromLaunchMode(s.launch_mode)} />
                    <span>
                      <span className="svc-name">{s.name}</span>
                    </span>
                    <span className="svc-grow" />
                    <span className="svc-meta">
                      {isPending ? <span className="chip">Opening…</span> : null}
                      <span className="chip cond">{canEmbed(s) ? 'Embedded' : 'New tab'}</span>
                      <span className={`chip${s.role === 'admin' || s.role === 'agent' || s.role === 'manager' ? ' pet' : ''}`}>{s.role}</span>
                      <span className={`dot${s.health === 'up' ? '' : s.health === 'build' ? ' o' : ' w'}`} />
                    </span>
                    <svg className="svc-arrow" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                      <path d="M9 6l6 6-6 6" />
                    </svg>
                  </button>
                  {rowError ? (
                    <div className="form-err" style={{ margin: '0 10px 10px' }}>
                      {rowError}{' '}
                      <button className="btn-q" style={{ marginLeft: 8 }} onClick={clearError}>
                        Dismiss
                      </button>
                    </div>
                  ) : null}
                </div>
              )
            })
          )}
        </div>
      </div>
    </div>
  )
}
