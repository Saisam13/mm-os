import React from 'react'
import { useAuth } from '../auth/AuthContext'
import { ServiceMark } from '../components/ServiceMark'
import { EmptyState } from '../components/EmptyState'
import { useLaunchService } from '../lib/useLaunchService'
import { kindFromLaunchMode } from '../lib/serviceKind'

// The home of MM OS: an app-launcher grid where each service is a tile — a
// large service mark with its name underneath, like a phone home screen.
// Tiles come straight from /api/me — never filtered client-side, the server
// already returned only what this person may open (agents/A3-shell.md).
// A tap routes through useLaunchService: embeddable services open inside MM OS
// on the Dashboard (authenticated in-frame), external services open in a new tab.
export function ServicesPage() {
  const { me } = useAuth()
  const { launch, pending, error, clearError } = useLaunchService()
  if (!me) return null
  const mail = me.mail ?? []

  return (
    <div className="page">
      <div className="head">
        <h1>Services</h1>
      </div>
      {me.services.length === 0 ? (
        <div className="card">
          <div className="card-b flush">
            <EmptyState title="No services yet" hint="Raise a request and IT will set you up." />
          </div>
        </div>
      ) : (
        <>
          {error ? (
            <div className="form-err" style={{ marginBottom: 'var(--gap)' }}>
              {error.message}{' '}
              <button className="btn-q" style={{ marginLeft: 8 }} onClick={clearError}>
                Dismiss
              </button>
            </div>
          ) : null}
          <div className="app-grid">
            {me.services.map((s) => {
              const isPending = pending === s.slug
              const newTab = s.launch_mode === 'external'
              return (
                <button
                  key={s.slug}
                  className="app-tile"
                  onClick={() => launch(s)}
                  disabled={isPending}
                  title={newTab ? `Open ${s.name} in a new tab` : `Open ${s.name}`}
                >
                  <span className="app-tile-icon">
                    <ServiceMark slug={s.slug} name={s.name} kind={kindFromLaunchMode(s.launch_mode)} size={48} />
                  </span>
                  <div className="app-tile-content">
                    <span className="app-tile-name">{s.name}</span>
                    <span className={`app-tile-role ${s.role.toLowerCase()}`}>{isPending ? 'Opening…' : s.role}</span>
                  </div>
                  <span className="app-tile-arrow">
                    {newTab ? (
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
                    ) : (
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="5" y1="12" x2="19" y2="12"></line><polyline points="12 5 19 12 12 19"></polyline></svg>
                    )}
                  </span>
                </button>
              )
            })}
          </div>
        </>
      )}

      {mail.length > 0 ? (
        <>
          <div className="head" style={{ marginTop: 'var(--gap)' }}>
            <h2>Mail</h2>
          </div>
          {/* Gmail will not load inside another site, so each mailbox opens in its own tab,
              on that Google account if this browser is signed into it. */}
          <div className="app-grid">
            {mail.map((m) => (
              <a key={m.email} className="app-tile" href={m.url} target="_blank" rel="noopener noreferrer" title={`Open ${m.email} in a new tab`} style={{ textDecoration: 'none' }}>
                <span className="app-tile-icon">
                  <ServiceMark slug={m.kind === 'own' ? 'mail' : 'mail-dept'} name={m.label} kind="third-party" size={48} />
                </span>
                <div className="app-tile-content">
                  <span className="app-tile-name">{m.label}</span>
                  <span className="app-tile-role user" style={{ textTransform: 'none' }}>{m.email}</span>
                </div>
                <span className="app-tile-arrow">
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path><polyline points="15 3 21 3 21 9"></polyline><line x1="10" y1="14" x2="21" y2="3"></line></svg>
                </span>
              </a>
            ))}
          </div>
        </>
      ) : null}
    </div>
  )
}
