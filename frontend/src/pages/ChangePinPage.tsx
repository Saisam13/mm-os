import React, { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { mmosApi } from '../api'

export function ChangePinPage() {
  const { me, loading, refresh, signOut } = useAuth()
  const navigate = useNavigate()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [repeat, setRepeat] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  if (loading) return null
  if (!me) return <Navigate to="/" replace />

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    if (next !== repeat) { setError('The new PINs do not match.'); return }
    if (!/^\d{4,8}$/.test(next)) { setError('Use 4 to 8 digits.'); return }
    setBusy(true)
    setError('')
    try {
      await mmosApi.changePin(current, next)
      setCurrent(''); setNext(''); setRepeat('')
      await refresh()
      navigate('/services', { replace: true })
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'Could not change the PIN. Try again.')
    } finally { setBusy(false) }
  }

  return <div className="entry-hero"><div className="entry-panel">
    <div className="entry-eyebrow">MM OS · account security</div>
    <h2 className="entry-title">Change your PIN</h2>
    <p>Your temporary PIN must be changed before you can open services. Other sessions will be signed out.</p>
    <form onSubmit={submit}>
      {error && <div className="form-err" role="alert">{error}</div>}
      <label className="fl" htmlFor="old-pin">Current PIN</label>
      <input id="old-pin" className="fi" type="password" inputMode="numeric" autoComplete="current-password" required value={current} onChange={e => setCurrent(e.target.value)} />
      <label className="fl" htmlFor="new-pin">New PIN</label>
      <input id="new-pin" className="fi" type="password" inputMode="numeric" autoComplete="new-password" required value={next} onChange={e => setNext(e.target.value)} />
      <label className="fl" htmlFor="repeat-pin">Repeat new PIN</label>
      <input id="repeat-pin" className="fi" type="password" inputMode="numeric" autoComplete="new-password" required value={repeat} onChange={e => setRepeat(e.target.value)} />
      <button className="btn-p" type="submit" disabled={busy}>{busy ? 'Saving…' : 'Change PIN'}</button>
    </form>
    <button className="btn" disabled={busy} onClick={() => { void signOut().then(() => navigate('/')) }}>Sign out</button>
  </div></div>
}
