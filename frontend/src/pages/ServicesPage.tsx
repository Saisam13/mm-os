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
                    <ServiceMark slug={s.slug} name={s.name} kind={kindFromLaunchMode(s.launch_mode)} size={72} />
                  </span>
                  <span className="app-tile-name">{s.name}</span>
                  <span className="app-tile-role">{isPending ? 'Opening…' : s.role}</span>
                </button>
              )
            })}
          </div>
        </>
      )}
    </div>
  )
}
