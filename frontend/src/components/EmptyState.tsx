// Every list is empty before it is full (agents/A3-shell.md). No marketing
// copy in the empty state either — a plain statement of what's there and,
// where it matters, what to do next.
export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="empty">
      <div className="t">{title}</div>
      {hint ? <div className="s">{hint}</div> : null}
    </div>
  )
}
