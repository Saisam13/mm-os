import React, { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { useNavigate } from 'react-router-dom'

// agents/A3-shell.md: "who you are, your department, band, approval level,
// your services and roles, your active sessions with a sign-out-everywhere
// button." docs/03-api-contract.md has no endpoint that lists or revokes a
// user's own sessions beyond the current one (POST /api/auth/logout clears
// only the calling session) — see handoff/a3-shell.md "Contract objections".
// The sessions list is therefore not fabricated; the gap is stated plainly.
export function ProfilePage() {
  const { me, signOut } = useAuth()
  const navigate = useNavigate()
  const [signingOut, setSigningOut] = useState(false)
  if (!me) return null

  async function handleSignOut() {
    setSigningOut(true)
    await signOut()
    navigate('/')
  }

  return (
    <div className="page">
      <div className="head">
        <h1>Profile</h1>
      </div>

      <div className="card">
        <div className="card-h">
          <div>
            <div className="eyebrow">{me.user.employee_code}</div>
            <h2>{me.user.name}</h2>
          </div>
        </div>
        <div className="card-b">
          <dl className="kv">
            <dt>Department</dt><dd>{me.user.department}</dd>
            <dt>Division</dt><dd>{me.user.division}</dd>
            <dt>Band</dt><dd className="cond">{me.user.band}</dd>
            <dt>Approval level</dt><dd>{me.user.approval_level ?? '—'}</dd>
            <dt>Sign-in method</dt><dd>{me.user.auth_type === 'google' ? 'Google' : 'Employee code + PIN'}</dd>
            <dt>Email</dt><dd>{me.user.email ?? '—'}</dd>
          </dl>
        </div>
      </div>

      <div className="card">
        <div className="card-h">
          <div><div className="eyebrow">{me.services.length} services</div><h2>Services and roles</h2></div>
        </div>
        <div className="card-b flush">
          {me.services.length === 0 ? (
            <div className="empty"><div className="t">No services granted.</div></div>
          ) : (
            <div className="tw">
              <table>
                <thead><tr><th>Service</th><th>Role</th><th>Status</th></tr></thead>
                <tbody>
                  {me.services.map((s) => (
                    <tr key={s.slug}>
                      <td>{s.name}</td>
                      <td className="tight"><span className="chip">{s.role}</span></td>
                      <td className="tight"><span className={`dot${s.health === 'up' ? '' : ' w'}`} /> {s.health}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      <div className="card">
        <div className="card-h"><div><h2>Active sessions</h2></div></div>
        <div className="card-b">
          <p className="muted" style={{ fontSize: 13, marginBottom: 14 }}>
            Session-by-session detail is not exposed by the API. Sign-out-everywhere below ends
            the current session; a session listing endpoint would be needed for the rest.
          </p>
          <button className="btn-q btn-danger" onClick={handleSignOut} disabled={signingOut}>
            {signingOut ? 'Signing out…' : 'Sign out everywhere'}
          </button>
        </div>
      </div>
    </div>
  )
}
