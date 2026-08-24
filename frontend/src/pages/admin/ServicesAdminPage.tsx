import React, { useEffect, useState } from 'react'
import { mmosApi } from '../../api'
import type { AdminService, LaunchMode } from '../../api/types'
import { Panel } from '../../components/Panel'
import { EmptyState } from '../../components/EmptyState'
import { rowActivation } from '../../lib/a11y'

export function ServicesAdminPage() {
  const [rows, setRows] = useState<AdminService[] | null>(null)
  const [selected, setSelected] = useState<AdminService | null>(null)
  const [creating, setCreating] = useState(false)
  const [loadError, setLoadError] = useState<string | null>(null)

  function reload() {
    mmosApi.admin.listServices().then(setRows).catch(() => setLoadError('Could not load the service registry.'))
  }
  useEffect(reload, [])

  if (loadError) return <EmptyState title={loadError} />

  return (
    <>
      <div className="head">
        <h1>Services</h1>
        <button className="btn-act" onClick={() => setCreating(true)}>Register service</button>
      </div>

      <div className="card">
        <div className="card-b flush">
          {rows === null ? null : rows.length === 0 ? (
            <EmptyState title="No services registered" />
          ) : (
            <div className="tw">
              <table>
                <thead><tr><th>Name</th><th>Category</th><th>Launch mode</th><th>Roles</th><th>Status</th></tr></thead>
                <tbody>
                  {rows.map((s) => (
                    <tr key={s.id} className="clickable" onClick={() => setSelected(s)} {...rowActivation(() => setSelected(s))}>
                      <td><strong>{s.name}</strong> <span className="muted cond">{s.slug}</span></td>
                      <td className="tight">{s.category}</td>
                      <td className="tight cond">{s.launch_mode}</td>
                      <td className="tight num">{s.roles.length}</td>
                      <td className="tight"><span className={`chip${s.is_active ? ' pet' : ''}`}>{s.is_active ? 'active' : 'inactive'}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>

      {selected ? (
        <ServiceDrawer
          service={selected}
          onClose={() => setSelected(null)}
          onChanged={(updated) => { setRows((r) => r?.map((x) => (x.id === updated.id ? updated : x)) ?? r); setSelected(updated) }}
        />
      ) : null}

      {creating ? (
        <CreateServiceDialog onCancel={() => setCreating(false)} onDone={() => { setCreating(false); reload() }} />
      ) : null}
    </>
  )
}

function ServiceDrawer({
  service,
  onClose,
  onChanged,
}: {
  service: AdminService
  onClose: () => void
  onChanged: (s: AdminService) => void
}) {
  const [form, setForm] = useState(service)
  const [saving, setSaving] = useState(false)
  const [roleKey, setRoleKey] = useState('')
  const [roleName, setRoleName] = useState('')
  const [roleDesc, setRoleDesc] = useState('')
  const [addingRole, setAddingRole] = useState(false)
  const [key, setKey] = useState<string | null>(null)
  const [rotating, setRotating] = useState(false)

  useEffect(() => { setForm(service); setKey(null) }, [service])

  async function save() {
    setSaving(true)
    try {
      const updated = await mmosApi.admin.updateService(service.slug, {
        name: form.name, tagline: form.tagline, category: form.category,
        base_url: form.base_url, launch_mode: form.launch_mode, is_active: form.is_active,
      })
      onChanged({ ...service, ...updated })
    } finally {
      setSaving(false)
    }
  }

  async function addRole() {
    if (!roleKey.trim() || !roleName.trim()) return
    setAddingRole(true)
    try {
      const role = await mmosApi.admin.addServiceRole(service.slug, { key: roleKey.trim(), name: roleName.trim(), description: roleDesc.trim() || undefined })
      onChanged({ ...service, roles: [...service.roles, role] })
      setRoleKey(''); setRoleName(''); setRoleDesc('')
    } finally {
      setAddingRole(false)
    }
  }

  async function rotate() {
    setRotating(true)
    try {
      const newKey = await mmosApi.admin.rotateServiceKey(service.slug)
      setKey(newKey)
    } finally {
      setRotating(false)
    }
  }

  return (
    <Panel open onClose={onClose} eyebrow={service.slug} title={service.name}>
      <div className="field">
        <label htmlFor="s-name">Name</label>
        <input id="s-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
      </div>
      <div className="field">
        <label htmlFor="s-tagline">Tagline</label>
        <input id="s-tagline" value={form.tagline ?? ''} onChange={(e) => setForm({ ...form, tagline: e.target.value })} />
      </div>
      <div className="field">
        <label htmlFor="s-url">Base URL</label>
        <input id="s-url" value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} />
      </div>
      <div className="field">
        <label htmlFor="s-mode">Launch mode</label>
        <select id="s-mode" value={form.launch_mode} onChange={(e) => setForm({ ...form, launch_mode: e.target.value as LaunchMode })}>
          <option value="handoff">handoff — MM OS mints a token</option>
          <option value="embed">embed</option>
          <option value="external">external — service owns its sign-in</option>
        </select>
      </div>
      <div className="field">
        <label htmlFor="s-active">
          <input id="s-active" type="checkbox" style={{ width: 'auto', marginRight: 6 }} checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
          Active
        </label>
      </div>
      <button className="btn-act" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save'}</button>

      <div className="eyebrow" style={{ margin: '22px 0 8px' }}>Roles</div>
      {service.roles.map((r) => (
        <details className="role" key={r.id}>
          <summary>{r.name} ({r.key})</summary>
          <p>{r.description || 'No description declared.'}</p>
        </details>
      ))}
      <div className="field" style={{ marginTop: 12 }}>
        <label htmlFor="r-key">New role key</label>
        <input id="r-key" value={roleKey} onChange={(e) => setRoleKey(e.target.value)} placeholder="admin" />
      </div>
      <div className="field">
        <label htmlFor="r-name">New role name</label>
        <input id="r-name" value={roleName} onChange={(e) => setRoleName(e.target.value)} placeholder="Administrator" />
      </div>
      <div className="field">
        <label htmlFor="r-desc">Meaning (shown wherever this role is granted)</label>
        <textarea id="r-desc" rows={2} value={roleDesc} onChange={(e) => setRoleDesc(e.target.value)} />
      </div>
      <button className="btn-q" onClick={addRole} disabled={addingRole || !roleKey.trim() || !roleName.trim()}>Add role</button>

      <div className="eyebrow" style={{ margin: '22px 0 8px' }}>Service key</div>
      {key ? (
        <>
          <div className="form-err" style={{ background: 'var(--petrol-100)', color: 'var(--petrol)', fontFamily: 'var(--fc)', wordBreak: 'break-all' }}>{key}</div>
          <p className="muted" style={{ fontSize: 12, marginTop: 6 }}>You will not see this again — copy it now.</p>
          <button className="btn-q" onClick={() => navigator.clipboard?.writeText(key)}>Copy</button>
        </>
      ) : (
        <button className="btn-q btn-danger" onClick={rotate} disabled={rotating}>{rotating ? 'Rotating…' : 'Rotate key'}</button>
      )}
    </Panel>
  )
}

function CreateServiceDialog({ onCancel, onDone }: { onCancel: () => void; onDone: () => void }) {
  const [slug, setSlug] = useState('')
  const [name, setName] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [launchMode, setLaunchMode] = useState<LaunchMode>('handoff')
  const [busy, setBusy] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!slug.trim() || !name.trim() || !baseUrl.trim()) return
    setBusy(true)
    try {
      await mmosApi.admin.createService({ slug: slug.trim(), name: name.trim(), base_url: baseUrl.trim(), launch_mode: launchMode })
      onDone()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="confirm-scrim" onClick={onCancel}>
      <div className="confirm-box" onClick={(e) => e.stopPropagation()} style={{ width: 420 }}>
        <h2>Register service</h2>
        <form onSubmit={submit}>
          <div className="field"><label htmlFor="ns-slug">Slug</label><input id="ns-slug" value={slug} onChange={(e) => setSlug(e.target.value)} required /></div>
          <div className="field"><label htmlFor="ns-name">Name</label><input id="ns-name" value={name} onChange={(e) => setName(e.target.value)} required /></div>
          <div className="field"><label htmlFor="ns-url">Base URL</label><input id="ns-url" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} required /></div>
          <div className="field">
            <label htmlFor="ns-mode">Launch mode</label>
            <select id="ns-mode" value={launchMode} onChange={(e) => setLaunchMode(e.target.value as LaunchMode)}>
              <option value="handoff">handoff</option>
              <option value="embed">embed</option>
              <option value="external">external</option>
            </select>
          </div>
          <div className="row-actions">
            <button type="button" className="btn-q" onClick={onCancel} disabled={busy}>Cancel</button>
            <button type="submit" className="btn-act" disabled={busy}>{busy ? 'Registering…' : 'Register'}</button>
          </div>
        </form>
      </div>
    </div>
  )
}
