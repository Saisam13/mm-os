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
  if (me.user.must_change_pin) return <Navigate to="/change-pin" replace />
  // First Google sign-in: confirm the employee code and set a PIN before anything else.
  if (me.user.needs_onboarding) return <Navigate to="/welcome" replace />
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
  if (!me.user.is_platform_admin && !(me.user.capabilities?.length)) return <Navigate to="/services" replace />
  return <Outlet />
}
