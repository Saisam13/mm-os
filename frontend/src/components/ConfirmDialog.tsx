import React from 'react'

// Every destructive action confirms once, never twice (agents/A3-shell.md,
// Access page rules). One shared dialog so that rule can't be violated by
// a page forgetting to wire it.
export function ConfirmDialog({
  title,
  body,
  confirmLabel = 'Confirm',
  danger = true,
  busy = false,
  onConfirm,
  onCancel,
}: {
  title: string
  body: string
  confirmLabel?: string
  danger?: boolean
  busy?: boolean
  onConfirm: () => void
  onCancel: () => void
}) {
  return (
    <div className="confirm-scrim" role="presentation" onClick={onCancel}>
      <div
        className="confirm-box"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 id="confirm-title">{title}</h2>
        <p>{body}</p>
        <div className="row-actions">
          <button className="btn-q" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button className={danger ? 'btn-act' : 'btn-q'} onClick={onConfirm} disabled={busy}>
            {busy ? 'Working…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
