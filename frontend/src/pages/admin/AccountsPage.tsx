import React, { useEffect, useMemo, useState } from 'react'
import { mmosApi } from '../../api'
import type { AccountBulkResult, AccountRosterRow, FunctionalAccount } from '../../api/types'
import { Panel } from '../../components/Panel'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { EmptyState } from '../../components/EmptyState'
import { rowActivation } from '../../lib/a11y'

// The operational "add & customize" surface for FUNCTIONAL-MAILBOX accounts
// (purchase.c2@, central.stores@, sales@ ...) — the counterpart to the CLI
// roster loader (scripts/provision_functional.py). Same look and tokens as the
// other admin pages; this is capability, not a redesign.
export function AccountsPage() {
  const [rows, setRows] = useState<FunctionalAccount[] | null>(null)
  const [dept, setDept] = useState('')
  const [selected, setSelected] = useState<FunctionalAccount | null>(null)
  const [adding, setAdding] = useState(false)
  const [importing, setImporting] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  function reload() {
    mmosApi.admin
      .listAccounts()
      .then(setRows)
      .catch(() => setLoadError('Could not load accounts.'))
  }
  useEffect(reload, [])

  const departments = useMemo(
    () => Array.from(new Set((rows ?? []).map((a) => a.department).filter(Boolean))).sort(),
    [rows],
  )
  const shown = (rows ?? []).filter((a) => !dept || a.department === dept)

  if (loadError) return <EmptyState title={loadError} />

  return (
    <>
      <div className="head">
        <h1>Accounts</h1>
        <div className="row-actions">
          <button className="btn-q" onClick={() => setImporting(true)}>Bulk import</button>
          <button className="btn-act" onClick={() => setAdding(true)}>Add account</button>
        </div>
      </div>

      <div className="filters">
        <div className="field">
          <label htmlFor="a-dept">Department</label>
          <select id="a-dept" value={dept} onChange={(e) => setDept(e.target.value)}>
            <option value="">All</option>
            {departments.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </div>
      </div>

      <div className="card">
        <div className="card-h">
          <div><div className="eyebrow">Functional mailboxes · click a row to customize</div><h2>{shown.length} account{shown.length === 1 ? '' : 's'}</h2></div>
        </div>
        <div className="card-b flush">
          {rows === null ? null : shown.length === 0 ? (
            <EmptyState title="No functional accounts yet" hint="Add one, or paste a roster with Bulk import." />
          ) : (
            <div className="tw">
              <table>
                <thead>
                  <tr><th>Email</th><th>Department</th><th>Approval level</th><th>Head</th><th>Status</th></tr>
                </thead>
                <tbody>
                  {shown.map((a) => (
                    <tr key={a.id} className="clickable" onClick={() => setSelected(a)} {...rowActivation(() => setSelected(a))}>
                      <td><strong>{a.email}</strong> <span className="muted cond">{a.employee_code}</span></td>
                      <td className="tight">{a.department}</td>
                      <td className="tight cond">{a.approval_level ?? '—'}</td>
                      <td className="tight">{a.is_platform_admin ? <span className="chip pet">head</span> : <span className="muted">—</span>}</td>
                      <td className="tight">
                        <span className={`chip${a.is_active ? ' pet' : ' wn'}`}>{a.is_active ? 'active' : 'disabled'}</span>
                        {a.must_change_pin ? <span className="chip wn" style={{ marginLeft: 6 }}>PIN pending</span> : null}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {selected ? (
        <AccountDrawer
          account={selected}
          onClose={() => setSelected(null)}
          onChanged={(updated) => {
            setRows((r) => r?.map((x) => (x.id === updated.id ? updated : x)) ?? r)
            setSelected(updated)
          }}
        />
      ) : null}

      {adding ? (
        <AddAccountDialog onCancel={() => setAdding(false)} onDone={() => { setAdding(false); reload() }} />
      ) : null}

      {importing ? (
        <BulkImportDialog onCancel={() => setImporting(false)} onDone={() => { setImporting(false); reload() }} />
      ) : null}
    </>
  )
}

// ── Pin reveal ─────────────────────────────────────────────────────────────
function PinReveal({ pin }: { pin: string }) {
  const [copied, setCopied] = useState(false)
  return (
    <div className="card" style={{ marginTop: 12 }}>
      <div className="card-b">
        <div className="eyebrow">One-time PIN · shown once</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 6 }}>
          <code style={{ fontSize: 20, letterSpacing: 2 }}>{pin}</code>
          <button
            className="btn-q"
            onClick={() => { navigator.clipboard?.writeText(pin).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500) }) }}
          >{copied ? 'Copied' : 'Copy'}</button>
        </div>
        <div className="muted" style={{ fontSize: 12, marginTop: 6 }}>Hand it to the mailbox holder directly. They must change it on first login.</div>
      </div>
    </div>
  )
}

// ── per-account customize ────────────────────────────────────────────────
function AccountDrawer({
  account,
  onClose,
  onChanged,
}: {
  account: FunctionalAccount
  onClose: () => void
  onChanged: (a: FunctionalAccount) => void
}) {
  const [approval, setApproval] = useState(account.approval_level ?? '')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [pin, setPin] = useState<string | null>(null)
  const [confirmActive, setConfirmActive] = useState(false)

  useEffect(() => { setApproval(account.approval_level ?? ''); setPin(null); setMsg(null); setErr(null) }, [account])

  async function patch(patchBody: Parameters<typeof mmosApi.admin.updateAccount>[1], note: string) {
    setBusy(true); setErr(null); setMsg(null)
    try {
      const updated = await mmosApi.admin.updateAccount(account.id, patchBody)
      onChanged(updated)
      setMsg(note)
    } catch {
      setErr('Could not apply the change.')
    } finally {
      setBusy(false)
    }
  }

  async function resetPin() {
    setBusy(true); setErr(null); setMsg(null)
    try {
      const p = await mmosApi.admin.resetAccountPin(account.id)
      setPin(p)
      onChanged({ ...account, pin_set: true, must_change_pin: true })
    } catch {
      setErr('Could not reset the PIN.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Panel open onClose={onClose} eyebrow={`${account.employee_code} · ${account.department.toUpperCase()}`} title={account.email ?? account.label}>
      {msg ? <div className="chip pet" style={{ marginBottom: 8 }}>{msg}</div> : null}
      {err ? <div className="form-err">{err}</div> : null}

      <div className="field">
        <label htmlFor="ac-appr">Approval level</label>
        <input id="ac-appr" value={approval} onChange={(e) => setApproval(e.target.value)} placeholder="e.g. L3 (HOD)" />
      </div>
      <div className="row-actions">
        <button className="btn-q" disabled={busy} onClick={() => patch({ approval_level: approval.trim() || null }, 'Approval level saved.')}>Save level</button>
        {account.approval_level ? (
          <button className="btn-q" disabled={busy} onClick={() => { setApproval(''); patch({ approval_level: null }, 'Approval level cleared.') }}>Clear level</button>
        ) : null}
      </div>

      <div className="eyebrow" style={{ margin: '22px 0 8px' }}>Management head</div>
      <div className="muted" style={{ fontSize: 12, marginBottom: 8 }}>A head gets full IT-admin-equivalent access (act + approve + see everything).</div>
      {account.is_platform_admin ? (
        <button className="btn-q btn-danger" disabled={busy} onClick={() => patch({ platform_admin: false }, 'Head access removed.')}>Remove head access</button>
      ) : (
        <button className="btn-q" disabled={busy} onClick={() => patch({ platform_admin: true }, 'Made management head.')}>Make management head</button>
      )}

      <div className="eyebrow" style={{ margin: '22px 0 8px' }}>PIN</div>
      <button className="btn-q" disabled={busy} onClick={resetPin}>Reset one-time PIN</button>
      {pin ? <PinReveal pin={pin} /> : null}

      <div className="eyebrow" style={{ margin: '22px 0 8px' }}>Access</div>
      {account.is_active ? (
        <button className="btn-q btn-danger" disabled={busy} onClick={() => setConfirmActive(true)}>Deactivate account</button>
      ) : (
        <>
          <span className="chip wn" style={{ marginBottom: 8, display: 'inline-block' }}>Disabled — nobody can sign in until enabled</span>
          <div><button className="btn-act" disabled={busy} onClick={() => patch({ is_active: true }, 'Account enabled.')}>Enable account</button></div>
        </>
      )}

      {confirmActive ? (
        <ConfirmDialog
          title={`Deactivate ${account.email ?? account.label}?`}
          body="Ends every session and blocks sign-in within 60 seconds."
          confirmLabel="Deactivate"
          busy={busy}
          onConfirm={async () => { await patch({ is_active: false }, 'Account deactivated.'); setConfirmActive(false) }}
          onCancel={() => setConfirmActive(false)}
        />
      ) : null}
    </Panel>
  )
}

// ── add one account ──────────────────────────────────────────────────────
function AddAccountDialog({ onCancel, onDone }: { onCancel: () => void; onDone: () => void }) {
  const [email, setEmail] = useState('')
  const [department, setDepartment] = useState('')
  const [role, setRole] = useState('requester')
  const [approval, setApproval] = useState('')
  const [head, setHead] = useState(false)
  const [enableNow, setEnableNow] = useState(false)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [pin, setPin] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!email.trim() || !department.trim()) return
    setBusy(true); setErr(null)
    try {
      const res = await mmosApi.admin.createAccount({
        email: email.trim(), department: department.trim(), role: role.trim() || 'requester',
        approval_level: approval.trim() || null, platform_admin: head, active: enableNow,
      })
      setPin(res.pin)
      if (!res.pin) onDone() // no PIN issued (already existed) — nothing to show
    } catch (e2: any) {
      setErr(e2?.message || 'Could not create the account.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="confirm-scrim" onClick={onCancel}>
      <div className="confirm-box" onClick={(e) => e.stopPropagation()} style={{ width: 460 }}>
        <h2>Add account</h2>
        {pin ? (
          <>
            <p className="muted" style={{ fontSize: 13 }}>
              Account created for <strong>{email}</strong>.{' '}
              {enableNow ? 'Enabled — it can sign in now.' : 'Disabled — enable it from the account row when you\'re ready.'}
            </p>
            <PinReveal pin={pin} />
            <div className="row-actions" style={{ marginTop: 12 }}><button className="btn-act" onClick={onDone}>Done</button></div>
          </>
        ) : (
          <form onSubmit={submit}>
            {err ? <div className="form-err">{err}</div> : null}
            <div className="field">
              <label htmlFor="na-email">Email</label>
              <input id="na-email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="purchase.c2@m-mines.com" required />
            </div>
            <div className="field">
              <label htmlFor="na-dept">Department</label>
              <input id="na-dept" value={department} onChange={(e) => setDepartment(e.target.value)} placeholder="Purchase" required />
            </div>
            <div className="field">
              <label htmlFor="na-role">Base role</label>
              <input id="na-role" value={role} onChange={(e) => setRole(e.target.value)} placeholder="requester" />
            </div>
            <div className="field">
              <label htmlFor="na-appr">Approval level (optional)</label>
              <input id="na-appr" value={approval} onChange={(e) => setApproval(e.target.value)} placeholder="e.g. L3 (HOD)" />
            </div>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '8px 0 4px', fontSize: 13 }}>
              <input type="checkbox" checked={head} onChange={(e) => setHead(e.target.checked)} />
              Management head (full IT-admin-equivalent access)
            </label>
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '4px 0 4px', fontSize: 13 }}>
              <input type="checkbox" checked={enableNow} onChange={(e) => setEnableNow(e.target.checked)} />
              Enable immediately
            </label>
            <div className="muted" style={{ fontSize: 12, marginBottom: 4 }}>
              {enableNow ? 'Created enabled — it can sign in right away.' : 'Off by default: the account is created disabled until you enable it.'}
            </div>
            <div className="row-actions">
              <button type="button" className="btn-q" onClick={onCancel} disabled={busy}>Cancel</button>
              <button type="submit" className="btn-act" disabled={busy}>{busy ? 'Creating…' : 'Create'}</button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}

// ── bulk import ──────────────────────────────────────────────────────────
// Parse the roster CSV client-side (never a multipart upload) and send JSON rows.
// Header: employee_code, login_email (or email), department, role, approval_level, platform_admin.
function parseRoster(text: string): AccountRosterRow[] {
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean)
  if (lines.length === 0) return []
  const header = lines[0].split(',').map((h) => h.trim().toLowerCase())
  const idx = (name: string) => header.indexOf(name)
  const iCode = idx('employee_code')
  const iEmail = idx('login_email') >= 0 ? idx('login_email') : idx('email')
  const iDept = idx('department')
  const iRole = idx('role')
  const iAppr = idx('approval_level')
  const iAdmin = idx('platform_admin')
  const truthy = new Set(['true', '1', 'yes', 'y', 't'])
  const rows: AccountRosterRow[] = []
  for (const line of lines.slice(1)) {
    const cells = line.split(',').map((c) => c.trim())
    const email = iEmail >= 0 ? cells[iEmail] : ''
    if (!email) continue
    rows.push({
      employee_code: iCode >= 0 ? cells[iCode] || undefined : undefined,
      email,
      department: iDept >= 0 ? cells[iDept] || '' : '',
      role: iRole >= 0 ? cells[iRole] || undefined : undefined,
      approval_level: iAppr >= 0 ? (cells[iAppr] || null) : null,
      platform_admin: iAdmin >= 0 ? truthy.has((cells[iAdmin] || '').toLowerCase()) : false,
    })
  }
  return rows
}

function BulkImportDialog({ onCancel, onDone }: { onCancel: () => void; onDone: () => void }) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [preview, setPreview] = useState<AccountBulkResult | null>(null)
  const [committed, setCommitted] = useState<AccountBulkResult | null>(null)
  const [copiedAll, setCopiedAll] = useState(false)

  const parsed = useMemo(() => parseRoster(text), [text])

  async function runDry() {
    if (parsed.length === 0) { setErr('No rows parsed. Check the header and columns.'); return }
    setBusy(true); setErr(null)
    try {
      setPreview(await mmosApi.admin.bulkAccounts(parsed, true))
    } catch {
      setErr('Could not preview the import.')
    } finally {
      setBusy(false)
    }
  }

  async function commit() {
    setBusy(true); setErr(null)
    try {
      setCommitted(await mmosApi.admin.bulkAccounts(parsed, false))
    } catch {
      setErr('Could not apply the import.')
    } finally {
      setBusy(false)
    }
  }

  const pins = committed?.pins ?? []

  return (
    <div className="confirm-scrim" onClick={onCancel}>
      <div className="confirm-box" onClick={(e) => e.stopPropagation()} style={{ width: 640, maxHeight: '82vh', overflow: 'auto' }}>
        <h2>Bulk import accounts</h2>
        {err ? <div className="form-err">{err}</div> : null}

        {committed ? (
          <>
            <p className="muted" style={{ fontSize: 13 }}>
              Created {committed.created}, updated {committed.updated}, unchanged {committed.unchanged}.
            </p>
            {(committed.created ?? 0) > 0 ? (
              <p className="chip wn" style={{ display: 'inline-block', marginBottom: 8 }}>
                Disabled — enable each after review
              </p>
            ) : null}
            {pins.length > 0 ? (
              <>
                <div className="eyebrow" style={{ margin: '10px 0 6px', display: 'flex', justifyContent: 'space-between' }}>
                  <span>One-time PINs · shown once</span>
                  <button
                    className="btn-q"
                    onClick={() => {
                      const blob = pins.map((p) => `${p.employee_code}\t${p.email}\t${p.pin}`).join('\n')
                      navigator.clipboard?.writeText(blob).then(() => { setCopiedAll(true); setTimeout(() => setCopiedAll(false), 1500) })
                    }}
                  >{copiedAll ? 'Copied' : 'Copy all'}</button>
                </div>
                <div className="tw">
                  <table>
                    <thead><tr><th>Code</th><th>Email</th><th>PIN</th><th>Head</th></tr></thead>
                    <tbody>
                      {pins.map((p) => (
                        <tr key={p.employee_code}>
                          <td className="tight cond">{p.employee_code}</td>
                          <td className="tight">{p.email}</td>
                          <td className="tight num"><code>{p.pin}</code></td>
                          <td className="tight">{p.platform_admin ? <span className="chip pet">head</span> : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            ) : (
              <p className="muted" style={{ fontSize: 12 }}>No new PINs issued (all rows already had one).</p>
            )}
            <div className="row-actions" style={{ marginTop: 12 }}><button className="btn-act" onClick={onDone}>Done</button></div>
          </>
        ) : (
          <>
            <div className="field">
              <label htmlFor="bi-csv">Roster CSV</label>
              <textarea
                id="bi-csv" rows={7} value={text} onChange={(e) => { setText(e.target.value); setPreview(null) }}
                placeholder={'employee_code,login_email,department,role,approval_level,platform_admin\nFN01,purchase.c2@m-mines.com,Purchase,requester,,\nFN02,central.stores@m-mines.com,Central Stores,approver,L3 (HOD),true'}
                style={{ fontFamily: 'monospace', fontSize: 12 }}
              />
            </div>
            <div className="muted" style={{ fontSize: 12 }}>{parsed.length} row{parsed.length === 1 ? '' : 's'} parsed.</div>

            {preview ? (
              <div className="card" style={{ marginTop: 10 }}>
                <div className="card-h"><div><div className="eyebrow">Dry run · nothing written yet</div><h2>Would create {preview.would_create}, update {preview.would_update}</h2></div></div>
                <div className="card-b flush">
                  {preview.would_create ? (
                    <p className="chip wn" style={{ display: 'inline-block', margin: '0 0 8px' }}>
                      New accounts are created Disabled — enable each after review
                    </p>
                  ) : null}
                  <div className="tw">
                    <table>
                      <thead><tr><th>Code</th><th>Email</th><th>Employee</th><th>Head</th><th>Status</th></tr></thead>
                      <tbody>
                        {preview.rows.map((r) => (
                          <tr key={r.employee_code}>
                            <td className="tight cond">{r.employee_code}</td>
                            <td className="tight">{r.email}</td>
                            <td className="tight"><span className={`chip${r.employee_action.includes('creat') ? ' pet' : ''}`}>{r.employee_action.replace('would_', '')}</span></td>
                            <td className="tight">{r.platform_admin ? <span className="chip pet">head</span> : '—'}</td>
                            <td className="tight">
                              {r.employee_action.includes('creat')
                                ? <span className={`chip${r.active ? ' pet' : ' wn'}`}>{r.active ? 'enabled' : 'disabled'}</span>
                                : <span className="muted">—</span>}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            ) : null}

            <div className="row-actions" style={{ marginTop: 12 }}>
              <button type="button" className="btn-q" onClick={onCancel} disabled={busy}>Cancel</button>
              {preview ? (
                <button type="button" className="btn-act" onClick={commit} disabled={busy}>{busy ? 'Applying…' : `Confirm & apply ${(preview.would_create ?? 0) + (preview.would_update ?? 0)}`}</button>
              ) : (
                <button type="button" className="btn-act" onClick={runDry} disabled={busy || parsed.length === 0}>{busy ? 'Previewing…' : 'Preview'}</button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
