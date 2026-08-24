import React, { useEffect } from 'react'

// Shared slide-over used by People's edit drawer and Access's per-person
// drill-down (agents/A3-shell.md). One implementation so both behave and
// look identical.
export function Panel({
  open,
  onClose,
  eyebrow,
  title,
  children,
}: {
  open: boolean
  onClose: () => void
  eyebrow?: string
  title: string
  children: React.ReactNode
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  return (
    <>
      <div className={`scrim${open ? ' on' : ''}`} onClick={onClose} />
      <aside className={`panel${open ? ' on' : ''}`} aria-label={title} aria-hidden={!open}>
        <div className="panel-h">
          <div>
            {eyebrow ? <div className="eyebrow">{eyebrow}</div> : null}
            <h2 style={{ fontSize: 18 }}>{title}</h2>
          </div>
          <button className="x" onClick={onClose} aria-label="Close">
            &times;
          </button>
        </div>
        <div className="panel-b">{open ? children : null}</div>
      </aside>
    </>
  )
}
