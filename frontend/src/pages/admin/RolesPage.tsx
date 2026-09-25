import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { mmosApi, ApiRequestError } from '../../api'
import type { AdminGrant, AdminService, RoleFile, RoleImportPlan } from '../../api/types'
import { EmptyState } from '../../components/EmptyState'
import { ConfirmDialog } from '../../components/ConfirmDialog'

// A service's roles, what each one may do, and the role file that declares both.
// The file format and its rules live in backend/app/roles_io.py; the committed files in
// backend/app/role_files/. Permissions can only be added through a file, because the
// service has to understand a permission before a role can usefully carry it.
export function RolesPage() {
  const [params, setParams] = useSearchParams()
  const [services, setServices] = useState<AdminService[] | null>(null)
  const [grants, setGrants] = useState<AdminGrant[]>([])
  const [error, setError] = useState<string | null>(null)
  const slug = params.get('service') || ''

  function loadServices() {
    return mmosApi.admin.listServices().then((s) => {
      setServices(s)
      if (!slug) {
        const first = s.find((x) => x.launch_mode !== 'external') ?? s[0]
        if (first) setParams({ service: first.slug }, { replace: true })
      }
    }).catch(() => setError('Could not load the service registry.'))
  }
  useEffect(() => { loadServices() }, [])
  useEffect(() => {
    if (slug) mmosApi.admin.listGrants({ service: slug }).then(setGrants).catch(() => setGrants([]))
  }, [slug])

  const service = services?.find((s) => s.slug === slug) ?? null
  const holders = useMemo(() => {
    const m = new Map<string, number>()
    for (const g of grants) m.set(g.role.key, (m.get(g.role.key) ?? 0) + 1)
    return m
  }, [grants])

  function replaceService(next: AdminService) {
    setServices((all) => all?.map((s) => (s.slug === next.slug ? next : s)) ?? all)
  }
  function refresh() {
    loadServices()
    if (slug) mmosApi.admin.listGrants({ service: slug }).then(setGrants).catch(() => {})
  }

  if (error) return <EmptyState title={error} />
  if (services === null) return null

  return (
    <>
      <div className="head">
        <h1>Roles</h1>
        <div className="field" style={{ marginBottom: 0, minWidth: 240 }}>
          <label htmlFor="roles-svc">Service</label>
          <select id="roles-svc" value={slug} onChange={(e) => setParams({ service: e.target.value })}>
            {services.map((s) => (
              <option key={s.slug} value={s.slug}>{s.name}{s.launch_mode === 'external' ? ' (own sign-in)' : ''}</option>
            ))}
          </select>
        </div>
      </div>

      {service ? (
        <>
          <PermissionMatrix service={service} holders={holders} onChanged={replaceService} onReload={refresh} />
          <RoleFileCard service={service} onApplied={refresh} />
        </>
      ) : (
        <EmptyState title="Pick a service" />
      )}
    </>
  )
}

function PermissionMatrix({
  service, holders, onChanged, onReload,
}: {
  service: AdminService
  holders: Map<string, number>
  onChanged: (s: AdminService) => void
  onReload: () => void
}) {
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)
  const [adding, setAdding] = useState(false)
  const catalog = Object.entries(service.permission_catalog ?? {})

  async function toggle(roleKey: string, perm: string) {
    const role = service.roles.find((r) => r.key === roleKey)!
    const next = role.permissions.includes(perm)
      ? role.permissions.filter((p) => p !== perm)
      : [...role.permissions, perm]
    setBusy(`${roleKey}:${perm}`); setErr(null)
    try {
      const updated = await mmosApi.admin.updateServiceRole(service.slug, roleKey, { permissions: next })
      onChanged({ ...service, roles: service.roles.map((r) => (r.key === roleKey ? updated : r)) })
    } catch (e) {
      setErr(e instanceof ApiRequestError ? e.message : 'Could not save that change.')
    } finally {
      setBusy(null)
    }
  }

  async function makeDefault(roleKey: string) {
    setErr(null)
    try {
      await mmosApi.admin.updateServiceRole(service.slug, roleKey, { is_default: true })
      onChanged({ ...service, roles: service.roles.map((r) => ({ ...r, is_default: r.key === roleKey })) })
    } catch (e) {
      setErr(e instanceof ApiRequestError ? e.message : 'Could not change the default role.')
    }
  }

  async function remove(roleKey: string) {
    setErr(null)
    try {
      await mmosApi.admin.deleteServiceRole(service.slug, roleKey)
      onChanged({ ...service, roles: service.roles.filter((r) => r.key !== roleKey) })
    } catch (e) {
      setErr(e instanceof ApiRequestError ? e.message : 'Could not delete that role.')
    } finally {
      setDeleting(null)
    }
  }

  return (
    <div className="card">
      <div className="card-h">
        <div>
          <div className="eyebrow">{service.roles.length} roles · {catalog.length} permissions · tick a box to change it</div>
          <h2>What each role can do</h2>
        </div>
        <button className="btn-q" onClick={() => setAdding(true)}>Add role</button>
      </div>
      {err ? <div className="card-b"><div className="form-err">{err}</div></div> : null}
      <div className="card-b flush">
        {service.roles.length === 0 ? (
          <EmptyState title="No roles yet" hint="Add one, or import a role file below." />
        ) : (
          <div className="matrix-wrap">
            <table className="matrix" style={{ width: '100%' }}>
              <thead>
                <tr>
                  <th>Permission</th>
                  {service.roles.map((r) => (
                    <th key={r.key} style={{ textAlign: 'center', verticalAlign: 'bottom' }}>
                      <div style={{ color: 'var(--text)', fontSize: 13, letterSpacing: 0, textTransform: 'none', fontFamily: 'var(--f)' }}>{r.name}</div>
                      <div className="cond">{r.key} · {holders.get(r.key) ?? 0} people</div>
                      {r.is_default ? <span className="chip pet">default</span> : null}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {catalog.length === 0 ? (
                  <tr>
                    <td colSpan={service.roles.length + 1} className="muted">
                      This service has no permissions declared yet. Import a role file to declare them.
                    </td>
                  </tr>
                ) : catalog.map(([perm, meaning]) => (
                  <tr key={perm}>
                    <td style={{ whiteSpace: 'normal' }}>
                      <strong className="cond">{perm}</strong>
                      <div className="muted" style={{ fontSize: 12 }}>{meaning}</div>
                    </td>
                    {service.roles.map((r) => {
                      const on = r.permissions.includes(perm)
                      return (
                        <td key={r.key} style={{ textAlign: 'center' }}>
                          <input
                            type="checkbox"
                            aria-label={`${r.name}: ${perm}`}
                            checked={on}
                            disabled={busy !== null}
                            onChange={() => toggle(r.key, perm)}
                          />
                        </td>
                      )
                    })}
                  </tr>
                ))}
                <tr>
                  <td className="muted" style={{ whiteSpace: 'normal' }}>Meaning shown wherever the role is granted</td>
                  {service.roles.map((r) => (
                    <td key={r.key} style={{ whiteSpace: 'normal', fontSize: 12, verticalAlign: 'top', minWidth: 160 }}>
                      {r.description || <span className="muted">No description.</span>}
                      <div className="row-actions" style={{ marginTop: 8, justifyContent: 'center' }}>
                        {!r.is_default ? <button className="btn-q" onClick={() => makeDefault(r.key)}>Make default</button> : null}
                        <button
                          className="btn-q btn-danger"
                          disabled={(holders.get(r.key) ?? 0) > 0}
                          title={(holders.get(r.key) ?? 0) > 0 ? 'People hold this role. Move them first.' : undefined}
                          onClick={() => setDeleting(r.key)}
                        >Delete</button>
                      </div>
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </div>

      {deleting ? (
        <ConfirmDialog
          title={`Delete the ${deleting} role?`}
          body="Nobody holds it, so no one loses access. This cannot be undone."
          confirmLabel="Delete role"
          onConfirm={() => remove(deleting)}
          onCancel={() => setDeleting(null)}
        />
      ) : null}
      {adding ? (
        <AddRoleDialog service={service} onCancel={() => setAdding(false)} onDone={() => { setAdding(false); onReload() }} />
      ) : null}
    </div>
  )
}

function AddRoleDialog({ service, onCancel, onDone }: { service: AdminService; onCancel: () => void; onDone: () => void }) {
  const [key, setKey] = useState('')
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [perms, setPerms] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true); setErr(null)
    try {
      await mmosApi.admin.addServiceRole(service.slug, {
        key: key.trim(), name: name.trim(), description: description.trim() || undefined, permissions: perms,
      })
      onDone()
    } catch (e2) {
      setErr(e2 instanceof ApiRequestError ? e2.message : 'Could not add the role.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="confirm-scrim" onClick={onCancel}>
      <div className="confirm-box" onClick={(e) => e.stopPropagation()} style={{ width: 460, maxWidth: 'calc(100vw - 32px)' }}>
        <h2>Add a role to {service.name}</h2>
        <form onSubmit={submit}>
          <div className="field">
            <label htmlFor="ar-key">Key (lowercase, used in tokens)</label>
            <input id="ar-key" value={key} onChange={(e) => setKey(e.target.value.toLowerCase())} placeholder="supervisor" pattern="[a-z][a-z0-9_]{0,31}" required />
          </div>
          <div className="field"><label htmlFor="ar-name">Name</label><input id="ar-name" value={name} onChange={(e) => setName(e.target.value)} required /></div>
          <div className="field"><label htmlFor="ar-desc">Meaning</label><textarea id="ar-desc" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} /></div>
          {Object.keys(service.permission_catalog ?? {}).length ? (
            <div className="field">
              <label>Can do</label>
              {Object.entries(service.permission_catalog).map(([p, meaning]) => (
                <label key={p} style={{ display: 'flex', gap: 8, textTransform: 'none', letterSpacing: 0, fontSize: 13, color: 'var(--text)', alignItems: 'flex-start' }}>
                  <input type="checkbox" style={{ width: 'auto', marginTop: 3 }} checked={perms.includes(p)}
                    onChange={(e) => setPerms(e.target.checked ? [...perms, p] : perms.filter((x) => x !== p))} />
                  <span><strong className="cond">{p}</strong> <span className="muted">{meaning}</span></span>
                </label>
              ))}
            </div>
          ) : null}
          {err ? <div className="form-err">{err}</div> : null}
          <div className="row-actions">
            <button type="button" className="btn-q" onClick={onCancel} disabled={busy}>Cancel</button>
            <button type="submit" className="btn-act" disabled={busy || !key.trim() || !name.trim()}>{busy ? 'Adding…' : 'Add role'}</button>
          </div>
        </form>
      </div>
    </div>
  )
}

function RoleFileCard({ service, onApplied }: { service: AdminService; onApplied: () => void }) {
  const [text, setText] = useState('')
  const [committed, setCommitted] = useState(false)
  const [plan, setPlan] = useState<RoleImportPlan | null>(null)
  const [problems, setProblems] = useState<string[]>([])
  const [err, setErr] = useState<string | null>(null)
  const [reassign, setReassign] = useState(false)
  const [busy, setBusy] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [done, setDone] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement>(null)

  useEffect(() => {
    setText(''); setPlan(null); setProblems([]); setErr(null); setDone(null); setCommitted(false)
    mmosApi.admin.roleFileTemplate(service.slug)
      .then((t) => { setCommitted(t.committed); if (t.committed) setText(JSON.stringify(t.file, null, 2)) })
      .catch(() => {})
  }, [service.slug])

  function parsed(): RoleFile | null {
    try {
      return JSON.parse(text) as RoleFile
    } catch (e) {
      setProblems([`Not valid JSON: ${(e as Error).message}`])
      return null
    }
  }

  async function run(dryRun: boolean) {
    const file = parsed()
    if (!file) return
    setBusy(true); setErr(null); setProblems([]); setDone(null)
    try {
      const result = await mmosApi.admin.importRoleFile(service.slug, file, {
        dryRun, assignMode: reassign ? 'all' : undefined,
      })
      if (dryRun) {
        setPlan(result)
      } else {
        setPlan(null)
        setDone(`Applied. ${result.grants_created.length} people given a role, ${result.grants_changed.length + result.grants_moved.length} moved.`)
        onApplied()
      }
    } catch (e) {
      if (e instanceof ApiRequestError && e.problems.length) setProblems(e.problems)
      else setErr(e instanceof ApiRequestError ? e.message : 'The import failed.')
    } finally {
      setBusy(false); setConfirming(false)
    }
  }

  async function loadFrom(source: 'export' | 'template') {
    setPlan(null); setProblems([]); setDone(null)
    const file = source === 'export'
      ? await mmosApi.admin.exportRoleFile(service.slug)
      : (await mmosApi.admin.roleFileTemplate(service.slug)).file
    setText(JSON.stringify(file, null, 2))
  }

  function download() {
    const blob = new Blob([text || '{}'], { type: 'application/json' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `${service.slug}.roles.json`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  function upload(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    if (!f) return
    f.text().then((t) => { setText(t); setPlan(null); setProblems([]); setDone(null) })
    e.target.value = ''
  }

  return (
    <div className="card">
      <div className="card-h">
        <div>
          <div className="eyebrow">{committed ? 'A role file ships with MM OS for this service' : 'Declare roles, permissions and who gets what in one file'}</div>
          <h2>Role file</h2>
        </div>
        <div className="row-actions">
          <input ref={fileInput} type="file" accept=".json,application/json" hidden onChange={upload} />
          <button className="btn-q" onClick={() => fileInput.current?.click()}>Upload file…</button>
          {committed ? <button className="btn-q" onClick={() => loadFrom('template')}>Load shipped file</button> : null}
          <button className="btn-q" onClick={() => loadFrom('export')}>Start from current roles</button>
          <button className="btn-q" onClick={download} disabled={!text}>Download</button>
        </div>
      </div>
      <div className="card-b">
        <div className="field">
          <label htmlFor="rf-text">File contents (JSON)</label>
          <textarea
            id="rf-text" rows={16} spellCheck={false} value={text}
            onChange={(e) => { setText(e.target.value); setPlan(null) }}
            style={{ fontFamily: 'ui-monospace, Consolas, monospace', fontSize: 12.5 }}
            placeholder="Upload a file, or start from the current roles."
          />
        </div>
        <p className="muted" style={{ fontSize: 12, margin: '0 0 12px' }}>
          <code>permissions</code> lists what the service can check. Each role lists the ones it gets.
          {' '}<code>replaces</code> moves everyone on an old role onto this one.
          {' '}<code>assign</code> gives people a role: named people first, then the first rule that matches
          ({'{'}"platform_admin": true{'}'}, {'{'}"is_approver": true{'}'}, band, department), then the default.
          Keep named people out of files you commit.
        </p>
        <label style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13, marginBottom: 12 }}>
          <input type="checkbox" checked={reassign} onChange={(e) => { setReassign(e.target.checked); setPlan(null) }} />
          Also re-assign people who already have a role on this service (otherwise only people with no role are given one)
        </label>

        {problems.length ? (
          <div className="form-err">
            <strong>The file has {problems.length} problem{problems.length === 1 ? '' : 's'}:</strong>
            <ul style={{ margin: '6px 0 0 18px' }}>{problems.map((p) => <li key={p}>{p}</li>)}</ul>
          </div>
        ) : null}
        {err ? <div className="form-err">{err}</div> : null}
        {done ? <div className="form-err" style={{ background: 'var(--petrol-100)', color: 'var(--petrol)' }}>{done}</div> : null}

        {plan ? <PlanSummary plan={plan} /> : null}

        <div className="row-actions" style={{ marginTop: 12 }}>
          <button className="btn-q" onClick={() => run(true)} disabled={busy || !text.trim()}>{busy && !confirming ? 'Checking…' : 'Preview changes'}</button>
          <button className="btn-act" onClick={() => setConfirming(true)} disabled={busy || !plan}>Apply</button>
        </div>
      </div>

      {confirming && plan ? (
        <ConfirmDialog
          title={`Apply this role file to ${service.name}?`}
          body={`${plan.roles_created.length} roles created, ${plan.roles_updated.length} updated, ${plan.roles_removed.length} removed; ${plan.grants_created.length} people given a role and ${plan.grants_moved.length + plan.grants_changed.length} moved. People whose role changes get the new role the next time they open ${service.name} from MM OS.`}
          confirmLabel="Apply"
          danger={false}
          busy={busy}
          onConfirm={() => run(false)}
          onCancel={() => setConfirming(false)}
        />
      ) : null}
    </div>
  )
}

function PlanSummary({ plan }: { plan: RoleImportPlan }) {
  const nothing = !plan.catalog_changed && !plan.roles_created.length && !plan.roles_updated.length
    && !plan.roles_removed.length && !plan.grants_moved.length && !plan.grants_created.length && !plan.grants_changed.length
  const byRole = (rows: { role: string }[]) => {
    const m = new Map<string, number>()
    rows.forEach((r) => m.set(r.role, (m.get(r.role) ?? 0) + 1))
    return [...m.entries()].map(([k, n]) => `${n} ${k}`).join(', ')
  }
  return (
    <div className="card" style={{ boxShadow: 'none' }}>
      <div className="card-b">
        <div className="eyebrow" style={{ marginBottom: 8 }}>Preview · nothing has been written yet</div>
        {nothing ? <p style={{ margin: 0 }}>No changes. The service already matches this file.</p> : (
          <ul style={{ margin: 0, paddingLeft: 18, lineHeight: 1.7 }}>
            {plan.catalog_changed ? <li>Permission list updated</li> : null}
            {plan.roles_created.length ? <li>New roles: <strong>{plan.roles_created.join(', ')}</strong></li> : null}
            {plan.roles_updated.length ? <li>Updated roles: {plan.roles_updated.join(', ')}</li> : null}
            {plan.roles_removed.length ? <li>Removed roles: {plan.roles_removed.join(', ')}</li> : null}
            {plan.grants_moved.length ? <li>{plan.grants_moved.length} people moved from a replaced role ({[...new Set(plan.grants_moved.map((g) => `${g.from} → ${g.to}`))].join(', ')})</li> : null}
            {plan.grants_created.length ? (
              <li>
                {plan.grants_created.length} people given a role ({byRole(plan.grants_created)})
                <details style={{ marginTop: 4 }}>
                  <summary className="muted">Show who</summary>
                  <ul style={{ paddingLeft: 18 }}>
                    {plan.grants_created.map((g) => <li key={g.user_id}>{g.name} <span className="muted cond">{g.employee_code}</span> → {g.role}</li>)}
                  </ul>
                </details>
              </li>
            ) : null}
            {plan.grants_changed.length ? (
              <li>
                {plan.grants_changed.length} people change role
                <details style={{ marginTop: 4 }}>
                  <summary className="muted">Show who</summary>
                  <ul style={{ paddingLeft: 18 }}>
                    {plan.grants_changed.map((g) => <li key={g.user_id}>{g.name} <span className="muted cond">{g.employee_code}</span>: {g.from} → {g.to}</li>)}
                  </ul>
                </details>
              </li>
            ) : null}
            {plan.unchanged_people ? <li className="muted">{plan.unchanged_people} people keep the role they have</li> : null}
          </ul>
        )}
        {plan.warnings.map((w) => <p key={w} className="muted" style={{ margin: '8px 0 0', color: 'var(--orange)' }}>⚠ {w}</p>)}
      </div>
    </div>
  )
}
