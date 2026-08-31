import React from 'react'
import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { TopNav } from '../components/TopNav'

// Everything behind sign-in shares the top nav. A 401 anywhere clears `me`
// in AuthContext, which sends the visitor back to the entry page from here.
export function ProtectedLayout() {
  const { me, loading } = useAuth()
  if (loading) return null
  if (!me) return <Navigate to="/" replace />
  return (
    <div className="console">
      <TopNav />
      <div className="body">
        <Outlet />
      </div>
    </div>
  )
}

// Admin screens are unreachable and invisible for a non-admin
// (agents/A3-shell.md Acceptance) — this is the one gate every admin
// route passes through.
export function AdminGuard() {
  const { me, loading } = useAuth()
  if (loading) return null
  if (!me) return <Navigate to="/" replace />
  if (!me.user.is_platform_admin) return <Navigate to="/dashboard" replace />
  return <Outlet />
}
