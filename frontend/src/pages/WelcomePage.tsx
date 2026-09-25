import React, { useEffect, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { mmosApi } from '../api'
import type { OnboardStatus } from '../api/types'
import { ApiRequestError } from '../api/types'

// First Google sign-in (backend app/onboarding.py): confirm your employee code and
// choose a PIN, once. Three ways to land here:
//   • session  - signed in with your official email; just confirm the code and set a PIN
//   • personal - a personal Gmail the people sheet listed; the code proves it is you
//   • new      - a company address MM OS has not seen; you start with basic access
export function WelcomePage() {
  const { me, loading, refresh } = useAuth()
  const navigate = useNavigate()
  const [status, setStatus] = useState<OnboardStatus | null>(null)
  const [code, setCode] = useState('')
  const [pin, setPin] = useState('')
  const [pin2, setPin2] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    mmosApi.onboardStatus().then(setStatus).catch(() => setStatus({ mode: 'none' }))
  }, [])

  if (loading || status === null) return null
  if (status.mode === 'none') {
    return <Navigate to={me && !me.user.needs_onboarding ? '/services' : '/'} replace />
  }

  const existingPin = status.mode === 'personal' && status.has_pin

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setErr(null)
    if (!/^\d{4,8}$/.test(pin)) { setErr('The PIN must be 4 to 8 digits.'); return }
    if (!existingPin && pin !== pin2) { setErr('The two PINs do not match.'); return }
    setBusy(true)
    try {
      const r = await mmosApi.onboard(code.trim(), pin)
      await refresh()
      navigate(r.next || '/services', { replace: true })
    } catch (x) {
      if (x instanceof ApiRequestError) {
        if (x.error === 'onboard_expired') setErr('This sign-in has expired. Go back and continue with Google again.')
        else if (x.error === 'invalid_credentials') setErr('That PIN is not correct.')
        else setErr(x.message)
      } else {
        setErr('Could not reach MM OS. Check the network and try again.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="entry-hero">
      <div className="entry-panel">
        <div className="entry-eyebrow">MM OS · first sign-in</div>
        <h2 className="entry-title">Welcome{status.name ? `, ${status.name}` : ''}</h2>
        {status.email ? (
          <p className="muted" style={{ fontSize: 13, marginTop: -4 }}>Signed in with Google as <strong>{status.email}</strong></p>
        ) : null}
        <p style={{ fontSize: 14, lineHeight: 1.5 }}>
          {status.mode === 'session' && 'Confirm your employee code and choose a PIN. After this you can sign in with Google, or with your employee code and PIN on a shared computer.'}
          {status.mode === 'personal' && (existingPin
            ? 'This is a personal Google account. Type your employee code and your current PIN to link it to your MM OS account.'
            : 'This is a personal Google account. Type your employee code to prove it is yours, and choose a PIN.')}
          {status.mode === 'new' && 'You are not set up in MM OS yet. Type your employee code and choose a PIN. You start with basic access; ask IT if you need more.'}
        </p>

        <form onSubmit={submit}>
          {err ? <div className="form-err">{err}</div> : null}
          <label className="fl" htmlFor="w-code">Employee code</label>
          <input id="w-code" className="fi" value={code} onChange={(e) => setCode(e.target.value)} placeholder="MM115" required autoComplete="username" />
          <div className="f2" style={{ marginTop: 10 }}>
            <div>
              <label className="fl" htmlFor="w-pin">{existingPin ? 'Current PIN' : 'New PIN (4–8 digits)'}</label>
              <input id="w-pin" className="fi" type="password" inputMode="numeric" value={pin} onChange={(e) => setPin(e.target.value)} required autoComplete={existingPin ? 'current-password' : 'new-password'} />
            </div>
            {existingPin ? null : (
              <div>
                <label className="fl" htmlFor="w-pin2">Repeat PIN</label>
                <input id="w-pin2" className="fi" type="password" inputMode="numeric" value={pin2} onChange={(e) => setPin2(e.target.value)} required autoComplete="new-password" />
              </div>
            )}
          </div>
          <button type="submit" className="btn-p" disabled={busy}>{busy ? 'Saving…' : 'Continue'}</button>
        </form>
      </div>
    </div>
  )
}
