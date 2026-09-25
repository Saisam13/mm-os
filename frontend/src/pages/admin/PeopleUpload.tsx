import React, { useMemo, useState } from 'react'
import { mmosApi, ApiRequestError } from '../../api'
import type { PeopleImportGrant, PeopleImportResult, PeopleImportRow } from '../../api/types'

// Bulk upload of the people sheet (backend app/people_sheet.py). Always a dry run first:
// the server runs the whole import against real rows and rolls it back, so the preview is
// exactly what "Confirm & apply" does. Every access change can be unticked; downgrades and
// removals start unticked so nobody loses access by accident.
const SOURCE: Record<PeopleImportGrant['source'], string> = {
  people: 'set in the row',
  rule: 'department default',
  default: 'lowest role',
}

export function PeopleUploadDialog({ onCancel, onDone }: { onCancel: () => void; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [preview, setPreview] = useState<PeopleImportResult | null>(null)
  const [applied, setApplied] = useState<PeopleImportResult | null>(null)
  const [unticked, setUnticked] = useState<Set<string>>(new Set())
  const [showNew, setShowNew] = useState(false)

  async function runDry() {
    if (!file) return
    setBusy(true); setErr(null)
    try {
      const r = await mmosApi.admin.importPeople(file, { dryRun: true })
      setPreview(r)
      setUnticked(new Set(r.grants.filter((g) => g.direction === 'down').map((g) => g.key)))
    } catch (e) {
      setErr(e instanceof ApiRequestError ? e.message : 'Could not read that file.')
    } finally {
      setBusy(false)
    }
  }

  async function apply() {
    if (!file) return
    setBusy(true); setErr(null)
    try {
      setApplied(await mmosApi.admin.importPeople(file, { dryRun: false, skip: [...unticked] }))
    } catch (e) {
      setErr(e instanceof ApiRequestError ? e.message : 'The upload failed. Nothing was changed.')
    } finally {
      setBusy(false)
    }
  }

  function toggle(key: string) {
    setUnticked((s) => {
      const n = new Set(s)
      if (n.has(key)) n.delete(key); else n.add(key)
      return n
    })
  }

  const rows = preview?.rows ?? []
  const rejected = rows.filter((r) => r.status === 'reject')
  const flagged = rows.filter((r) => r.status !== 'reject' && (r.fixes.length || r.notes.length))
  const existingChanges = useMemo(() => (preview?.grants ?? []).filter((g) => g.kind !== 'created'), [preview])
  const newAccess = useMemo(() => (preview?.grants ?? []).filter((g) => g.kind === 'created'), [preview])
  const s = preview?.summary ?? {}

  return (
    <div className="confirm-scrim" onClick={onCancel}>
      <div className="confirm-box" onClick={(e) => e.stopPropagation()} style={{ width: 'min(960px, 94vw)', maxHeight: '88vh', overflow: 'auto' }}>
        <h2>Bulk upload people</h2>
        {err ? <div className="form-err">{err}</div> : null}

        {applied ? (
          <>
            <p style={{ fontSize: 14 }}>
              Done. Created {applied.summary.create ?? 0}, updated {applied.summary.update ?? 0}; access given{' '}
              {applied.summary.grants_created ?? 0}, changed {applied.summary.grants_changed ?? 0}, removed{' '}
              {applied.summary.grants_removed ?? 0}. {applied.summary.rejected ?? 0} row(s) were skipped as rejected.
            </p>
            <p className="muted" style={{ fontSize: 13 }}>
              People sign in with Google on their official email, then confirm their employee code and choose a PIN.
            </p>
            <div className="row-actions" style={{ marginTop: 12 }}><button className="btn-act" onClick={onDone}>Done</button></div>
          </>
        ) : (
          <>
            <p className="muted" style={{ fontSize: 13 }}>
              <a href={mmosApi.admin.peopleTemplateUrl()} download>Download the template</a> (its dropdowns come from the
              live services and roles), fill it in, then upload it here. Nothing is written until you confirm.
            </p>
            <div className="field">
              <label htmlFor="pu-file">People sheet (.xlsx)</label>
              <input id="pu-file" type="file" accept=".xlsx"
                onChange={(e) => { setFile(e.target.files?.[0] ?? null); setPreview(null) }} />
            </div>

            {preview ? (
              <>
                <div className="eyebrow" style={{ margin: '14px 0 6px' }}>Dry run · nothing written yet</div>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
                  <span className="chip pet">create {s.create ?? 0}</span>
                  <span className="chip">update {s.update ?? 0}</span>
                  <span className="chip">unchanged {s.unchanged ?? 0}</span>
                  <span className={`chip${s.rejected ? ' wn' : ''}`}>rejected {s.rejected ?? 0}</span>
                  {s.duplicates ? <span className="chip">listed twice {s.duplicates}</span> : null}
                  <span className="chip pet">access given {s.grants_created ?? 0}</span>
                  <span className="chip">changed {s.grants_changed ?? 0}</span>
                  <span className={`chip${s.grants_removed ? ' wn' : ''}`}>removed {s.grants_removed ?? 0}</span>
                </div>

                {preview.warnings.length ? (
                  <ul style={{ fontSize: 13, margin: '0 0 10px', paddingLeft: 18 }}>
                    {preview.warnings.map((w) => <li key={w}>{w}</li>)}
                  </ul>
                ) : null}

                {rejected.length ? (
                  <Section title={`Rejected, will not be imported (${rejected.length})`}>
                    <RowTable rows={rejected} field="errors" />
                  </Section>
                ) : null}

                {flagged.length ? (
                  <Section title={`Corrected or worth a look (${flagged.length})`}>
                    <RowTable rows={flagged} field="fixes" />
                  </Section>
                ) : null}

                {existingChanges.length ? (
                  <Section title={`Changes to access people already have (${existingChanges.length}) · downgrades start unticked`}>
                    <GrantTable grants={existingChanges} unticked={unticked} onToggle={toggle} />
                  </Section>
                ) : null}

                <Section title={`New access (${newAccess.length})`}>
                  {showNew ? (
                    <GrantTable grants={newAccess} unticked={unticked} onToggle={toggle} />
                  ) : (
                    <button className="btn-q" onClick={() => setShowNew(true)}>Show all {newAccess.length}</button>
                  )}
                </Section>

                {preview.departments.length ? (
                  <Section title="Department spellings mapped">
                    <div className="tw">
                      <table>
                        <thead><tr><th>In the sheet</th><th>Stored as</th><th>Rows</th></tr></thead>
                        <tbody>
                          {preview.departments.map((d) => (
                            <tr key={`${d.from}→${d.to}`}><td className="tight">{d.from || '(blank)'}</td><td className="tight">{d.to}</td><td className="tight num">{d.rows}</td></tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </Section>
                ) : null}
              </>
            ) : null}

            <div className="row-actions" style={{ marginTop: 12 }}>
              <button type="button" className="btn-q" onClick={onCancel} disabled={busy}>Cancel</button>
              {preview ? (
                <button type="button" className="btn-act" onClick={apply} disabled={busy}>
                  {busy ? 'Applying…' : `Confirm & apply${unticked.size ? ` (${unticked.size} unticked)` : ''}`}
                </button>
              ) : (
                <button type="button" className="btn-act" onClick={runDry} disabled={busy || !file}>{busy ? 'Checking…' : 'Dry run'}</button>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="card" style={{ marginTop: 10 }}>
      <div className="card-h"><div><h2 style={{ fontSize: 14 }}>{title}</h2></div></div>
      <div className="card-b flush">{children}</div>
    </div>
  )
}

function RowTable({ rows, field }: { rows: PeopleImportRow[]; field: 'errors' | 'fixes' }) {
  return (
    <div className="tw">
      <table>
        <thead><tr><th>Row</th><th>ID</th><th>Name</th><th>Department</th><th>{field === 'errors' ? 'Why' : 'What changed / notes'}</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.row}>
              <td className="tight num">{r.row}</td>
              <td className="tight cond">{r.employee_code}</td>
              <td className="tight">{r.name}</td>
              <td className="tight">{r.department}</td>
              <td style={{ fontSize: 12 }}>
                {(field === 'errors' ? r.errors : [...r.fixes, ...r.notes]).map((x) => <div key={x}>{x}</div>)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function GrantTable({ grants, unticked, onToggle }: { grants: PeopleImportGrant[]; unticked: Set<string>; onToggle: (k: string) => void }) {
  return (
    <div className="tw">
      <table>
        <thead><tr><th>Apply</th><th>Person</th><th>Service</th><th>Role</th><th>Why</th></tr></thead>
        <tbody>
          {grants.map((g) => (
            <tr key={g.key}>
              <td className="tight">
                <input type="checkbox" checked={!unticked.has(g.key)} onChange={() => onToggle(g.key)}
                  aria-label={`Apply ${g.service_name} for ${g.name}`} />
              </td>
              <td className="tight">{g.name} <span className="muted cond">{g.employee_code}</span></td>
              <td className="tight">{g.service_name}</td>
              <td className="tight">
                {g.from ? <span className="muted">{g.from} → </span> : null}
                <span className={`chip${g.kind === 'removed' || g.direction === 'down' ? ' wn' : ' pet'}`}>{g.to ?? 'no access'}</span>
              </td>
              <td className="tight muted">{SOURCE[g.source]}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
