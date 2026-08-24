import React, { useState } from 'react'

// The LLM toggle asks for a reason (agents/A3-shell.md, Admin > LLM). Kept
// separate from ConfirmDialog because this one collects input rather than
// just confirming.
export function ReasonDialog({
  title,
  label,
  confirmLabel = 'Confirm',
  busy = false,
  onConfirm,
  onCancel,
}: {
  title: string
  label: string
  confirmLabel?: string
  busy?: boolean
  onConfirm: (reason: string) => void
  onCancel: () => void
}) {
  const [reason, setReason] = useState('')
  return (
    <div className="confirm-scrim" role="presentation" onClick={onCancel}>
      <div className="confirm-box" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <h2>{title}</h2>
        <div className="field">
          <label htmlFor="reason-input">{label}</label>
          <input
            id="reason-input"
            autoFocus
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && reason.trim()) onConfirm(reason.trim())
            }}
          />
        </div>
        <div className="row-actions">
          <button className="btn-q" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button className="btn-act" disabled={busy || !reason.trim()} onClick={() => onConfirm(reason.trim())}>
            {busy ? 'Working…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
