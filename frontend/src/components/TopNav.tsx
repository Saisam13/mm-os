import React, { useEffect, useRef, useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { deriveInitials } from '../lib/initials'
import { useLaunchService } from '../lib/useLaunchService'
import { CommandPalette, type PaletteItem } from './CommandPalette'

// Direction B, locked: a 60px navy sticky bar, logo lockup, Services ·
// Service Desk · Access · AI services as flat text buttons, a spacer,
// Search, avatar chip. brand/UI-DECISIONS.md § Console direction. Access
// and AI services only render for a platform admin — the brief's
// acceptance criterion that admin screens are invisible for anyone else.
export function TopNav() {
  const { me, signOut } = useAuth()
  const location = useLocation()
  const navigate = useNavigate()
  const { launch } = useLaunchService()
  const [palOpen, setPalOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPalOpen(true)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    if (!menuOpen) return
    const onClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [menuOpen])

  if (!me) return null

  const desk = me.services.find((s) => s.slug === 'desk')
  const isAdmin = me.user.is_platform_admin
  const sel = (path: string) => (location.pathname.startsWith(path) ? ' sel' : '')

  const paletteItems: PaletteItem[] = [
    // A service picked from the palette opens in the workspace (Dashboard),
    // where it embeds if frameable and otherwise offers a launch panel.
    ...me.services.map((s) => ({ id: `svc-${s.slug}`, label: s.name, kind: s.role, run: () => navigate(`/dashboard?app=${s.slug}`) })),
    { id: 'nav-dashboard', label: 'Dashboard', kind: 'page', run: () => navigate('/dashboard') },
    { id: 'nav-services', label: 'Services', kind: 'page', run: () => navigate('/services') },
    { id: 'nav-profile', label: 'Profile', kind: 'page', run: () => navigate('/profile') },
    ...(isAdmin
      ? [
          { id: 'nav-access', label: 'Access', kind: 'page', run: () => navigate('/admin/access') },
          { id: 'nav-people', label: 'People', kind: 'page', run: () => navigate('/admin/people') },
          { id: 'nav-svcadmin', label: 'Services (admin)', kind: 'page', run: () => navigate('/admin/services') },
          { id: 'nav-audit', label: 'Audit', kind: 'page', run: () => navigate('/admin/audit') },
          { id: 'nav-ai', label: 'AI services', kind: 'page', run: () => navigate('/ai') },
        ]
      : []),
  ]

  const initials = me.user.name.split(/\s+/).map((w) => w[0]).slice(0, 2).join('').toUpperCase()

  return (
    <>
      <header className="topnav">
        <Link to="/dashboard" className="logo">
          <svg className="logo-mark" width="24" height="24" viewBox="0 0 34 34" aria-hidden="true">
            <circle cx="11" cy="17" r="7.4" fill="none" stroke="#fff" strokeWidth="2.6" />
            <path d="M7.6 17h6.8M11 13.6v6.8" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" />
            <circle cx="25" cy="17" r="7.4" fill="none" stroke="#fff" strokeWidth="2.6" />
            <path d="M21.6 17h6.8" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" />
          </svg>
          <span className="logo-type">
            <span className="l1">MINI</span>
            <span className="l2">MINES</span>
          </span>
        </Link>

        <Link to="/dashboard" className={`topnav-i${sel('/dashboard')}`}>
          Dashboard
        </Link>
        <Link to="/services" className={`topnav-i${sel('/services')}`}>
          Services
        </Link>
        {desk ? (
          <button className="topnav-i" onClick={() => launch(desk)}>
            Service Desk{me.badges.servicedesk_open > 0 ? <span className="cond" style={{ marginLeft: 6, color: 'var(--orange)' }}>{me.badges.servicedesk_open}</span> : null}
          </button>
        ) : null}
        {isAdmin ? (
          <Link to="/admin/access" className={`topnav-i${sel('/admin')}`}>
            Access
          </Link>
        ) : null}
        {isAdmin ? (
          <Link to="/ai" className={`topnav-i${sel('/ai')}`}>
            AI services
          </Link>
        ) : null}

        <div className="topnav-sp" />
        <button className="topnav-i" onClick={() => setPalOpen(true)}>
          Search
        </button>
        <div className="topnav-avatar" ref={menuRef}>
          <button className="avatar-btn" onClick={() => setMenuOpen((v) => !v)} aria-label="Account menu">
            <span className="chip pet cond">{initials}</span>
          </button>
          <div className={`avatar-menu${menuOpen ? ' on' : ''}`} role="menu">
            <div className="avatar-menu-hd">
              <div className="nm">{me.user.name}</div>
              <div className="mt cond">{me.user.employee_code} · {me.user.department}</div>
            </div>
            <button className="pal-i" role="menuitem" onClick={() => { setMenuOpen(false); navigate('/profile') }}>
              Profile
            </button>
            <button className="pal-i" role="menuitem" onClick={() => { setMenuOpen(false); signOut() }}>
              Sign out
            </button>
          </div>
        </div>
      </header>
      <CommandPalette open={palOpen} onClose={() => setPalOpen(false)} items={paletteItems} />
    </>
  )
}
