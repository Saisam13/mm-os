import React from 'react'
import { NavLink, Outlet } from 'react-router-dom'

// brand/UI-DECISIONS.md's Console direction only reserves top-nav real
// estate for Services / Service Desk / Access / AI services. People, the
// service registry and Audit have no designed chrome of their own, so they
// are grouped here as tabs under "Access" — the same `.tabs` idiom the
// locked prototype already uses for Service Desk's four views. Recorded
// under handoff/a3-shell.md "Assumptions".
const TABS = [
  { to: '/admin/access', label: 'Access' },
  { to: '/admin/people', label: 'People' },
  { to: '/admin/accounts', label: 'Accounts' },
  { to: '/admin/services', label: 'Services' },
  { to: '/admin/audit', label: 'Audit' },
]

export function AdminTabs() {
  return (
    <div className="page">
      <div className="tabs">
        {TABS.map((t) => (
          <NavLink key={t.to} to={t.to} className={({ isActive }) => `tab${isActive ? ' sel' : ''}`}>
            {t.label}
          </NavLink>
        ))}
      </div>
      <Outlet />
    </div>
  )
}
