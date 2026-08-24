import React, { useEffect, useMemo, useRef, useState } from 'react'

export interface PaletteItem {
  id: string
  label: string
  kind: string
  run: () => void
}

// B's Search button and Ctrl/Cmd-K open this — brand/UI-DECISIONS.md
// § Console direction is explicit that the palette stays in direction B,
// just not as the centrepiece direction C would have made it.
export function CommandPalette({
  open,
  onClose,
  items,
}: {
  open: boolean
  onClose: () => void
  items: PaletteItem[]
}) {
  const [q, setQ] = useState('')
  const [sel, setSel] = useState(0)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) {
      setQ('')
      setSel(0)
      requestAnimationFrame(() => inputRef.current?.focus())
    }
  }, [open])

  const hits = useMemo(
    () => items.filter((i) => i.label.toLowerCase().includes(q.toLowerCase())).slice(0, 9),
    [items, q],
  )

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { onClose(); return }
      if (e.key === 'ArrowDown') { e.preventDefault(); setSel((s) => Math.min(s + 1, hits.length - 1)) }
      if (e.key === 'ArrowUp') { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)) }
      if (e.key === 'Enter') { const hit = hits[sel]; if (hit) { onClose(); hit.run() } }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose, hits, sel])

  if (!open) return null

  return (
    <div className="ovl on" onClick={(e) => { if (e.target === e.currentTarget) onClose() }}>
      <div className="pal" role="dialog" aria-label="Go to">
        <input
          ref={inputRef}
          value={q}
          onChange={(e) => { setQ(e.target.value); setSel(0) }}
          placeholder="Go to a service or page…"
          autoComplete="off"
        />
        <div className="pal-l">
          {hits.length === 0 ? (
            <div className="pal-empty">Nothing you can open matches that.</div>
          ) : (
            hits.map((h, i) => (
              <button
                key={h.id}
                className={`pal-i${i === sel ? ' sel' : ''}`}
                onMouseEnter={() => setSel(i)}
                onClick={() => { onClose(); h.run() }}
              >
                <span>{h.label}</span>
                <span className="r">{h.kind}</span>
              </button>
            ))
          )}
        </div>
        <div className="pal-f">
          <span>↑↓ move</span>
          <span>↵ open</span>
          <span>esc close</span>
        </div>
      </div>
    </div>
  )
}
