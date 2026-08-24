import React, { useState } from 'react'
import { deriveInitials } from '../lib/initials'

// Known third-party brand colours, used only as the fallback tile until the
// real mark lands in brand/service-marks/ (per brand/UI-DECISIONS.md § Service
// list). Anything not listed falls back to a neutral surface tile with its
// initial, so a new third-party service is never missing a mark either.
const THIRD_PARTY_COLOR: Record<string, string> = {
  erpnext: '#2490EF',
  twenty: '#1A1A1A',
}

export function ServiceMark({
  slug,
  name,
  kind,
  size = 36,
}: {
  slug: string
  name: string
  kind: 'in-house' | 'third-party'
  size?: number
}) {
  const [imgFailed, setImgFailed] = useState(false)
  const initial = kind === 'in-house' ? deriveInitials(name) : (name[0] || '?').toUpperCase()
  const style: React.CSSProperties = { width: size, height: size, flexBasis: size }

  if (kind === 'in-house') {
    return (
      <span className="svc-mark cond" style={{ ...style, background: 'var(--petrol)' }} aria-hidden="true">
        {deriveInitials(name)}
      </span>
    )
  }

  if (!imgFailed) {
    return (
      <span className="svc-mark" style={style} aria-hidden="true">
        <img
          src={`/service-marks/${slug}.svg`}
          alt=""
          onError={() => setImgFailed(true)}
        />
      </span>
    )
  }

  return (
    <span
      className="svc-mark cond"
      style={{ ...style, background: THIRD_PARTY_COLOR[slug] || 'var(--surface-3)', color: THIRD_PARTY_COLOR[slug] ? '#fff' : 'var(--text-3)' }}
      aria-hidden="true"
    >
      {initial}
    </span>
  )
}
