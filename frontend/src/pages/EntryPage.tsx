import React, { useEffect, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { mmosApi } from '../api'
import type { PublicService } from '../api/types'
import { ApiRequestError } from '../api/types'
import { ServiceMark } from '../components/ServiceMark'
import { kindFromSessionOwner } from '../lib/serviceKind'

// One page: logo, the two sign-in methods, then the public service
// directory underneath — docs/01-architecture.md "The entry page, and who
// owns each session". Visible before sign-in, deliberately, on a VPN-only
// deployment.
export function EntryPage() {
  const { me, loading, refresh } = useAuth()
  const navigate = useNavigate()
  const [services, setServices] = useState<PublicService[] | null>(null)
  const [servicesError, setServicesError] = useState<string | null>(null)
  const [code, setCode] = useState('')
  const [pin, setPin] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [formError, setFormError] = useState<string | null>(null)

  useEffect(() => {
    mmosApi
      .getPublicServices()
      .then(setServices)
      .catch(() => setServicesError('Could not reach MM OS to list services.'))
  }, [])

  if (!loading && me) return <Navigate to="/services" replace />

  async function submitPin(e: React.FormEvent) {
    e.preventDefault()
    setFormError(null)
    setSubmitting(true)
    try {
      await mmosApi.signInWithPin(code.trim(), pin)
      await refresh()
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
    <div className="entry">
      <div className="entry-logo">
        <span className="logo">
          <svg className="logo-mark" width="34" height="34" viewBox="0 0 34 34" aria-hidden="true">
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
        </span>
      </div>

      <div className="entry-in">
        <div className="entry-card">
          <a className="btn-g" href={mmosApi.googleStartUrl('/services')}>
            <svg width="16" height="16" viewBox="0 0 18 18" aria-hidden="true">
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
                <label className="fl" htmlFor="ec">Code</label>
                <input
                  className="fi"
                  id="ec"
                  spellCheck={false}
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  autoComplete="username"
                  required
                />
              </div>
              <div>
                <label className="fl" htmlFor="pin">PIN</label>
                <input
                  className="fi"
                  id="pin"
                  type="password"
                  value={pin}
                  onChange={(e) => setPin(e.target.value)}
                  autoComplete="current-password"
                  required
                />
              </div>
            </div>
            <button className="btn-p" type="submit" disabled={submitting}>
              {submitting ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        </div>

        <div className="entry-svcs">
          <div className="lbl">Services</div>
          {servicesError ? (
            <div className="empty"><div className="t">{servicesError}</div></div>
          ) : services === null ? null : services.length === 0 ? (
            <div className="empty"><div className="t">No services registered yet.</div></div>
          ) : (
            services.map((s) => (
              <a key={s.slug} className="svc" href={s.launch_url}>
                <ServiceMark slug={s.slug} name={s.name} kind={kindFromSessionOwner(s.session_owner)} />
                <span><span className="svc-name">{s.name}</span></span>
                <span className="svc-grow" />
                <span className="svc-meta">
                  <span className={`chip${s.session_owner === 'mmos' ? '' : ' cy'}`}>
                    {s.session_owner === 'mmos' ? 'MM OS sign-in' : 'own sign-in'}
                  </span>
                </span>
                <svg className="svc-arrow" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <path d="M9 6l6 6-6 6" />
                </svg>
              </a>
            ))
          )}
        </div>
      </div>
    </div>
  )
}
