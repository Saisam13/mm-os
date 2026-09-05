import React, { useEffect, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { mmosApi } from '../api'
import type { PublicService } from '../api/types'
import { ApiRequestError } from '../api/types'

// One page: the logo lockup, the two sign-in methods, and the PIN / Google
// flow. Restyled to the workspace design language — calm, light, petrol
// accent — but the authentication behaviour is unchanged: the User / Admin
// choice only steers the post-login redirect and the Google `next` param.
export function EntryPage() {
  const { me, loading, refresh } = useAuth()
  const navigate = useNavigate()
  const [, setServices] = useState<PublicService[] | null>(null)
  const [code, setCode] = useState('')
  const [pin, setPin] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)
  const [loginType, setLoginType] = useState<'user' | 'admin' | null>(null)

  useEffect(() => {
    mmosApi.getPublicServices().then(setServices).catch(() => setServices(null))
  }, [])

  if (!loading && me) return <Navigate to="/services" replace />

  async function submitPin(e: React.FormEvent) {
    e.preventDefault()
    setFormError(null)
    setSubmitting(true)
    try {
      await mmosApi.signInWithPin(code.trim(), pin)
      await refresh()
      // Everyone lands on the Services app-grid — the home of MM OS. Admins
      // still reach /admin from the top nav; this is just where sign-in drops you.
      navigate('/services')
    } catch (err) {
      if (err instanceof ApiRequestError) {
        if (err.error === 'account_locked') setFormError('This account is locked. Contact IT.')
        else if (err.error === 'unknown_user') setFormError('No account matches that employee code.')
        else if (err.error === 'wrong_pin') setFormError('That PIN is not correct.')
        else setFormError(err.message)
      } else {
        setFormError('Could not reach MM OS. Check the network and try again.')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="entry-hero">
      <div className="entry-panel">
        <div className="entry-brand">
          <svg width="44" height="44" viewBox="0 0 34 34" aria-hidden="true">
            <circle cx="11" cy="17" r="7.4" fill="none" stroke="var(--petrol)" strokeWidth="2.4" />
            <path d="M7.6 17h6.8M11 13.6v6.8" stroke="var(--petrol)" strokeWidth="2.4" strokeLinecap="round" />
            <circle cx="25" cy="17" r="7.4" fill="none" stroke="var(--petrol)" strokeWidth="2.4" />
            <path d="M21.6 17h6.8" stroke="var(--petrol)" strokeWidth="2.4" strokeLinecap="round" />
          </svg>
          <span className="logo-type">
            <span className="l1">MINI</span>
            <span className="l2">MINES</span>
            <span className="tag">Extracting what matters</span>
          </span>
        </div>

        {!loginType ? (
          <div className="entry-choice">
            <div className="entry-eyebrow">MM OS</div>
            <button className="choice-btn" onClick={() => setLoginType('user')}>
              <span className="ic"><UserIcon /></span>
              <span>
                User access
                <span className="sub">Sign in to your services</span>
              </span>
              <span className="choice-arrow"><ArrowRight /></span>
            </button>
            <button className="choice-btn" onClick={() => setLoginType('admin')}>
              <span className="ic"><ShieldIcon /></span>
              <span>
                Administrator
                <span className="sub">Platform and access console</span>
              </span>
              <span className="choice-arrow"><ArrowRight /></span>
            </button>
          </div>
        ) : (
          <div>
            <button className="entry-back" onClick={() => { setLoginType(null); setFormError(null) }}>
              <ArrowLeft /> Back
            </button>
            <h2 className="entry-title">{loginType === 'admin' ? 'Administrator sign-in' : 'User sign-in'}</h2>

            <a className="btn-g" href={mmosApi.googleStartUrl('/services')}>
              <svg width="18" height="18" viewBox="0 0 18 18" aria-hidden="true">
                <path fill="#4285F4" d="M17.6 9.2c0-.6-.1-1.3-.2-1.8H9v3.5h4.8a4.1 4.1 0 0 1-1.8 2.7v2.2h2.9c1.7-1.6 2.7-3.9 2.7-6.6z" />
                <path fill="#34A853" d="M9 18c2.4 0 4.5-.8 6-2.2l-2.9-2.2c-.8.5-1.8.9-3.1.9-2.4 0-4.4-1.6-5.2-3.8H.8v2.3A9 9 0 0 0 9 18z" />
                <path fill="#FBBC05" d="M3.8 10.7a5.4 5.4 0 0 1 0-3.4V5H.8a9 9 0 0 0 0 8l3-2.3z" />
                <path fill="#EA4335" d="M9 3.6c1.3 0 2.5.5 3.4 1.3l2.6-2.6A9 9 0 0 0 .8 5l3 2.3C4.6 5.2 6.6 3.6 9 3.6z" />
              </svg>
              Continue with Google
            </a>

            <div className="rule">or employee code</div>

            <form onSubmit={submitPin}>
              {formError ? <div className="form-err">{formError}</div> : null}
              <div className="f2">
                <div>
                  <label className="fl" htmlFor="ec">Employee code</label>
                  <input id="ec" className="fi" value={code} onChange={(e) => setCode(e.target.value)} required autoComplete="username" />
                </div>
                <div>
                  <label className="fl" htmlFor="pin">PIN</label>
                  <input id="pin" className="fi" type="password" value={pin} onChange={(e) => setPin(e.target.value)} required autoComplete="current-password" />
                </div>
              </div>
              <button type="submit" className="btn-p" disabled={submitting}>
                {submitting ? 'Signing in…' : 'Sign in'}
              </button>
            </form>
          </div>
        )}
      </div>
    </div>
  )
}

/* ── inline icons (no icon-font dependency) ── */
const UserIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg>
)
const ShieldIcon = () => (
  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /></svg>
)
const ArrowRight = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M5 12h14" /><path d="m12 5 7 7-7 7" /></svg>
)
const ArrowLeft = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M19 12H5" /><path d="m12 19-7-7 7-7" /></svg>
)
