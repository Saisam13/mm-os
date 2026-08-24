// Inline sparkline, ported from demo/console-directions.html (no charting
// dependency — the brief allows only fetch + React context beyond the fixed
// stack). Colour signals direction only when it's steep, per the demo: a
// sharp rise reads in orange (attention), everything else in cyan.
export function Spark({ points }: { points: number[] }) {
  if (points.length < 2) return <span className="muted">—</span>
  const w = 70
  const h = 20
  const max = Math.max(...points)
  const min = Math.min(...points)
  const span = max - min || 1
  const step = w / (points.length - 1)
  const coords = points.map((p, i) => {
    const x = i * step
    const y = h - 2 - ((p - min) / span) * (h - 4)
    return [x, y] as const
  })
  const rise = (points[points.length - 1] - points[0]) / (max || 1)
  const color = rise > 0.5 ? 'var(--orange)' : 'var(--cyan)'
  const last = coords[coords.length - 1]
  return (
    <svg className="spark" width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <polyline fill="none" stroke={color} strokeWidth="1.6" points={coords.map(([x, y]) => `${x},${y}`).join(' ')} />
      <circle cx={last[0]} cy={last[1]} r="2.2" fill={color} />
    </svg>
  )
}
