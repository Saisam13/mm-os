import React from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../../auth/AuthContext'

// brand/UI-DECISIONS.md's Console direction only reserves top-nav real
// estate for Services / Service Desk / Access / AI services. People, the
// service registry and Audit have no designed chrome of their own, so they
// are grouped here as tabs under "Access" — the same `.tabs` idiom the
// locked prototype already uses for Service Desk's four views. Recorded
// under handoff/a3-shell.md "Assumptions".
const TABS = [
  { to: '/admin/people', label: 'People', any: ['people.view', 'people.create', 'people.edit'] },
  { to: '/admin/agents', label: 'Agents', any: ['agents.manage'] },
  { to: '/admin/departments', label: 'Departments', any: ['departments.assign'] },
  { to: '/admin/roles', label: 'Roles & capabilities', any: ['admin_roles.manage'] },
  { to: '/admin/access', label: 'Service grants', any: ['grants.view', 'grants.add', 'grants.change', 'grants.revoke'] },
  { to: '/admin/services', label: 'Services', any: [] },
  { to: '/admin/audit', label: 'Audit', any: [] },
]

export function AdminTabs() {
  const { me } = useAuth()
  const caps = new Set(me?.user.capabilities || [])
  const tabs = me?.user.is_platform_admin ? TABS : TABS.filter((t) => t.any.some((c) => caps.has(c)))
  return (
    <div className="page">
      <div className="tabs">
        {tabs.map((t) => (
          <NavLink key={t.to} to={t.to} className={({ isActive }) => `tab${isActive ? ' sel' : ''}`}>
            {t.label}
          </NavLink>
        ))}
      </div>
      <Outlet />
    </div>
  )
}
