import React, { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { canEmbed } from '../lib/useLaunchService'
import { ServiceMark } from '../components/ServiceMark'
import { kindFromLaunchMode } from '../lib/serviceKind'
import { mmosApi } from '../api'
import type { MeService } from '../api/types'
import { ApiRequestError } from '../api/types'

// The workspace: a sidebar of the person's services on the left, the active
// app on the right. When a service is genuinely frameable (canEmbed —
// launch_mode 'embed' AND not an http target from an https page, see
// lib/useLaunchService.ts) MM OS mints a short-lived service token and points
// the iframe at the `/_mmos/accept#token=…` handoff URL, so the service is
// authenticated *inside the frame* rather than showing its own login. When a
// service is not frameable, the main area shows an explicit "opens in its own
// window" panel with a Launch button — never a blank frame.
export function Dashboard() {
  const { me } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()
  const appParam = searchParams.get('app')

  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [maximized, setMaximized] = useState(false)
  const [searchQuery, setSearchQuery] = useState('')

  // The authenticated handoff URL for the active embeddable app. `null` while
  // there is nothing to frame or while a mint is in flight.
  const [frameUrl, setFrameUrl] = useState<string | null>(null)
  const [minting, setMinting] = useState(false)
  const [mintError, setMintError] = useState<string | null>(null)
  // Bumping this re-runs the mint effect — used by the "Try again" affordance.
  const [retryTick, setRetryTick] = useState(0)

  const active: MeService | null =
    (me && appParam && me.services.find((s) => s.slug === appParam)) || null

  // Reset full-screen whenever the selected app changes.
  useEffect(() => { setMaximized(false) }, [appParam])

  const embeds = active ? canEmbed(active) : false
  // External services own their own session and never take an MM OS token.
  // Everything else — embed AND handoff — is signed in with a minted token, so
  // both need one. Handoff used to fall through to a bare-URL "launch" that
  // carried no token, which just bounced the visitor back to the MM OS login.
  const external = active?.launch_mode === 'external'
  const needsToken = !!active && !external

  // Mint a fresh token whenever a token-taking app becomes active (or the user
  // switches apps, or retries). The token is short-lived, so it is re-minted
  // per app rather than cached. `cancelled` guards against a slow mint landing
  // after the user has already moved to another app.
  useEffect(() => {
    if (!active || !needsToken) {
      setFrameUrl(null)
      setMinting(false)
      setMintError(null)
      return
    }
    let cancelled = false
    setFrameUrl(null)
    setMintError(null)
    setMinting(true)
    mmosApi
      .mintServiceToken(active.slug)
      .then((token) => {
        if (cancelled) return
        setFrameUrl(token.launch_url)
      })
      .catch((e) => {
        if (cancelled) return
        const message = e instanceof ApiRequestError
          ? (e.status === 403 ? 'You cannot open this — the access was removed.' : e.message)
          : 'Could not reach MM OS to open this service.'
        setMintError(message)
      })
      .finally(() => {
        if (!cancelled) setMinting(false)
      })
    return () => { cancelled = true }
  }, [active?.slug, embeds, retryTick])

  if (!me) return null

  const select = (s: MeService) => setSearchParams({ app: s.slug })

  const filteredServices = me.services.filter(s => 
    s.name.toLowerCase().includes(searchQuery.toLowerCase()) || 
    s.role.toLowerCase().includes(searchQuery.toLowerCase())
  )

  return (
    <div className="ws">
      <aside className={`ws-side${sidebarOpen ? '' : ' collapsed'}`}>
        <div className="ws-side-hd">
          <span className="t">Workspace</span>
          <button className="ws-iconbtn" onClick={() => setSidebarOpen(false)} title="Hide sidebar" aria-label="Hide sidebar">
            <ChevronLeft />
          </button>
        </div>
        
        <div style={{ padding: '0 12px 8px' }}>
          <div style={{ display: 'flex', alignItems: 'center', background: 'var(--surface-2)', borderRadius: 6, padding: '6px 10px', border: '1px solid var(--border)' }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--text-3)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ marginRight: 8 }}><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
            <input 
              type="text" 
              placeholder="Search apps..." 
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{ background: 'transparent', border: 'none', color: 'var(--text)', fontSize: 13, outline: 'none', width: '100%' }}
            />
          </div>
        </div>

        <div className="ws-list">
          {me.services.length === 0 ? (
            <div className="ws-list-empty">
              <div className="t" style={{color: 'var(--text)'}}>Welcome to MM OS!</div>
              <div style={{color: 'var(--text-3)', lineHeight: '1.4'}}>You don't have any apps yet. Please contact your IT administrator to request access.</div>
            </div>
          ) : filteredServices.length === 0 ? (
             <div className="ws-list-empty" style={{color: 'var(--text-3)'}}>
               <div>No apps found for "{searchQuery}"</div>
             </div>
          ) : (
            filteredServices.map((s) => (
              <button
                key={s.slug}
                className={`ws-svc${active?.slug === s.slug ? ' active' : ''}`}
                onClick={() => select(s)}
              >
                <ServiceMark slug={s.slug} name={s.name} icon={s.icon} kind={kindFromLaunchMode(s.launch_mode)} size={34} />
                <span className="g">
                  <span className="nm">{s.name}</span>
                  <span className="rl">{s.role.replace(/_/g, ' ')}</span>
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
              <div className="t">{me.services.length === 0 ? 'Welcome to MM OS!' : 'No app open'}</div>
              <div className="s">
                {me.services.length === 0
                  ? "You don't have any apps yet. Please contact your IT administrator."
                  : 'Select an app from the sidebar.'}
              </div>
            </div>
          </div>
        ) : embeds ? (
          <div className={`ws-embed${maximized ? ' max' : ''}`}>
            {!maximized && (
              <div className="ws-appbar">
                <div className="ttl">
                  <h2>{active.name}</h2>
                  <span className="chip cond">{active.role}</span>
                </div>
                <div className="actions">
                  <button className="btn-icon" onClick={() => setMaximized(true)} title="Full screen">
                    <Maximize /> Full screen
                  </button>
                  <a className="btn-icon" href={frameUrl ?? active.base_url} target="_blank" rel="noopener noreferrer">
                    <External /> Open tab
                  </a>
                </div>
              </div>
            )}
            
            {maximized && (
              <button className="ws-float-close" onClick={() => setMaximized(false)} title="Exit full screen" aria-label="Exit full screen">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
              </button>
            )}

            {/* Authenticated in-frame: the src is the minted `/_mmos/accept
                #token=…` handoff URL, not the bare base_url, so the service
                signs the visitor in inside the frame. Same iframe config as
                ServiceOpenPage — internal, backend-vetted (embed) target. The
                fork's `allow-scripts allow-same-origin` sandbox is deliberately
                not adopted (that pairing lets a frame drop its own sandbox). */}
            {frameUrl ? (
              <iframe
                key={active.slug}
                src={frameUrl}
                title={active.name}
                className="ws-frame"
              />
            ) : mintError ? (
              <div className="ws-center">
                <div className="ws-launch">
                  <ServiceMark slug={active.slug} name={active.name} icon={active.icon} kind={kindFromLaunchMode(active.launch_mode)} size={56} />
                  <h2>Could not open {active.name}</h2>
                  <p>{mintError}</p>
                  <div className="row-actions">
                    <button className="btn-launch" onClick={() => setRetryTick((v) => v + 1)}>
                      Try again
                    </button>
                    <a className="btn-q" href={active.base_url} target="_blank" rel="noopener noreferrer">
                      Open in new tab
                    </a>
                  </div>
                </div>
              </div>
            ) : (
              <div className="ws-center">
                <div className="ws-empty">
                  <span className="icon"><PanelIcon /></span>
                  <div className="t">Opening {active.name}…</div>
                  <div className="s">Signing you in securely.</div>
                </div>
              </div>
            )}
          </div>
        ) : external ? (
          <div className="ws-center">
            <div className="ws-launch">
              <ServiceMark slug={active.slug} name={active.name} icon={active.icon} kind={kindFromLaunchMode(active.launch_mode)} size={56} />
              <h2>{active.name}</h2>
              <p>Opens in its own window. This service runs its own session.</p>
              <a className="btn-launch" href={active.base_url} target="_blank" rel="noopener noreferrer">
                Launch {active.name} <ArrowRight />
              </a>
            </div>
          </div>
        ) : (
          // Handoff: an MM OS service that can't (or shouldn't) be framed. We
          // still owe it a token — mint one and open the authenticated
          // `/_mmos/accept#token=…` launch URL in a new tab. Opening it
          // top-level rather than in an iframe keeps the service's session
          // cookie first-party, so it is set reliably even in browsers that
          // block third-party cookies (which an embedded handoff cannot rely
          // on). This is the path that was silently dropping the token before.
          <div className="ws-center">
            <div className="ws-launch">
              <ServiceMark slug={active.slug} name={active.name} icon={active.icon} kind={kindFromLaunchMode(active.launch_mode)} size={56} />
              <h2>{active.name}</h2>
              {mintError ? (
                <>
                  <p>{mintError}</p>
                  <div className="row-actions">
                    <button className="btn-launch" onClick={() => setRetryTick((v) => v + 1)}>
                      Try again
                    </button>
                  </div>
                </>
              ) : frameUrl ? (
                <>
                  <p>Opens in a new tab, already signed in.</p>
                  <a className="btn-launch" href={frameUrl} target="_blank" rel="noopener noreferrer">
                    Launch {active.name} <ArrowRight />
                  </a>
                </>
              ) : (
                <p>Preparing your secure sign-in…</p>
              )}
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
