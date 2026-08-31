import React, { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { canEmbed } from '../lib/useLaunchService'
import { ServiceMark } from '../components/ServiceMark'
import { kindFromLaunchMode } from '../lib/serviceKind'
import type { MeService } from '../api/types'

// The workspace: a sidebar of the person's services on the left, the active
// app on the right. When a service is genuinely frameable (canEmbed —
// launch_mode 'embed' AND not an http target from an https page, see
// lib/useLaunchService.ts) it embeds in an iframe. When it is not, the main
// area shows an explicit "opens in its own window" panel with a Launch
// button — never a blank frame. This is the deliberate contrast with the
// Services page, which always opens a new tab.
export function Dashboard() {
  const { me } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const appParam = searchParams.get('app')

  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [maximized, setMaximized] = useState(false)

  const active: MeService | null =
    (me && appParam && me.services.find((s) => s.slug === appParam)) || null

  // Reset full-screen whenever the selected app changes.
  useEffect(() => { setMaximized(false) }, [appParam])

  if (!me) return null

  const select = (s: MeService) => setSearchParams({ app: s.slug })
  const embeds = active ? canEmbed(active) : false

  return (
    <div className="ws">
      <aside className={`ws-side${sidebarOpen ? '' : ' collapsed'}`}>
        <div className="ws-side-hd">
          <span className="t">Workspace</span>
          <button className="ws-iconbtn" onClick={() => setSidebarOpen(false)} title="Hide sidebar" aria-label="Hide sidebar">
            <ChevronLeft />
          </button>
        </div>
        <div className="ws-list">
          {me.services.length === 0 ? (
            <div className="ws-list-empty">
              <div className="t">No services yet</div>
              <div>Raise a request and IT will set you up.</div>
            </div>
          ) : (
            me.services.map((s) => (
              <button
                key={s.slug}
                className={`ws-svc${active?.slug === s.slug ? ' active' : ''}`}
                onClick={() => select(s)}
              >
                <ServiceMark slug={s.slug} name={s.name} kind={kindFromLaunchMode(s.launch_mode)} size={34} />
                <span className="g">
                  <span className="nm">{s.name}</span>
                  <span className="rl">{s.role}</span>
                </span>
              </button>
            ))
          )}
        </div>
      </aside>

      <main className={`ws-main${sidebarOpen ? '' : ' collapsed'}`}>
        {!sidebarOpen && (
          <div className="ws-reveal">
            <button className="ws-iconbtn raised" onClick={() => setSidebarOpen(true)} title="Show sidebar" aria-label="Show sidebar">
              <Menu />
            </button>
          </div>
        )}

        {!active ? (
          <div className="ws-center">
            <div className="ws-empty">
              <span className="icon"><PanelIcon /></span>
              <div className="t">{me.services.length === 0 ? 'No services yet' : 'No app open'}</div>
              <div className="s">
                {me.services.length === 0
                  ? 'Raise a request and IT will set you up.'
                  : 'Select a service from the sidebar.'}
              </div>
            </div>
          </div>
        ) : embeds ? (
          <div className={`ws-embed${maximized ? ' max' : ''}`}>
            <div className="ws-appbar">
              <div className="ttl">
                <h2>{active.name}</h2>
                <span className="chip cond">{active.role}</span>
              </div>
              <div className="actions">
                <button className="btn-icon" onClick={() => setMaximized((v) => !v)} title={maximized ? 'Exit full screen' : 'Full screen'}>
                  {maximized ? <Minimize /> : <Maximize />}
                  {maximized ? 'Exit full screen' : 'Full screen'}
                </button>
                <a className="btn-icon" href={active.base_url} target="_blank" rel="noopener noreferrer">
                  <External /> Open tab
                </a>
              </div>
            </div>
            {/* Same iframe configuration as ServiceOpenPage — internal,
                backend-vetted (embed) target on a VPN-only deployment. The
                fork's `allow-scripts allow-same-origin` sandbox is deliberately
                not adopted (that pairing lets a frame drop its own sandbox). */}
            <iframe
              src={active.base_url}
              title={active.name}
              className="ws-frame"
            />
          </div>
        ) : (
          <div className="ws-center">
            <div className="ws-launch">
              <ServiceMark slug={active.slug} name={active.name} kind={kindFromLaunchMode(active.launch_mode)} size={56} />
              <h2>{active.name}</h2>
              <p>Opens in its own window. This service runs its own session and cannot be embedded here.</p>
              <a className="btn-launch" href={active.base_url} target="_blank" rel="noopener noreferrer">
                Launch {active.name} <ArrowRight />
              </a>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

/* ── inline icons (no icon-font dependency) ── */
const ChevronLeft = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m15 18-6-6 6-6" /></svg>
)
const Menu = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><line x1="3" y1="6" x2="21" y2="6" /><line x1="3" y1="12" x2="21" y2="12" /><line x1="3" y1="18" x2="21" y2="18" /></svg>
)
const PanelIcon = () => (
  <svg width="56" height="56" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="2" /><line x1="9" y1="3" x2="9" y2="21" /></svg>
)
const Maximize = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M8 3H5a2 2 0 0 0-2 2v3" /><path d="M21 8V5a2 2 0 0 0-2-2h-3" /><path d="M3 16v3a2 2 0 0 0 2 2h3" /><path d="M16 21h3a2 2 0 0 0 2-2v-3" /></svg>
)
const Minimize = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M8 3v3a2 2 0 0 1-2 2H3" /><path d="M21 8h-3a2 2 0 0 1-2-2V3" /><path d="M3 16h3a2 2 0 0 1 2 2v3" /><path d="M16 21v-3a2 2 0 0 1 2-2h3" /></svg>
)
const External = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /><polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" /></svg>
)
const ArrowRight = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12h14" /><path d="m12 5 7 7-7 7" /></svg>
)
